"""Where a converted file is written, including the game folder layout."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.output import game_folder_layout, output_for, system_folder_of
from aynthor.core.settings import FormatSettings


def _out(path: Path, fmt: CompressionFormat, settings: FormatSettings,
         options: dict | None = None, platform: str = "", member: str = "",
         mode: ConversionMode = ConversionMode.COMPRESS) -> Path:
    return output_for(path, fmt, mode, settings, options, platform, member)


def test_a_single_file_lands_in_a_folder_named_like_itself(tmp_path: Path):
    settings = FormatSettings(game_folders=True)
    source = tmp_path / "psx" / "Chrono Cross.cue"
    source.parent.mkdir(parents=True)
    result = _out(source, CompressionFormat.CHD, settings)
    assert result == tmp_path / "psx" / "Chrono Cross.chd" / "Chrono Cross.chd"


def test_disc_1_is_renamed_to_match_the_folder():
    assert game_folder_layout("Final Fantasy VIII (Disc 1).chd") == (
        "Final Fantasy VIII.chd", "Final Fantasy VIII.chd")


def test_disc_2_keeps_its_own_name_beside_the_primary():
    assert game_folder_layout("Final Fantasy VIII (Disc 2).chd") == (
        "Final Fantasy VIII.chd", "Final Fantasy VIII (Disc 2).chd")


def test_a_switch_base_game_is_the_file_the_folder_is_named_after(tmp_path: Path):
    settings = FormatSettings(output_dir=str(tmp_path / "out"), game_folders=True)
    result = _out(
        tmp_path / "Mario Kart 8 Deluxe.nsp", CompressionFormat.NSZ, settings,
        {"game_group": "Mario Kart 8 Deluxe", "content_type": "base"})
    assert result == (tmp_path / "out" / "Mario Kart 8 Deluxe.nsz"
                      / "Mario Kart 8 Deluxe.nsz")


def test_a_switch_update_keeps_its_own_name(tmp_path: Path):
    settings = FormatSettings(output_dir=str(tmp_path / "out"), game_folders=True)
    source = tmp_path / "sxs-mk8u_v1376256.nsp"
    result = _out(source, CompressionFormat.NSZ, settings,
                  {"game_group": "Mario Kart 8 Deluxe", "content_type": "update"})
    assert result == (tmp_path / "out" / "Mario Kart 8 Deluxe.nsz"
                      / "sxs-mk8u_v1376256.nsz")


def test_nsp_update_joins_existing_xci_base_folder(tmp_path: Path):
    """Base is Game.xci/Game.xci; Update/DLC are still .nsp and must not invent Game.nsp/."""
    settings = FormatSettings(output_dir=str(tmp_path / "out"), game_folders=True)
    update = tmp_path / "Ys X Nordics [0100BAC01E57E800][v196608].nsp"
    dlc = tmp_path / "Ys X Nordics Extra Pack [0100BAC01E57E001][v0].nsp"
    shared = {
        "game_group": "Ys X Nordics",
        "game_folder": "Ys X Nordics.xci",
    }
    update_out = _out(
        update, CompressionFormat.NSZ, settings,
        {**shared, "content_type": "Update"},
        mode=ConversionMode.MOVE)
    dlc_out = _out(
        dlc, CompressionFormat.NSZ, settings,
        {**shared, "content_type": "DLC"},
        mode=ConversionMode.MOVE)
    assert update_out == (
        tmp_path / "out" / "Ys X Nordics.xci" / update.name)
    assert dlc_out == (
        tmp_path / "out" / "Ys X Nordics.xci" / dlc.name)


def test_an_imported_list_title_names_the_folder(tmp_path: Path):
    settings = FormatSettings(output_dir=str(tmp_path / "out"), game_folders=True)
    result = _out(tmp_path / "game.iso", CompressionFormat.CHD, settings,
                  {"game_group": "Persona 4"}, platform="ps2")
    assert result == tmp_path / "out" / "Persona 4.chd" / "Persona 4.chd"


def test_a_file_already_in_a_game_folder_does_not_nest_again(tmp_path: Path):
    """A re-run used to produce Game.chd/Game.cue/Game.cue."""
    settings = FormatSettings(game_folders=True)
    source = tmp_path / "psx" / "Chrono Cross.cue" / "Chrono Cross.cue"
    source.parent.mkdir(parents=True)
    assert system_folder_of(source) == tmp_path / "psx"
    result = _out(source, CompressionFormat.CHD, settings)
    assert result == tmp_path / "psx" / "Chrono Cross.chd" / "Chrono Cross.chd"


def test_a_card_destination_puts_the_game_folder_in_the_platform_folder(tmp_path: Path):
    card = tmp_path / "ROMs"
    (card / "ps2").mkdir(parents=True)
    settings = FormatSettings(esde_root=str(card), game_folders=True)
    result = _out(tmp_path / "Downloads" / "game.iso", CompressionFormat.CHD,
                  settings, platform="ps2")
    assert result == card / "ps2" / "game.chd" / "game.chd"


def test_nds_trim_copies_into_a_game_folder(tmp_path: Path):
    settings = FormatSettings(game_folders=True)
    source = tmp_path / "nds" / "Ghost Trick.nds"
    source.parent.mkdir(parents=True)
    result = _out(source, CompressionFormat.NDS_TRIM, settings)
    assert result == tmp_path / "nds" / "Ghost Trick.nds" / "Ghost Trick.nds"


def test_unzipping_a_7z_does_not_grow_another_game_folder(tmp_path: Path):
    settings = FormatSettings(game_folders=True)
    source = tmp_path / "snes" / "Front Mission.7z"
    source.parent.mkdir(parents=True)
    result = _out(source, CompressionFormat.SEVEN_ZIP, settings,
                  mode=ConversionMode.DECOMPRESS)
    assert result == tmp_path / "snes" / "Front Mission"


def test_an_archive_member_is_named_after_the_rom_inside(tmp_path: Path):
    settings = FormatSettings(game_folders=True)
    archive = tmp_path / "ps2" / "download.zip"
    archive.parent.mkdir(parents=True)
    result = _out(archive, CompressionFormat.CHD, settings, platform="ps2",
                  member="Persona 4.iso")
    assert result == tmp_path / "ps2" / "Persona 4.chd" / "Persona 4.chd"


def test_game_folders_off_writes_beside_the_source(tmp_path: Path):
    source = tmp_path / "psx" / "Chrono Cross.cue"
    source.parent.mkdir(parents=True)
    result = _out(source, CompressionFormat.CHD, FormatSettings())
    assert result == tmp_path / "psx" / "Chrono Cross.chd"
