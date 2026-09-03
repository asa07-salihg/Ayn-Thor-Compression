"""What each direction is called, per format.

Why
    One verb does not cover all of these. A `.7z` is unzipped, a `.chd` is
    decompressed, a `.nds` is trimmed, and a `.cia` is decrypted; calling every
    one of them "open" told the user nothing about what they were about to get.
    So the label shows the destination (`-> CUE/ISO`) and the verb is the one
    that belongs to that format, which is what the queue and its menu print.

    Formats with one direction (WUA, Decrypt 3DS, NDS trim) declare exactly one
    entry, so nothing offers a reverse that does not exist.

Used by
    `ui.queue_view` (the Becomes cell and its menu),
    `ui.option_panels.BaseFormatPanel`.

Reference
    Direction support per tool: each converter module says what it can undo.
"""

from __future__ import annotations

from dataclasses import dataclass

from aynthor.core.models import CompressionFormat, ConversionMode


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
