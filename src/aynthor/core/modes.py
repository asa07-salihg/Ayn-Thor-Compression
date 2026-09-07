"""What each direction is called, per format.

Why
    One verb does not cover all of these. A `.7z` is unzipped, a `.chd` is
    decompressed, a `.nds` is trimmed, and a `.cia` is decrypted; calling every
    one of them "open" told the user nothing about what they were about to get.
    So the label shows the destination (`-> CUE/ISO`) and the verb is the one
    that belongs to that format, which is what the queue and its menu print.

    Formats with one direction (WUA, Decrypt 3DS, NDS trim) declare exactly one
    entry, so nothing offers a reverse that does not exist.

    A RAR/ZIP that was peeked into an NSZ row still offers Unzip (extract the
    member, do not compress), not Decompress — that word is for containers.

Used by
    `ui.queue_view` (the Becomes cell and its menu),
    `ui.option_panels.BaseFormatPanel`.

Reference
    Direction support per tool: each converter module says what it can undo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.unpack import is_archive


@dataclass(frozen=True)
class ModeInfo:
    mode: ConversionMode
    label: str        # what the dropdown shows
    description: str  # the verb: Compress, Decompress, Unzip, Trim padding...


FORMAT_MODES: dict[CompressionFormat, tuple[ModeInfo, ...]] = {
    CompressionFormat.CHD: (
        ModeInfo(ConversionMode.COMPRESS, "-> CHD", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> CUE/ISO", "Decompress"),
    ),
    CompressionFormat.RVZ: (
        ModeInfo(ConversionMode.COMPRESS, "-> RVZ", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ISO", "Decompress"),
    ),
    CompressionFormat.CSO: (
        ModeInfo(ConversionMode.COMPRESS, "-> CSO", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ISO", "Decompress"),
    ),
    CompressionFormat.Z3DS: (
        ModeInfo(ConversionMode.COMPRESS, "-> ZCCI", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> CCI/CIA", "Decompress"),
    ),
    CompressionFormat.NDS_TRIM: (
        ModeInfo(ConversionMode.COMPRESS, "-> Trimmed .nds", "Trim padding"),
    ),
    CompressionFormat.NSZ: (
        ModeInfo(ConversionMode.COMPRESS, "-> NSZ", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> NSP", "Decompress"),
    ),
    CompressionFormat.SEVEN_ZIP: (
        ModeInfo(ConversionMode.COMPRESS, "-> 7z/ZIP", "Bundle"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ROM", "Unzip"),
    ),
    CompressionFormat.WUA: (
        ModeInfo(ConversionMode.COMPRESS, "-> WUA", "Compress"),
    ),
    CompressionFormat.DEC_3DS: (
        ModeInfo(ConversionMode.COMPRESS, "-> Decrypted", "Decrypt"),
    ),
}


def source_is_archive(path: Path, member: str = "") -> bool:
    """True when the queued file is (or came from) a zip/7z/rar."""
    return bool(member) or is_archive(path)


def reverse_verb(fmt: CompressionFormat, *, from_archive: bool = False) -> str:
    """Menu label for the reverse action: Unzip vs Decompress."""
    if from_archive:
        # Peeked RAR/ZIP rows already are the inner ROM; Move vs convert only.
        return "Move"
    if fmt is CompressionFormat.SEVEN_ZIP:
        return "Unzip"
    for info in FORMAT_MODES.get(fmt, ()):
        if info.mode is ConversionMode.DECOMPRESS:
            return info.description
    return "Decompress"


def reverse_mode(fmt: CompressionFormat, *, from_archive: bool = False) -> ConversionMode:
    """What selecting Unzip/Decompress should set on the row.

    Archive members are extracted automatically at run time; the reverse for
    them is Move (place the ROM). Loose containers use DECOMPRESS.
    """
    if from_archive:
        return ConversionMode.MOVE
    return ConversionMode.DECOMPRESS


def becomes_label(
    fmt: CompressionFormat | None,
    mode: ConversionMode,
    *,
    from_archive: bool = False,
    intent: str = "",
) -> str:
    """What the Becomes column shows for this row."""
    if mode is ConversionMode.MOVE:
        return "Move"
    if fmt is None:
        return "?"
    if mode is ConversionMode.DECOMPRESS:
        return reverse_verb(fmt, from_archive=from_archive)
    return ""


def supports_reverse(fmt: CompressionFormat, *, from_archive: bool = False) -> bool:
    # Peeked archive rows: Move only + convert. No separate Unzip action.
    if from_archive:
        return False
    return any(m.mode is ConversionMode.DECOMPRESS for m in FORMAT_MODES.get(fmt, ()))
