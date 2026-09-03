"""The catalogue of formats, and the rules for naming an output file.

Why
    Three questions get asked about a format all over the app: which file
    extensions belong to it, which external tool implements it, and what the
    output should be called. Answering them in one table keeps the sidebar, the
    file dialogs, auto-detection and the queue from drifting apart -- a class of
    bug that already happened once: `.cci` was missing from the Decrypt 3DS
    extension list, so the file that ZCCI *Open* produces could not be
    decrypted at all.

Used by
    `ui.format_list` (sidebar entries), `ui.option_panels` (panel headers),
    `ui.queue_view` (which files a format will accept), `core.presets`
    (fallback when a platform guess fails), `ui.main_window` (folder scan).

Reference
    Per-format details, and why each platform gets the format it gets:
    each converter module under `core.converters`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aynthor.core.ctr.z3ds import CONTAINER_EXTENSIONS
from aynthor.core.models import CompressionFormat, ConversionMode


@dataclass(frozen=True)
class FormatInfo:
    format: CompressionFormat
    label: str
    platform: str
    extensions: tuple[str, ...]
    tool: str
    reason: str = ""  # why this format is the right target for that platform
    notes: str = ""   # shown above the format's options


FORMAT_CATALOG: tuple[FormatInfo, ...] = (
    FormatInfo(
        CompressionFormat.CHD,
        "CHD",
        "PS1, PS2, PSP, Dreamcast",
        (".cue", ".bin", ".iso", ".gdi", ".chd", ".img"),
        "chdman",
        reason="One file instead of a cue/bin pair, and every mainstream disc "
               "emulator reads it directly.",
        notes="PS2 on NetherSX2 needs zlib and hunk 2048; it cannot read zstd CHDs.",
    ),
    FormatInfo(
        CompressionFormat.RVZ,
        "RVZ",
        "GameCube, Wii",
        (".iso", ".wbfs", ".rvz", ".wia", ".gcz"),
        "DolphinTool",
        reason="Dolphin's own format. It drops the junk padding Nintendo discs "
               "are full of, which GCZ and WBFS keep.",
        notes="Defaults are Dolphin's: zstd level 5, block size 131072.",
    ),
    FormatInfo(
        CompressionFormat.CSO,
        "CSO",
        "PSP (alternative to CHD)",
        (".iso", ".cso", ".zso"),
        "maxcso",
        reason="Smaller than CHD on PSP titles, and PPSSPP reads it natively. "
               "Pick CHD instead if you want one format across all disc systems.",
        notes="ZSO trades a little size for much faster decompression on weak hardware.",
    ),
    FormatInfo(
        CompressionFormat.Z3DS,
        "ZCCI",
        "Nintendo 3DS",
        (".cci", ".cia", ".3ds", ".cxi", ".3dsx",
         ".zcci", ".zcia", ".zcxi", ".z3dsx", ".z3ds"),
        "rom-converto (or z3ds_compressor)",
        reason="The only compressed 3DS format Azahar loads directly. Around a "
               "quarter off a decrypted cart.",
        notes="The ROM must be decrypted first: encrypted bytes do not compress. "
              "Open restores the original file byte for byte.",
    ),
    FormatInfo(
        CompressionFormat.NDS_TRIM,
        "NDS trim",
        "Nintendo DS",
        (".nds",),
        "ndstrim",
        reason="melonDS will not read an archive, so trimming the unused tail of "
               "the cart is the only saving available.",
        notes="Optional. DS carts are small to begin with; this is worth doing "
              "only on the handful of titles with large padding.",
    ),
    FormatInfo(
        CompressionFormat.NSZ,
        "NSZ",
        "Nintendo Switch",
        (".nsp", ".xci", ".nsz", ".xcz"),
        "nsz",
        reason="Recompresses the NCA contents with zstd while leaving every "
               "signature intact, so installers still accept the file.",
        notes="Needs your own prod.keys. Base game, update and DLC are separate "
              "files and are compressed separately.",
    ),
    FormatInfo(
        CompressionFormat.SEVEN_ZIP,
        "7z / ZIP",
        "SNES, GBA, GB, GBC, Mega Drive, arcade",
        (".sfc", ".smc", ".gba", ".gb", ".gbc", ".md", ".gen", ".smd", ".7z", ".zip"),
        "7-Zip",
        reason="Cartridge ROMs are plain data and compress well. RetroArch opens "
               "7z transparently.",
        notes="Use ZIP for FBNeo and MAME: those cores expect a zipped romset and "
              "will not look inside a 7z.",
    ),
    FormatInfo(
        CompressionFormat.WUA,
        "WUA",
        "Wii U",
        (".wud", ".wux", ".wua"),
        "rom-converto",
        reason="Packs the game, its update and its DLC into a single archive that "
               "Cemu mounts as one title.",
        notes="A .wud or .wux disc image needs its disc key. There is no reverse "
              "direction: Cemu reads WUA, nothing converts back.",
    ),
    # Deliberately last. Auto-detect walks this catalogue in order and a .cia or
    # .3ds is far more often headed for compression than for decryption, so ZCCI
    # should win the extension race; Decrypt 3DS is chosen from the sidebar.
    FormatInfo(
        CompressionFormat.DEC_3DS,
        "Decrypt 3DS",
        "Nintendo 3DS (.cia / .3ds / .cci)",
        (".cia", ".3ds", ".cci"),
        "ctrtool + decrypt + makerom",
        reason="A cart dumped from a console is encrypted. Emulators can decrypt "
               "on the fly, compressors cannot -- so this has to happen first.",
        notes="Handles game, update, DLC and demo CIAs plus .3ds and .cci carts. "
              "DSiWare (TWL) titles are not supported.",
    ),
)

_BY_FORMAT = {info.format: info for info in FORMAT_CATALOG}


def format_info(fmt: CompressionFormat) -> FormatInfo | None:
    return _BY_FORMAT.get(fmt)


def detect_format(path: Path) -> FormatInfo | None:
    """First catalogue entry that claims this extension, or None."""
    ext = path.suffix.lower()
    for info in FORMAT_CATALOG:
        if ext in info.extensions:
            return info
    return None


def known_extensions() -> set[str]:
    """Every extension the app recognises, for folder scans and file dialogs."""
    return {ext for info in FORMAT_CATALOG for ext in info.extensions}


# --------------------------------------------------------------- output naming

_COMPRESS_SUFFIX = {
    CompressionFormat.CHD: ".chd",
    CompressionFormat.RVZ: ".rvz",
    CompressionFormat.CSO: ".cso",
    CompressionFormat.SEVEN_ZIP: ".7z",
    CompressionFormat.WUA: ".wua",
}

# A Z3DS container keeps the original container's identity in its extension, so
# Open can restore the right file without reading the header first.
_Z3DS_SUFFIX = {".cci": ".zcci", ".3ds": ".zcci", ".cia": ".zcia",
                ".cxi": ".zcxi", ".3dsx": ".z3dsx"}
_NSZ_SUFFIX = {".xci": ".xcz", ".nsp": ".nsz"}


def suggest_output_path(
    input_path: Path,
    target: CompressionFormat,
    mode: ConversionMode = ConversionMode.COMPRESS,
) -> Path:
    """Where the result should land, before output-folder and conflict rules."""
    if mode == ConversionMode.DECOMPRESS:
        return _decompressed_path(input_path, target)

    ext = input_path.suffix.lower()
    if target == CompressionFormat.NDS_TRIM:
        # ndstrim rewrites the cart in place; there is no second file.
        return input_path
    if target == CompressionFormat.DEC_3DS:
        # .3ds and .cci are both NCSD carts and both come back out as .cci.
        out_ext = ".cia" if ext == ".cia" else ".cci"
        return input_path.with_name(f"{input_path.stem}-decrypted{out_ext}")
    if target == CompressionFormat.Z3DS:
        return input_path.with_suffix(_Z3DS_SUFFIX.get(ext, ".z3ds"))
    if target == CompressionFormat.NSZ:
        return input_path.with_suffix(_NSZ_SUFFIX.get(ext, ".nsz"))
    return input_path.with_suffix(_COMPRESS_SUFFIX.get(target, ".out"))


def _decompressed_path(input_path: Path, target: CompressionFormat) -> Path:
    ext = input_path.suffix.lower()
    if target == CompressionFormat.CHD:
        # chdman writes a cue/bin pair for CD images and a flat .iso for DVDs;
        # the converter corrects this once it knows which extract command ran.
        return input_path.with_suffix(".cue")
    if target in (CompressionFormat.RVZ, CompressionFormat.CSO):
        return input_path.with_suffix(".iso")
    if target == CompressionFormat.Z3DS:
        return input_path.with_suffix(CONTAINER_EXTENSIONS.get(ext, ".cci"))
    if target == CompressionFormat.NSZ:
        return input_path.with_suffix(".xci" if ext == ".xcz" else ".nsp")
    if target == CompressionFormat.SEVEN_ZIP:
        # An archive expands into a folder, not a file.
        return input_path.parent / input_path.stem
    return input_path.with_suffix(".out")
