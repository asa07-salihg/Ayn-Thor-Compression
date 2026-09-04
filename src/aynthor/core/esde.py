"""ES-DE ROM folder names, and how to find the right one on a card.

Why
    Importing a list means turning "Chrono Cross -> psx" into a real file, and
    that only works if the app knows where ES-DE keeps PS1 games. The names are
    not guessable: SNES lives in `snes` on some setups and `sfc` on others,
    Mega Drive in `megadrive` or `genesis`, arcade in `fbneo`, `fba` or `mame`.
    Each platform therefore lists its alternatives and all of them are searched.

    `resolve_roms_root` exists because users select the wrong folder. Given an
    SD card root it finds `ROMs/` inside it; given `ROMs/` it uses it directly;
    given a folder that already contains `psx/` and friends it accepts that too.

Used by
    `core.romlist` (locating files named in a list), `core.presets`
    (platform guess for an ambiguous .iso), `ui.main_window` (folder audit).

Reference
    Folder names follow the ES-DE directory layout:
    https://github.com/retrogamecorps/ES-DE-Directories
"""

from __future__ import annotations

from pathlib import Path

# Ayn Thor list platform -> ES-DE subfolder names (primary + alternatives)
ESDE_PLATFORM_FOLDERS: dict[str, tuple[str, ...]] = {
    "psx": ("psx",),
    "ps2": ("ps2",),
    "psp": ("psp",),
    "dreamcast": ("dreamcast",),
    "gc": ("gc",),
    "wii": ("wii",),
    "n3ds": ("n3ds",),
    "switch": ("switch",),
    "snes": ("snes", "sfc", "snesna"),
    "gba": ("gba",),
    "megadrive": ("megadrive", "genesis", "megadrivejp"),
    "gb": ("gb",),
    "gbc": ("gbc",),
    "fbneo": ("fbneo", "fba"),
    "mame": ("mame", "mame-advmame"),
    # ES-DE's own arcade folders. Most cards use `arcade` or `neogeo` rather
    # than a core's name, and every one of these wants a zipped romset.
    "arcade": ("arcade", "neogeo", "cps", "cps1", "cps2", "cps3",
               "consolearcade", "pcarcade"),
    # Disc systems chdman handles. They were missing, so a .iso in ROMs/saturn
    # fell through to the PS2 guess and picked up createdvd and hunk 2048,
    # which are there for NetherSX2 and mean nothing to a Saturn core.
    "saturn": ("saturn", "saturnjp"),
    "segacd": ("segacd", "megacd", "megacdjp"),
    "pcenginecd": ("pcenginecd", "tg-cd"),
    "neogeocd": ("neogeocd", "neogeocdjp"),
    "3do": ("3do",),
    "pcfx": ("pcfx",),
    # Cartridge systems whose ROMs are plain data, same as SNES.
    "mastersystem": ("mastersystem", "mark3"),
    "gamegear": ("gamegear",),
    "sega32x": ("sega32x", "sega32xjp", "sega32xna"),
    "pcengine": ("pcengine", "tg16", "supergrafx"),
    "sg-1000": ("sg-1000",),
    "n64": ("n64",),
    "nds": ("nds",),
    "wiiu": ("wiiu",),
    "windows": ("windows", "ports", "pc"),
    "steam": ("steam",),
}

# Folder name -> platform. Built in two passes so a platform's own primary
# folder always wins: `fbneo` lists `mame` as an alternative, and a single pass
# let it claim the name before MAME itself could, so anything found in
# ROMs/mame was reported as FBNeo.
FOLDER_TO_PLATFORM: dict[str, str] = {}
for _platform, _folders in ESDE_PLATFORM_FOLDERS.items():
    FOLDER_TO_PLATFORM[_folders[0]] = _platform
for _platform, _folders in ESDE_PLATFORM_FOLDERS.items():
    for _folder in _folders[1:]:
        FOLDER_TO_PLATFORM.setdefault(_folder, _platform)

# Platforms that get compressed in the Ayn Thor list
COMPRESSIBLE_PLATFORMS: frozenset[str] = frozenset({
    "psx", "ps2", "psp", "dreamcast", "gc", "wii", "n3ds", "switch",
    "snes", "gba", "megadrive", "gb", "gbc", "fbneo", "mame", "arcade", "wiiu",
    "saturn", "segacd", "pcenginecd", "neogeocd", "3do", "pcfx",
    "mastersystem", "gamegear", "sega32x", "pcengine", "sg-1000",
})


def resolve_roms_root(selected: Path) -> Path:
    """Return the correct root when an SD card root or ROMs folder is selected."""
    selected = selected.resolve()
    if selected.name.lower() == "roms":
        return selected
    for child in ("ROMs", "roms"):
        candidate = selected / child
        if candidate.is_dir():
            return candidate
    # Root that already contains psx/gc etc. subfolders
    if any((selected / f).is_dir() for f in ("psx", "switch", "gc", "snes")):
        return selected
    return selected


def search_dirs(roms_root: Path, platform: str) -> list[Path]:
    """Return ES-DE folders to search for the platform."""
    root = resolve_roms_root(roms_root)
    folders = ESDE_PLATFORM_FOLDERS.get(platform, (platform,))
    dirs: list[Path] = []
    seen: set[Path] = set()
    for name in folders:
        for candidate in (root / name, roms_root / name):
            if candidate.is_dir() and candidate not in seen:
                seen.add(candidate)
                dirs.append(candidate)
    return dirs


def audit_folders(roms_root: Path, platforms: set[str] | None = None) -> dict[str, list[str]]:
    """Report which platform folders exist."""
    root = resolve_roms_root(roms_root)
    check = platforms or COMPRESSIBLE_PLATFORMS
    found: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    for platform in sorted(check):
        existing = [f for f in ESDE_PLATFORM_FOLDERS.get(platform, (platform,))
                    if (root / f).is_dir()]
        if existing:
            found[platform] = existing
        else:
            missing[platform] = list(ESDE_PLATFORM_FOLDERS.get(platform, (platform,)))
    return {"found": found, "missing": missing, "roms_root": str(root)}
