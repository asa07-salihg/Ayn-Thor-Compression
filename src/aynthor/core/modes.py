"""What "compress" and "open" are called in each format's Mode dropdown.

Why
    "Compress" and "Decompress" are the wrong words at the point of use. A user
    with a `.zcci` does not want to "decompress" it, they want their `.cci`
    back; a user with a `.nds` is not compressing anything, they are trimming
    padding. The dropdown therefore shows the destination (`-> CUE/ISO`) and
    the panel explains it. Formats with one direction (WUA, Decrypt 3DS, NDS
    trim) declare exactly one entry, so the dropdown shows no choice that does
    not exist.

Used by
    `ui.option_panels.BaseFormatPanel`, which builds the Mode dropdown from it.

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
    description: str  # what the action is called elsewhere in the interface


FORMAT_MODES: dict[CompressionFormat, tuple[ModeInfo, ...]] = {
    CompressionFormat.CHD: (
        ModeInfo(ConversionMode.COMPRESS, "-> CHD", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> CUE/ISO", "Open"),
    ),
    CompressionFormat.RVZ: (
        ModeInfo(ConversionMode.COMPRESS, "-> RVZ", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ISO", "Open"),
    ),
    CompressionFormat.CSO: (
        ModeInfo(ConversionMode.COMPRESS, "-> CSO", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ISO", "Open"),
    ),
    CompressionFormat.Z3DS: (
        ModeInfo(ConversionMode.COMPRESS, "-> ZCCI", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> CCI/CIA", "Open"),
    ),
    CompressionFormat.NDS_TRIM: (
        ModeInfo(ConversionMode.COMPRESS, "-> Trimmed .nds", "Trim padding"),
    ),
    CompressionFormat.NSZ: (
        ModeInfo(ConversionMode.COMPRESS, "-> NSZ", "Compress"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> NSP", "Open"),
    ),
    CompressionFormat.SEVEN_ZIP: (
        ModeInfo(ConversionMode.COMPRESS, "-> 7z/ZIP", "Bundle"),
        ModeInfo(ConversionMode.DECOMPRESS, "-> ROM", "Open"),
    ),
    CompressionFormat.WUA: (
        ModeInfo(ConversionMode.COMPRESS, "-> WUA", "Compress"),
    ),
    CompressionFormat.DEC_3DS: (
        ModeInfo(ConversionMode.COMPRESS, "-> Decrypted", "Decrypt"),
    ),
}
