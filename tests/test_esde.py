"""Finding the right ROM folder on a card."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.esde import (
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
