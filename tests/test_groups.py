"""Putting a queue row in a game folder, and the primary-name rule."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.groups import (
    assign_to_folder,
    best_disk_game_folder,
    discover_folders,
    discover_game_folders,
    group_folder_name,
    on_disk_members,
    rename_game_folder,
    unassign,
)
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.output import file_name_in_folder
from aynthor.core.settings import FormatSettings


def test_the_primary_rom_takes_the_folder_name_exactly():
    assert file_name_in_folder(
        "Final Fantasy VIII.chd", "Final Fantasy VIII (Disc 1).chd") == (
        "Final Fantasy VIII.chd")
    assert file_name_in_folder("Game.chd", "Game.chd") == "Game.chd"


def test_disc_2_and_updates_keep_their_own_names():
    assert file_name_in_folder(
        "Final Fantasy VIII.chd", "Final Fantasy VIII (Disc 2).chd") == (
        "Final Fantasy VIII (Disc 2).chd")
    assert file_name_in_folder(
        "Mario Kart 8 Deluxe.nsz", "sxs-mk8u_v1376256.nsz",
        {"content_type": "update"}) == "sxs-mk8u_v1376256.nsz"
    assert file_name_in_folder(
        "Mario Kart 8 Deluxe.nsz", "Booster Pass.nsz",
        {"content_type": "dlc"}) == "Booster Pass.nsz"


def test_dropping_onto_a_folder_renames_the_primary(tmp_path: Path):
    source = tmp_path / "Downloads" / "dump.cue"
    source.parent.mkdir()
    item = QueueItem(
        path=source, format=CompressionFormat.CHD, mode=ConversionMode.COMPRESS,
        output=source.with_suffix(".chd"),
    )
    assigned = assign_to_folder(item, "Final Fantasy VIII.chd", FormatSettings())
    assert assigned.output.parent.name == "Final Fantasy VIII.chd"
    assert assigned.output.name == "Final Fantasy VIII.chd"


def test_dropping_an_update_keeps_its_filename(tmp_path: Path):
    """Extras keep the folder they were dropped on — even when they become .nsz."""
    source = tmp_path / "sxs-mk8u_v1376256.nsp"
    item = QueueItem(
        path=source, format=CompressionFormat.NSZ, mode=ConversionMode.COMPRESS,
        output=source.with_suffix(".nsz"),
        content_type="Update",
        tool_options={"content_type": "update"},
    )
    assigned = assign_to_folder(item, "Mario Kart 8 Deluxe.nsp", FormatSettings())
    assert assigned.output.parent.name == "Mario Kart 8 Deluxe.nsp"
    assert assigned.output.name == "sxs-mk8u_v1376256.nsz"


def test_a_file_already_in_a_game_folder_groups_there(tmp_path: Path):
    source = tmp_path / "psx" / "Chrono Cross.chd" / "Chrono Cross.cue"
    source.parent.mkdir(parents=True)
    item = QueueItem(
        path=source, format=CompressionFormat.CHD, mode=ConversionMode.COMPRESS,
        output=tmp_path / "psx" / "Chrono Cross.chd" / "Chrono Cross.chd",
    )
    assert group_folder_name(item, FormatSettings()) == "Chrono Cross.chd"


def test_unassign_clears_the_forced_folder(tmp_path: Path):
    source = tmp_path / "game.cue"
    item = QueueItem(
        path=source, format=CompressionFormat.CHD, mode=ConversionMode.COMPRESS,
        output=source.with_suffix(".chd"),
    )
    assign_to_folder(item, "Game.chd", FormatSettings())
    unassign(item, FormatSettings())
    assert item.output == source.with_suffix(".chd")
    assert "game_folder" not in (item.tool_options or {})


def test_empty_game_folders_are_discovered(tmp_path: Path):
    empty = tmp_path / "psx" / "Final Fantasy VIII.chd"
    empty.mkdir(parents=True)
    filled = tmp_path / "snes" / "Front Mission.7z"
    filled.mkdir(parents=True)
    (filled / "Front Mission.7z").write_bytes(b"7z")
    (tmp_path / "psx" / "loose").mkdir()
    found = {p.name for p in discover_game_folders(tmp_path)}
    assert "Final Fantasy VIII.chd" in found
    assert "Front Mission.7z" in found
    assert "loose" not in found


def test_platform_folders_are_discovered_even_without_roms(tmp_path: Path):
    roms = tmp_path / "ROMs"
    (roms / "psx").mkdir(parents=True)
    (roms / "snes").mkdir()
    (roms / "psx" / "systeminfo.txt").write_text("psx")
    found = {p.name for p in discover_folders(roms)}
    assert "psx" in found
    assert "snes" in found
    assert "ROMs" not in found


def test_an_empty_directory_is_still_a_drop_target(tmp_path: Path):
    empty = tmp_path / "dumps"
    empty.mkdir()
    found = discover_folders(empty)
    assert found == [empty]


def test_best_disk_game_folder_picks_the_shortest_header(tmp_path: Path):
    """DLC/update names join by header; no keyword required."""
    platform = tmp_path / "switch"
    short = platform / "Ys X Nordics.nsp"
    short.mkdir(parents=True)
    long = platform / "Ys X Nordics Extra Pack.nsp"
    long.mkdir()
    (platform / "Other Game.nsp").mkdir()
    assert best_disk_game_folder(
        "Ys X Nordics ys x advanced pack", [short, long]) == short
    assert best_disk_game_folder("Other Game", [short, long]) is None


def test_best_disk_game_folder_works_for_disc_titles(tmp_path: Path):
    folder = tmp_path / "psx" / "Final Fantasy VIII.chd"
    folder.mkdir(parents=True)
    assert best_disk_game_folder(
        "Final Fantasy VIII", [folder]) == folder
    assert best_disk_game_folder(
        "Final Fantasy VIII (Disc 2)", [folder]) == folder


def test_rename_game_folder_keeps_the_extension(tmp_path: Path):
    folder = tmp_path / "Old Name.nsp"
    folder.mkdir()
    (folder / "Old Name.nsp").write_bytes(b"x")
    renamed = rename_game_folder(folder, "New Name")
    assert renamed.name == "New Name.nsp"
    assert renamed.is_dir()
    assert not folder.exists()


def test_on_disk_members_lists_files_in_the_game_folder(tmp_path: Path):
    folder = tmp_path / "Game.nsp"
    folder.mkdir()
    base = folder / "Game.nsp"
    base.write_bytes(b"base")
    extra = folder / "update.nsp"
    extra.write_bytes(b"upd")
    (folder / "readme.txt").write_text("no")
    members = on_disk_members(folder)
    assert base in members
    assert extra in members
    assert all(p.suffix.lower() != ".txt" for p in members)


def test_rename_game_folder_renames_the_primary_rom_too(tmp_path: Path):
    folder = tmp_path / "Old Title.nsp"
    folder.mkdir()
    primary = folder / "Old Title.nsp"
    primary.write_bytes(b"base")
    dlc = folder / "Old Title [DLC].nsp"
    dlc.write_bytes(b"dlc")

    renamed = rename_game_folder(folder, "New Title")

    assert renamed.name == "New Title.nsp"
    assert (renamed / "New Title.nsp").is_file()
    assert (renamed / "New Title.nsp").read_bytes() == b"base"
    assert (renamed / "Old Title [DLC].nsp").is_file()
    assert not (renamed / "Old Title.nsp").exists()
