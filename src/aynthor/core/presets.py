"""What each platform gets converted to, and with which settings.

Why
    Nobody wants to pick a format nine times for nine systems, so dropping a
    whole card into the window has to work without being told anything. The
    extension usually identifies the platform, and the platform decides both
    the format and the flags that platform's emulator actually needs.

    These choices used to be invisible: a PS2 file quietly became a zlib CHD
    with hunk 2048 and nothing said so, let alone let anyone change it. They
    are a `PresetTable` now, shown and edited in Settings, with the built-in
    values kept separately so any row can be put back.

    `.iso` is the awkward case, and the reason this looks at the whole path
    rather than the filename. A `.iso` can be PS2, PSP, GameCube or Wii, and
    those want different formats. The ES-DE folder it sits in is the only
    reliable signal, so `ROMs/gc/game.iso` becomes RVZ while `ROMs/ps2/game.iso`
    becomes CHD. With nothing to go on it falls back to PS2, which is the
    largest ISO library on a handheld of this class by a wide margin.

Used by
    `ui.queue_view` (every file added), `core.romlist` (imported lists),
    `ui.presets_page` (showing and editing them), `ui.state` (persisting the
    edits).

Reference
    Why each platform gets the format it gets: the `reason` on every entry
    below.
    Folder names: `core.esde`.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from aynthor.core.esde import FOLDER_TO_PLATFORM
from aynthor.core.formats import detect_format
from aynthor.core.models import CompressionFormat


@dataclass
class Preset:
    platform: str
    label: str          # what a person calls that system
    format: CompressionFormat
    options: dict = field(default_factory=dict)
    note: str = ""      # why these settings, when the reason is not obvious

    def copy(self) -> Preset:
        return Preset(self.platform, self.label, self.format,
                      copy.deepcopy(self.options), self.note)


# Order matters: this is the order the Settings page lists them in, grouped the
# way someone thinks about their card rather than alphabetically.
_BUILT_IN: tuple[Preset, ...] = (
    Preset("psx", "PlayStation", CompressionFormat.CHD,
           {"chd_type": "auto", "codecs": ["zlib"], "hunk_size": 0}),
    Preset("ps2", "PlayStation 2", CompressionFormat.CHD,
           {"chd_type": "createdvd", "codecs": ["zlib"], "hunk_size": 2048},
           note="Change this only if you are not using NetherSX2."),
    Preset("psp", "PSP", CompressionFormat.CHD,
           {"chd_type": "createdvd", "codecs": ["zlib"], "hunk_size": 2048},
           note="Switch the format to CSO if you would rather have the smaller file."),
    Preset("dreamcast", "Dreamcast", CompressionFormat.CHD,
           {"chd_type": "createcd", "codecs": ["zlib"], "hunk_size": 0}),
    Preset("gc", "GameCube", CompressionFormat.RVZ,
           {"out_fmt": "rvz", "codec": "zstd", "level": 5, "block_size": 131072},
           note="Dolphin's own defaults."),
    Preset("wii", "Wii", CompressionFormat.RVZ,
           {"out_fmt": "rvz", "codec": "zstd", "level": 5, "block_size": 131072},
           note="Dolphin's own defaults."),
    Preset("wiiu", "Wii U", CompressionFormat.WUA, {"level": 0}),
    Preset("n3ds", "Nintendo 3DS", CompressionFormat.Z3DS, {},
           note="Run Decrypt 3DS first; encrypted ROMs do not compress."),
    Preset("nds", "Nintendo DS", CompressionFormat.NDS_TRIM, {},
           note="melonDS reads no archive, so trimming the padding is all there is."),
    Preset("switch", "Nintendo Switch", CompressionFormat.NSZ,
           {"level": 18, "comp_mode": "auto"},
           note="Needs your own prod.keys."),
    Preset("snes", "SNES", CompressionFormat.SEVEN_ZIP, {"archive_type": "7z", "level": 9}),
    Preset("megadrive", "Mega Drive", CompressionFormat.SEVEN_ZIP,
           {"archive_type": "7z", "level": 9}),
    Preset("gba", "Game Boy Advance", CompressionFormat.SEVEN_ZIP,
           {"archive_type": "7z", "level": 9}),
    Preset("gb", "Game Boy", CompressionFormat.SEVEN_ZIP, {"archive_type": "7z", "level": 9}),
    Preset("gbc", "Game Boy Color", CompressionFormat.SEVEN_ZIP,
           {"archive_type": "7z", "level": 9}),
    Preset("fbneo", "Arcade (FBNeo)", CompressionFormat.SEVEN_ZIP,
           {"archive_type": "zip", "level": 9},
           note="Leave this on ZIP: FBNeo will not look inside a 7z."),
    Preset("mame", "Arcade (MAME)", CompressionFormat.SEVEN_ZIP,
           {"archive_type": "zip", "level": 9},
           note="Leave this on ZIP: MAME will not look inside a 7z."),
)


class PresetTable:
    """The platform table, with the built-in values kept for comparison.

    A copy of the defaults is held so the Settings page can show which rows have
    been changed and put any of them back, which matters here because several of
    the defaults exist to work around a specific emulator and are easy to break
    by accident.
    """

    def __init__(self, presets: tuple[Preset, ...] = _BUILT_IN) -> None:
        self._defaults = {p.platform: p for p in presets}
        self._current = {p.platform: p.copy() for p in presets}

    def __iter__(self) -> Iterator[Preset]:
        return iter(self._current.values())

    def __contains__(self, platform: object) -> bool:
        return platform in self._current

    def __len__(self) -> int:
        return len(self._current)

    def get(self, platform: str) -> Preset | None:
        return self._current.get(platform)

    def default(self, platform: str) -> Preset | None:
        return self._defaults.get(platform)

    def is_modified(self, platform: str) -> bool:
        current, original = self._current.get(platform), self._defaults.get(platform)
        if current is None or original is None:
            return False
        return (current.format, current.options) != (original.format, original.options)

    def set_format(self, platform: str, fmt: CompressionFormat) -> None:
        preset = self._current.get(platform)
        if preset is None:
            return
        if preset.format != fmt:
            # The options belong to the old format's tool and mean nothing to
            # the new one, so they go rather than being silently misapplied.
            preset.options = {}
        preset.format = fmt

    def set_options(self, platform: str, options: dict) -> None:
        preset = self._current.get(platform)
        if preset is not None:
            preset.options = copy.deepcopy(options)

    def reset(self, platform: str | None = None) -> None:
        if platform is None:
            self._current = {k: v.copy() for k, v in self._defaults.items()}
        elif platform in self._defaults:
            self._current[platform] = self._defaults[platform].copy()

    def overrides(self) -> dict[str, dict]:
        """Only what differs from the built-in table, for persisting."""
        changed: dict[str, dict] = {}
        for platform, preset in self._current.items():
            if self.is_modified(platform):
                changed[platform] = {
                    "format": preset.format.value,
                    "options": copy.deepcopy(preset.options),
                }
        return changed

    def apply_overrides(self, stored: dict[str, dict]) -> None:
        """Load saved edits. Anything unreadable is ignored, not fatal."""
        for platform, entry in (stored or {}).items():
            preset = self._current.get(platform)
            if preset is None or not isinstance(entry, dict):
                continue
            try:
                preset.format = CompressionFormat(entry.get("format", preset.format.value))
            except ValueError:
                continue
            options = entry.get("options")
            if isinstance(options, dict):
                preset.options = copy.deepcopy(options)


# The table the app runs on. A module-level instance because auto-detection is
# called from places that have no reason to be handed a settings object; every
# function that reads it also accepts one explicitly, so tests never touch this.
PRESETS = PresetTable()


# Platform guess from the extension alone.
EXT_TO_PLATFORM: dict[str, str] = {
    ".cue": "psx", ".bin": "psx", ".img": "psx", ".chd": "psx",
    ".iso": "ps2",  # refined below from the folder it sits in
    ".gdi": "dreamcast",
    ".cso": "psp", ".zso": "psp",
    ".wbfs": "wii", ".rvz": "gc", ".wia": "gc", ".gcz": "gc",
    ".cci": "n3ds", ".cia": "n3ds", ".3ds": "n3ds", ".cxi": "n3ds", ".3dsx": "n3ds",
    ".zcci": "n3ds", ".zcia": "n3ds", ".zcxi": "n3ds", ".z3ds": "n3ds", ".z3dsx": "n3ds",
    ".nds": "nds",
    ".nsp": "switch", ".xci": "switch", ".nsz": "switch", ".xcz": "switch",
    ".sfc": "snes", ".smc": "snes", ".7z": "snes",
    ".gba": "gba",
    ".md": "megadrive", ".gen": "megadrive", ".smd": "megadrive",
    ".gb": "gb", ".gbc": "gbc",
    ".zip": "fbneo",
    ".wud": "wiiu", ".wux": "wiiu", ".wua": "wiiu",
}

# An uncompressed .z64 is the most compatible form and the emulators that
# matter read nothing smaller, so this is a decision rather than a gap.
SKIP_EXTENSIONS = {".n64", ".v64", ".z64"}
SKIP_PLATFORMS = {"windows", "steam"}

# Which folder an ambiguous .iso is treated as when nothing else says.
_ISO_FALLBACK = "ps2"


@dataclass(frozen=True)
class DetectResult:
    format: CompressionFormat | None
    platform: str | None
    tool_options: dict
    skip: bool = False
    skip_reason: str = ""


def _platform_for_iso(path: Path) -> str:
    parts = [part.lower() for part in path.parts]
    for part in parts:
        if part in FOLDER_TO_PLATFORM:
            return FOLDER_TO_PLATFORM[part]
    for candidate in ("wii", "gc", "psp", "ps2"):
        if candidate in parts:
            return candidate
    return _ISO_FALLBACK


def detect_platform_format(path: Path, presets: PresetTable | None = None) -> DetectResult:
    table = presets if presets is not None else PRESETS
    extension = path.suffix.lower()

    if extension in SKIP_EXTENSIONS:
        return DetectResult(
            None, "n64", {}, skip=True,
            skip_reason="N64 is left uncompressed; .z64 is the most compatible form")

    platform = _platform_for_iso(path) if extension == ".iso" else EXT_TO_PLATFORM.get(extension)

    preset = table.get(platform) if platform else None
    if preset is not None:
        # A copy: the row that receives these will edit its own options.
        return DetectResult(preset.format, platform, copy.deepcopy(preset.options))

    info = detect_format(path)
    if info:
        return DetectResult(info.format, None, {})
    return DetectResult(None, None, {}, skip=True,
                        skip_reason="no format handles this extension")
