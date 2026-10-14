"""Turning a dropped file into the queue rows the runner will see."""

from __future__ import annotations

import zipfile
from pathlib import Path

from aynthor.core.intake import folder_label, queue_items_for
from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.settings import FormatSettings


def _zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as opened:
        for name, data in entries.items():
            opened.writestr(name, data)
    return path


def test_a_zip_holding_an_iso_in_ps2_queues_a_chd_row(tmp_path: Path):
    archive = _zip(tmp_path / "ROMs" / "ps2" / "Persona 4.zip",
                   {"Persona 4.iso": b"\0" * 16})
    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    assert len(items) == 1
    row = items[0]
    assert row.member == "Persona 4.iso"
    assert row.format is CompressionFormat.CHD
    assert row.platform == "ps2"
    assert row.display_name == "Persona 4.zip [Persona 4.iso]"
    assert row.output == tmp_path / "ROMs" / "ps2" / "Persona 4.chd"


def test_a_zip_in_fbneo_is_left_as_a_romset(tmp_path: Path):
    """Even a zip that happens to contain an .iso is a romset, not a disc.
    It is queued all the same, with nothing to do until it has somewhere
    else to go; the batch skips it."""
    archive = _zip(tmp_path / "ROMs" / "fbneo" / "kof97.zip",
                   {"kof97.iso": b"not really"})
    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    [row] = items
    assert row.member == ""
    assert row.mode is ConversionMode.COMPRESS
    assert row.output == archive


def test_a_finished_game_is_moved_once_there_is_a_card_to_put_it_on(tmp_path: Path):
    """Refusing `Game.chd` at the door meant it could never be copied to a card
    or a handheld. With a destination chosen it is a move."""
    game = tmp_path / "Downloads" / "Game.chd"
    game.parent.mkdir(parents=True)
    game.write_bytes(b"\0" * 64)
    card = tmp_path / "Card" / "ROMs"
    (card / "psx").mkdir(parents=True)

    items, reason = queue_items_for(game, FormatSettings(esde_root=str(card)))

    assert reason is None
    [row] = items
    assert row.mode is ConversionMode.MOVE


def test_a_finished_game_with_nowhere_to_go_is_still_queued(tmp_path: Path):
    game = tmp_path / "ROMs" / "psx" / "Game.chd"
    game.parent.mkdir(parents=True)
    game.write_bytes(b"\0" * 64)

    items, reason = queue_items_for(game, FormatSettings())

    assert reason is None
    assert len(items) == 1


def test_an_arcade_zip_is_placed_in_its_game_folder(tmp_path: Path):
    archive = _zip(tmp_path / "ROMs" / "fbneo" / "kof97.zip",
                   {"kof97.iso": b"not really"})
    items, reason = queue_items_for(archive, FormatSettings(game_folders=True))
    assert reason is None
    row = items[0]
    assert row.member == ""
    assert row.output == tmp_path / "ROMs" / "fbneo" / "kof97.zip" / "kof97.zip"


def test_a_loose_7z_in_snes_is_copied_into_its_game_folder(tmp_path: Path):
    archive = tmp_path / "ROMs" / "snes" / "Front Mission.7z"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"7z")
    items, reason = queue_items_for(archive, FormatSettings(game_folders=True))
    assert reason is None
    assert len(items) == 1
    row = items[0]
    assert row.member == ""
    assert row.format is CompressionFormat.SEVEN_ZIP
    assert row.mode is ConversionMode.MOVE
    assert row.output == (tmp_path / "ROMs" / "snes" / "Front Mission.7z"
                          / "Front Mission.7z")


def test_a_zip_of_a_cartridge_rom_becomes_7z_in_a_game_folder(tmp_path: Path):
    archive = _zip(tmp_path / "ROMs" / "snes" / "Mario.zip",
                   {"Mario.sfc": b"\0" * 16})
    items, reason = queue_items_for(archive, FormatSettings(game_folders=True))
    assert reason is None
    row = items[0]
    assert row.member == "Mario.sfc"
    assert row.format is CompressionFormat.SEVEN_ZIP
    assert row.output == tmp_path / "ROMs" / "snes" / "Mario.7z" / "Mario.7z"


def test_a_zip_in_snes_is_not_skipped_as_an_arcade_romset(tmp_path: Path):
    """`.zip` used to mean FBNeo, so a cartridge zip with no inner ROM the
    app recognised was skipped as 'already a zip' while the same title as
    `.7z` was queued."""
    archive = _zip(tmp_path / "ROMs" / "snes" / "Mario.zip",
                   {"readme.txt": b"hi"})
    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    assert len(items) == 1
    row = items[0]
    assert row.member == ""
    assert row.platform == "snes"
    assert row.format is CompressionFormat.SEVEN_ZIP
    assert row.output.suffix == ".7z"


def test_an_unreadable_zip_in_snes_still_queues_as_7z(tmp_path: Path):
    """Python's zipfile cannot open every zip 7za can. Treat it as the
    cartridge archive the folder says it is, not as an arcade romset."""
    archive = tmp_path / "ROMs" / "snes" / "Mario.zip"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"not a zip")
    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    assert len(items) == 1
    assert items[0].platform == "snes"
    assert items[0].output.suffix == ".7z"


def test_a_zip_in_psx_with_no_disc_inside_is_not_queued_as_chd(tmp_path: Path):
    """The folder is PlayStation, but chdman cannot read a zip. Skip rather
    than queue a job that cannot run."""
    archive = _zip(tmp_path / "ROMs" / "psx" / "Empty.zip", {"readme.txt": b"hi"})
    items, reason = queue_items_for(archive, FormatSettings())
    assert items == []
    assert reason is not None
    assert "already a zip" not in reason


def test_a_rar_holding_an_nsp_is_queued_as_nsz(tmp_path: Path, monkeypatch):
    """Switch dumps often arrive as RAR. 7za cannot read those; the ROM
    inside still has to become the queue row."""
    from aynthor.core.unpack import Member

    archive = tmp_path / "DANGANRONPA-V3-KILLING-HARMONY-ANNIVERSARY-EDITION-NSP.rar"
    archive.write_bytes(b"Rar!\x1a\x07\x00")
    monkeypatch.setattr(
        "aynthor.core.intake.list_members",
        lambda _path: [Member("Danganronpa V3.nsp", 16)],
    )
    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    assert len(items) == 1
    row = items[0]
    assert row.member == "Danganronpa V3.nsp"
    assert row.format is CompressionFormat.NSZ
    assert row.platform == "switch"


def test_adding_a_folder_labels_rows_from_the_folder_name(tmp_path: Path):
    roms = tmp_path / "ROMs"
    file = roms / "psx" / "Final Fantasy VIII.chd" / "Final Fantasy VIII.cue"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"cue")
    label = folder_label(roms / "psx", file)
    assert label == "psx/Final Fantasy VIII.chd/Final Fantasy VIII.cue"
    items, reason = queue_items_for(
        file, FormatSettings(game_folders=True), label=label)
    assert reason is None
    assert items[0].display_name == label


def test_a_file_added_on_its_own_keeps_the_bare_name(tmp_path: Path):
    source = tmp_path / "Chrono Cross.cue"
    source.write_bytes(b"cue")
    items, reason = queue_items_for(source, FormatSettings())
    assert reason is None
    assert items[0].display_name == "Chrono Cross.cue"
    assert items[0].label == ""


def test_four_discs_in_one_zip_share_the_game_name(tmp_path: Path):
    archive = _zip(tmp_path / "Final Fantasy VIII.zip", {
        "FF8 (Disc 1).iso": b"1",
        "FF8 (Disc 2).iso": b"2",
        "FF8 (Disc 3).iso": b"3",
        "FF8 (Disc 4).iso": b"4",
    })
    items, reason = queue_items_for(archive, FormatSettings(game_folders=True))
    assert reason is None
    assert len(items) == 4
    assert {row.member for row in items} == {
        "FF8 (Disc 1).iso", "FF8 (Disc 2).iso",
        "FF8 (Disc 3).iso", "FF8 (Disc 4).iso",
    }
    assert {row.game_group for row in items} == {"Final Fantasy VIII"}
    folders = {row.output.parent.name for row in items}
    assert folders == {"Final Fantasy VIII.chd"}
    names = {row.output.name for row in items}
    assert "Final Fantasy VIII.chd" in names
    assert "FF8 (Disc 2).chd" in names


def test_an_archive_of_several_games_is_not_one_game(tmp_path: Path):
    """Every member was named after the archive, so a compilation zip sent
    three cartridges to one path: `SNES Favourites.7z/SNES Favourites.7z`.
    Two of the three games were destroyed on the way."""
    snes = tmp_path / "ROMs" / "snes"
    archive = _zip(snes / "SNES Favourites.zip", {
        "Super Mario World.sfc": b"a" * 64,
        "Chrono Trigger.sfc": b"b" * 64,
        "Secret of Mana.sfc": b"c" * 64,
    })
    settings = FormatSettings()
    settings.game_folders = True

    items, _ = queue_items_for(archive, settings)
    assert len({item.output for item in items}) == 3
    assert not any(item.game_group == "SNES Favourites" for item in items)


def test_an_archive_of_one_game_is_still_one_folder(tmp_path: Path):
    """The grouping rule that exists for a four-disc set still holds."""
    ps2 = tmp_path / "ROMs" / "ps2"
    archive = _zip(ps2 / "Final Fantasy VII.zip", {
        "Final Fantasy VII (Disc 1).cue": b"a" * 64,
        "Final Fantasy VII (Disc 2).cue": b"b" * 64,
    })
    settings = FormatSettings()
    settings.game_folders = True

    items, _ = queue_items_for(archive, settings)
    assert {item.output.parent.name for item in items} == {"Final Fantasy VII.chd"}
    assert len({item.output for item in items}) == 2


def test_a_readable_rar_with_nothing_inside_does_not_blame_the_tool(
    tmp_path: Path, monkeypatch,
):
    """The "install 7-Zip" message fired whenever nothing convertible was
    found, so a RAR of cover art opened perfectly well and then told the user
    to install a tool that was already working."""
    from aynthor.core import intake

    archive = tmp_path / "Extras.rar"
    archive.write_bytes(b"not really a rar")
    monkeypatch.setattr(intake, "list_members", lambda _path: [])

    _items, reason = queue_items_for(archive, FormatSettings())
    assert reason and "install 7-Zip" not in reason
