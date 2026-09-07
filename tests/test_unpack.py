"""Listing and opening ZIP/7z archives that hold a ROM."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from aynthor.core.unpack import (
    UnpackError,
    extract_all,
    list_members,
    rom_members,
    should_peek,
    unpacked,
)


def _zip_with(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as opened:
        for name, data in entries.items():
            opened.writestr(name, data)
    return path


def test_a_zip_lists_its_files(tmp_path: Path):
    archive = _zip_with(tmp_path / "game.zip", {
        "game.iso": b"iso",
        "readme.txt": b"hi",
        "art/cover.png": b"png",
    })
    names = [m.name for m in list_members(archive)]
    assert names == ["game.iso", "readme.txt", "art/cover.png"]


def test_a_cue_sheet_is_queued_and_its_bins_are_not(tmp_path: Path):
    members = list_members(_zip_with(tmp_path / "disc.zip", {
        "game.cue": b"FILE \"game.bin\" BINARY",
        "game.bin": b"\0" * 16,
        "track2.bin": b"\0" * 16,
    }))
    assert rom_members(members) == ["game.cue"]


def test_an_iso_is_skipped_when_the_same_disc_already_has_a_cue(tmp_path: Path):
    members = list_members(_zip_with(tmp_path / "disc.zip", {
        "game.cue": b"FILE \"game.bin\" BINARY",
        "game.bin": b"\0" * 16,
        "game.iso": b"iso",
    }))
    assert rom_members(members) == ["game.cue"]


def test_every_disc_in_a_zip_is_queued(tmp_path: Path):
    members = list_members(_zip_with(tmp_path / "game.zip", {
        "Game (Disc 1).iso": b"1",
        "Game (Disc 2).iso": b"2",
        "Game (Disc 3).iso": b"3",
        "Game (Disc 4).iso": b"4",
        "readme.txt": b"hi",
    }))
    assert rom_members(members) == [
        "Game (Disc 1).iso",
        "Game (Disc 2).iso",
        "Game (Disc 3).iso",
        "Game (Disc 4).iso",
    ]


def test_cues_in_disc_subfolders_are_each_a_row(tmp_path: Path):
    members = list_members(_zip_with(tmp_path / "game.zip", {
        "Disc 1/game.cue": b"FILE \"game.bin\" BINARY",
        "Disc 1/game.bin": b"\0",
        "Disc 2/game.cue": b"FILE \"game.bin\" BINARY",
        "Disc 2/game.bin": b"\0",
    }))
    assert rom_members(members) == ["Disc 1/game.cue", "Disc 2/game.cue"]


def test_a_bin_only_set_is_not_treated_as_a_rom(tmp_path: Path):
    """MAME romsets are full of .bin files. Those must stay archives."""
    members = list_members(_zip_with(tmp_path / "kof97.zip", {
        "kof97.bin": b"\0",
        "kof97.img": b"\0",
    }))
    assert rom_members(members) == []


def test_a_nested_archive_is_ignored(tmp_path: Path):
    members = list_members(_zip_with(tmp_path / "outer.zip", {
        "inner.zip": b"PK",
        "game.iso": b"iso",
    }))
    assert rom_members(members) == ["game.iso"]


def test_a_member_that_escapes_the_folder_is_refused(tmp_path: Path):
    archive = _zip_with(tmp_path / "evil.zip", {"../evil.iso": b"no"})
    with pytest.raises(UnpackError, match="escapes"):
        extract_all(archive, tmp_path / "into")


def test_unpacked_yields_the_member_and_removes_the_scratch(tmp_path: Path):
    archive = _zip_with(tmp_path / "game.zip", {"game.iso": b"disc-image"})
    with unpacked(archive, "game.iso") as inner:
        assert inner.read_bytes() == b"disc-image"
        scratch = inner.parent
        assert scratch.is_dir()
    assert not scratch.exists()
    leftovers = list(tmp_path.glob(".aynthor-unpack-*"))
    assert leftovers == []


def test_one_extraction_serves_every_member(tmp_path: Path):
    from aynthor.core.unpack import ArchiveScratch

    archive = _zip_with(tmp_path / "game.zip", {
        "disc1.iso": b"one",
        "disc2.iso": b"two",
    })
    scratch = ArchiveScratch(archive)
    try:
        assert scratch.path_for("disc1.iso").read_bytes() == b"one"
        assert scratch.path_for("disc2.iso").read_bytes() == b"two"
        assert scratch.root.is_dir()
    finally:
        scratch.close()
    assert not scratch.root.exists()


def test_an_arcade_folder_is_never_peeked(tmp_path: Path):
    assert should_peek(tmp_path / "ROMs" / "fbneo" / "kof97.zip") is False
    assert should_peek(tmp_path / "ROMs" / "mame" / "pacman.zip") is False
    assert should_peek(tmp_path / "ROMs" / "neogeo" / "kof97.zip") is False


def test_a_zip_of_an_iso_is_peeked(tmp_path: Path):
    assert should_peek(tmp_path / "ROMs" / "ps2" / "game.zip") is True
    assert should_peek(tmp_path / "Downloads" / "game.zip") is True


def test_a_7z_is_only_peeked_when_the_platform_does_not_want_one(tmp_path: Path):
    assert should_peek(tmp_path / "ROMs" / "snes" / "game.7z") is False
    assert should_peek(tmp_path / "ROMs" / "psx" / "game.7z") is True
    assert should_peek(tmp_path / "Downloads" / "game.7z") is False


def test_a_rar_is_always_peeked(tmp_path: Path):
    """RAR is never a destination format, so the ROM inside is the file."""
    assert should_peek(tmp_path / "Downloads" / "game.rar") is True
    assert should_peek(tmp_path / "ROMs" / "switch" / "game.rar") is True


def test_path_for_finds_a_nested_member_when_the_folder_name_differs(tmp_path: Path):
    """7-Zip can list one path and write another (encoding / sanitised names)."""
    from aynthor.core.unpack import ArchiveScratch

    archive = _zip_with(tmp_path / "game.zip", {
        "Folder (US)/game.nsp": b"rom",
    })
    scratch = ArchiveScratch(archive)
    try:
        # Simulate extract landing under a different folder spelling.
        written = scratch.path_for("Folder (US)/game.nsp")
        alt_dir = scratch.root / "Folder _US_"
        alt_dir.mkdir()
        target = alt_dir / "game.nsp"
        written.replace(target)
        written.parent.rmdir()
        assert scratch.path_for("Folder (US)/game.nsp") == target
    finally:
        scratch.close()


def test_path_for_matches_when_underscores_replace_spaces(tmp_path: Path):
    """Listing vs disk spelling: `Ys X_ Nordics….nsp` vs `Ys X Nordics….nsp`."""
    from aynthor.core.unpack import ArchiveScratch

    archive = _zip_with(tmp_path / "upd.zip", {
        "folder/Ys X Nordics [0100](Update).nsp": b"update-rom",
    })
    scratch = ArchiveScratch(archive)
    try:
        written = next(scratch.root.rglob("*.nsp"))
        mangled = written.with_name("Ys X_ Nordics [0100](Update).nsp")
        written.replace(mangled)
        assert scratch.path_for(
            "folder/Ys X Nordics [0100](Update).nsp"
        ).read_bytes() == b"update-rom"
    finally:
        scratch.close()


def test_path_for_still_errors_when_the_rom_is_missing(tmp_path: Path):
    from aynthor.core.unpack import ArchiveScratch

    archive = _zip_with(tmp_path / "game.zip", {"other.nsp": b"x"})
    scratch = ArchiveScratch(archive)
    try:
        with pytest.raises(UnpackError, match="was not in"):
            scratch.path_for("missing.nsp")
    finally:
        scratch.close()


def test_extract_member_to_writes_straight_to_the_destination(tmp_path: Path):
    """Move must not leave a second .aynthor-unpack copy beside the game folder."""
    from aynthor.core.unpack import extract_member_to

    archive = _zip_with(tmp_path / "Game.zip", {"Game.nsp": b"nsp-bytes-here"})
    dest = tmp_path / "switch" / "Game.nsp" / "Game.nsp"
    seen: list[int] = []

    extract_member_to(archive, "Game.nsp", dest, on_progress=seen.append)

    assert dest.read_bytes() == b"nsp-bytes-here"
    leftovers = [
        path for path in tmp_path.rglob("*")
        if path.is_dir() and path.name.startswith(".aynthor-")
    ]
    assert leftovers == [], leftovers
    assert seen and seen[-1] == 100


def test_extract_member_to_handles_brackets_in_switch_names(tmp_path: Path):
    """7-Zip treats [0100…] as a wildcard mask and would extract nothing."""
    from aynthor.core.unpack import extract_member_to, _safe_7z_mask

    member = (
        "Ys X_ Nordics (NSP)(US)(Update 1.0.3)/"
        "Ys X_ Nordics [0100BAC01E57E800][v196608](Update 1.0.3).nsp"
    )
    assert _safe_7z_mask(member) == "*0100BAC01E57E800*"

    archive = _zip_with(tmp_path / "upd.zip", {
        member.replace("\\", "/"): b"update-bytes",
    })
    dest = tmp_path / "game" / "Update.nsp"
    extract_member_to(archive, member.replace("\\", "/"), dest)
    assert dest.read_bytes() == b"update-bytes"
