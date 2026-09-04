"""Finding the right ROM folder on a card."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.esde import (
    COMPRESSIBLE_PLATFORMS,
    ESDE_PLATFORM_FOLDERS,
    FOLDER_TO_PLATFORM,
    audit_folders,
    resolve_roms_root,
    search_dirs,
)


def test_card_root_resolves_to_the_roms_folder(roms_root: Path):
    """Users select the card, not the ROMs folder inside it."""
    assert resolve_roms_root(roms_root.parent) == roms_root


def test_roms_folder_resolves_to_itself(roms_root: Path):
    assert resolve_roms_root(roms_root) == roms_root


def test_a_folder_that_already_holds_platforms_is_accepted(tmp_path: Path):
    root = tmp_path / "games"
    (root / "psx").mkdir(parents=True)
    (root / "snes").mkdir()
    assert resolve_roms_root(root) == root


def test_alternative_folder_names_are_searched(tmp_path: Path):
    """SNES is `snes` on some setups and `sfc` on others."""
    root = tmp_path / "ROMs"
    (root / "sfc").mkdir(parents=True)
    found = search_dirs(root, "snes")
    assert [p.name for p in found] == ["sfc"]


def test_search_returns_nothing_when_the_platform_has_no_folder(roms_root: Path):
    assert search_dirs(roms_root, "wiiu") == []


def test_audit_separates_present_from_absent(roms_root: Path):
    audit = audit_folders(roms_root, {"psx", "wiiu"})
    assert "psx" in audit["found"]
    assert "wiiu" in audit["missing"]


def test_every_platform_maps_back_from_its_folders():
    for platform, folders in ESDE_PLATFORM_FOLDERS.items():
        assert FOLDER_TO_PLATFORM[folders[0]] == platform


def test_folder_lookup_has_no_empty_entries():
    assert all(folders for folders in ESDE_PLATFORM_FOLDERS.values())


# ------------------------------------------ the folders ES-DE actually ships

@pytest.mark.parametrize("folder, platform", [
    # Arcade. Most cards use one of these rather than a core's name, and every
    # one of them wants a zipped romset.
    ("arcade", "arcade"),
    ("neogeo", "arcade"),
    ("cps2", "arcade"),
    ("mame", "mame"),
    ("fbneo", "fbneo"),
    # Disc systems chdman handles. Before these were listed, a .iso in
    # ROMs/saturn fell through to the PS2 guess and picked up createdvd and
    # hunk 2048, which exist for NetherSX2 and mean nothing to a Saturn core.
    ("saturn", "saturn"),
    ("saturnjp", "saturn"),
    ("segacd", "segacd"),
    ("megacd", "segacd"),
    ("pcenginecd", "pcenginecd"),
    ("tg-cd", "pcenginecd"),
    ("neogeocd", "neogeocd"),
    ("3do", "3do"),
    # Cartridge systems, plain data like SNES.
    ("mastersystem", "mastersystem"),
    ("gamegear", "gamegear"),
    ("sega32x", "sega32x"),
    ("pcengine", "pcengine"),
    ("tg16", "pcengine"),
    ("snesna", "snes"),
    ("megadrivejp", "megadrive"),
])
def test_the_folder_maps_to_the_platform_it_belongs_to(folder, platform):
    assert FOLDER_TO_PLATFORM[folder] == platform


def test_every_folder_the_app_knows_is_a_real_esde_folder():
    """Checked against ES-DE's own es_systems.xml. A folder that does not exist
    upstream is dead weight that only shadows a name that does."""
    real = {
        "psx", "ps2", "psp", "dreamcast", "gc", "wii", "n3ds", "switch", "nds",
        "wiiu", "n64", "snes", "sfc", "snesna", "gba", "gb", "gbc",
        "megadrive", "genesis", "megadrivejp", "mastersystem", "mark3",
        "gamegear", "sega32x", "sega32xjp", "sega32xna", "sg-1000",
        "pcengine", "tg16", "supergrafx", "pcenginecd", "tg-cd", "pcfx",
        "saturn", "saturnjp", "segacd", "megacd", "megacdjp", "3do",
        "neogeo", "neogeocd", "neogeocdjp", "arcade", "mame", "mame-advmame",
        "fbneo", "fba", "cps", "cps1", "cps2", "cps3", "consolearcade",
        "pcarcade", "windows", "ports", "pc", "steam",
    }
    unknown = sorted(set(FOLDER_TO_PLATFORM) - real)
    assert unknown == []


def test_every_compressible_platform_has_a_preset():
    """A folder that resolves to a platform with no preset is a file the app
    recognises and then does nothing sensible with."""
    from aynthor.core.presets import PRESETS

    missing = sorted(p for p in COMPRESSIBLE_PLATFORMS if PRESETS.get(p) is None)
    assert missing == []
