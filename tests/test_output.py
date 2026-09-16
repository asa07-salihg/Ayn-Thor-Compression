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


# --------------------------------------------------------------------------
# Regressions from the 1.3.2 audit.


def test_a_zero_padded_disc_one_is_still_disc_one():
    """The disc token was compared as text, so `01` was not disc 1. A
    redump-style set produced `Final Fantasy VII.chd/` holding only
    `(Disc 01)`, `(Disc 02)` and `(Disc 03)` -- a game folder with no file
    matching its own name, which ES-DE hands to the emulator as a directory."""
    folder, name = game_folder_layout("Final Fantasy VII (Disc 01).chd")
    assert (folder, name) == ("Final Fantasy VII.chd", "Final Fantasy VII.chd")
    folder, name = game_folder_layout("Final Fantasy VII (Disc 02).chd")
    assert (folder, name) == (
        "Final Fantasy VII.chd", "Final Fantasy VII (Disc 02).chd")


def test_a_multi_disc_archive_keeps_its_discs_apart():
    """`Disc 1/Game.iso` and `Disc 2/Game.iso` are one game whose discs are
    told apart by their folders. Naming the output after the file alone gave
    both rows the same path and one disc overwrote the other."""
    from aynthor.core.output import member_name

    assert member_name("Disc 1/Game.iso") == "Game (Disc 1).iso"
    assert member_name("Disc 2/Game.iso") == "Game (Disc 2).iso"
    assert member_name("Game.iso") == "Game.iso"
    # A disc tag already in the name is left alone.
    assert member_name("CD 2/Game (Disc 2).iso") == "Game (Disc 2).iso"


def test_a_title_with_a_full_stop_in_it_survives_disc_stripping():
    """`strip_disc_tag` used `Path.stem`, which cuts at the last dot. "New
    Super Mario Bros. U Deluxe" came back as "New Super Mario Bros", so an
    update never matched the folder of that name already on the card."""
    from aynthor.core.output import strip_disc_tag

    assert strip_disc_tag("New Super Mario Bros. U Deluxe") == \
        "New Super Mario Bros. U Deluxe"
    assert strip_disc_tag("Game (Disc 2).chd") == "Game"


def test_a_name_is_trimmed_after_it_is_cut_to_length():
    """Trimming and then truncating can put a trailing space or dot back on
    the end, and Windows will create such a folder and then refuse to open
    it."""
    from aynthor.core.output import safe_folder_name

    name = "A" * 119 + " tail"
    assert not safe_folder_name(name).endswith((" ", "."))
    assert safe_folder_name("Tab\there") == "Tab_here"


def test_joining_a_folder_that_already_has_its_primary_keeps_the_new_name():
    """Otherwise the joined file is given the folder's own name, which is the
    path of the ROM already sitting there: with overwrite selected the extra
    was copied straight over the base game."""
    from aynthor.core.output import file_name_in_folder

    assert file_name_in_folder(
        "Ys X Nordics.nsp", "Ys X Nordics Extra.nsp", {"keep_name": True},
    ) == "Ys X Nordics Extra.nsp"
    assert file_name_in_folder(
        "Ys X Nordics.nsp", "Ys X Nordics.nsp", {},
    ) == "Ys X Nordics.nsp"


def test_the_roms_root_cache_can_be_dropped(tmp_path: Path):
    """Someone who points the app at a blank card and then copies an ES-DE
    tree onto it has changed the answer. The cache is only true for the length
    of one fill."""
    from aynthor.core.output import forget_roms_root, platform_destination

    settings = FormatSettings()
    settings.esde_root = str(tmp_path)
    assert platform_destination(settings, "psx") == tmp_path / "psx"

    (tmp_path / "ROMs").mkdir()
    forget_roms_root()
    assert platform_destination(settings, "psx") == tmp_path / "ROMs" / "psx"
