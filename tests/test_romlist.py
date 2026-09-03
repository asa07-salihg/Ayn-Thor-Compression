"""Parsing a list file and matching its entries to files on a card."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.romlist import (
    entries_to_queue,
    find_rom_files,
    parse_list_file,
    summarize_list,
)

LIST_TEXT = """\
==============================================================
Emulator -> ES-DE folder
Rule: this decorative line must be ignored
==============================================================

Chrono Cross -> psx -> CHD
Persona 4 -> ps2 -> CHD
Metroid Prime -> gc -> RVZ
Super Mario World -> snes -> 7Z
Mario Kart 8 Deluxe -> switch -> NSZ
Super Mario 64 -> n64 -> Z64
Some PC Game -> windows -> -
this line has no arrows and should be skipped
"""


@pytest.fixture()
def list_file(tmp_path: Path) -> Path:
    path = tmp_path / "ayn-thor.txt"
    path.write_text(LIST_TEXT, encoding="utf-8")
    return path


TABLE_TEXT = """\
# Ayn Thor

| Game                | Folder | Format | Done |
| ------------------- | ------ | ------ | ---- |
| Chrono Cross        | psx    | CHD    | yes  |
| Persona 4           | ps2    | CHD    |      |
| Metroid Prime       | gc     | RVZ    |      |

NOTE: this sentence sits in the middle and must be ignored.
| A note in a table   | this cell is a sentence | x |
"""


@pytest.fixture()
def table_file(tmp_path: Path) -> Path:
    path = tmp_path / "ayn-thor-table.md"
    path.write_text(TABLE_TEXT, encoding="utf-8")
    return path


def test_a_markdown_table_is_read_too(table_file):
    """A list pasted into a document to tick titles off is the common shape.

    Reading only the arrow form meant such a file imported nothing at all, with
    no error to explain why.
    """
    entries = parse_list_file(table_file)
    assert [e.game for e in entries] == ["Chrono Cross", "Persona 4", "Metroid Prime"]


def test_the_table_header_and_separator_are_not_entries(table_file):
    games = {e.game.lower() for e in parse_list_file(table_file)}
    assert "game" not in games
    assert not any(set(g) <= set("- :") for g in games)


def test_a_prose_row_is_rejected(table_file):
    """The platform column holds one token; a sentence there is not an entry."""
    assert all(len(e.platform.split()) == 1 for e in parse_list_file(table_file))


def test_the_shipped_sample_parses():
    sample = Path(__file__).resolve().parents[1] / "examples" / "sample-list.txt"
    entries = parse_list_file(sample)
    assert len(entries) >= 20
    # It documents both shapes, so both must survive.
    assert any(e.game == "Chrono Cross" for e in entries)      # arrow form
    assert any(e.game == "Silent Hill 2" for e in entries)     # table form


def test_parses_only_the_game_lines(list_file):
    entries = parse_list_file(list_file)
    assert [e.game for e in entries] == [
        "Chrono Cross", "Persona 4", "Metroid Prime", "Super Mario World",
        "Mario Kart 8 Deluxe", "Super Mario 64", "Some PC Game",
    ]


def test_platform_is_lowercased_and_format_uppercased(list_file):
    entry = parse_list_file(list_file)[0]
    assert entry.platform == "psx"
    assert entry.target_format == "CHD"


def test_line_numbers_are_kept_for_error_reporting(list_file):
    entries = parse_list_file(list_file)
    assert entries[0].line_no == 6


def test_summarize_counts_by_format(list_file):
    summary = summarize_list(parse_list_file(list_file))
    assert summary["CHD"] == 2
    assert summary["Z64"] == 1


def test_an_empty_file_parses_to_nothing(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    assert parse_list_file(path) == []


def test_matches_a_game_despite_region_tags(roms_root):
    found = find_rom_files(roms_root, "psx", "Chrono Cross")
    assert found and found[0].name.startswith("Chrono Cross")


def test_two_keywords_are_required_so_near_misses_do_not_match(roms_root):
    """"Mario Kart" must not match "Super Mario World"."""
    assert find_rom_files(roms_root, "snes", "Mario Kart") == []


def test_a_switch_entry_returns_the_whole_set(roms_root):
    found = find_rom_files(roms_root, "switch", "Mario Kart 8 Deluxe")
    assert len(found) == 3


def test_switch_set_is_ordered_base_first(roms_root):
    from aynthor.core.switch import ContentType, detect_content_type

    found = find_rom_files(roms_root, "switch", "Mario Kart 8 Deluxe")
    assert detect_content_type(found[0]) is ContentType.BASE


def test_skipped_platforms_never_reach_the_queue(list_file, roms_root):
    platforms = {e.platform for e in entries_to_queue(parse_list_file(list_file), roms_root)}
    assert "windows" not in platforms
    assert "n64" not in platforms


def test_queue_entries_carry_the_platform_preset(list_file, roms_root):
    queued = entries_to_queue(parse_list_file(list_file), roms_root)
    ps2 = next(e for e in queued if e.platform == "ps2")
    assert ps2.options["hunk_size"] == 2048
    assert ps2.format.value == "chd"


def test_queue_entries_carry_the_game_name_for_grouping(list_file, roms_root):
    queued = entries_to_queue(parse_list_file(list_file), roms_root)
    assert all(e.options.get("game_group") for e in queued)


def test_an_edited_preset_reaches_an_imported_list(list_file, roms_root):
    """The list says which platform; the preset says what that platform becomes."""
    from aynthor.core.presets import PresetTable

    table = PresetTable()
    table.set_options("ps2", {"hunk_size": 8192})
    queued = entries_to_queue(parse_list_file(list_file), roms_root, table)
    ps2 = next(e for e in queued if e.platform == "ps2")
    assert ps2.options["hunk_size"] == 8192


# --------------------------------------------------------------- performance

def test_each_platform_folder_is_walked_once_per_import(list_file, roms_root, monkeypatch):
    """Matching used to re-walk the whole folder for every line of the list.

    A real list is over a thousand entries and a real card is tens of thousands
    of files, so that meant a thousand full walks over an SD card.
    """
    from aynthor.core import romlist

    walks: list[str] = []
    original = romlist.search_dirs

    def counting(roms_root, platform):
        walks.append(platform)
        return original(roms_root, platform)

    monkeypatch.setattr(romlist, "search_dirs", counting)
    entries = parse_list_file(list_file)
    entries_to_queue(entries, roms_root)

    # Switch is looked up twice by design: once to index it, once to find the
    # folder a matched title lives in. Nothing else may repeat.
    non_switch = [p for p in walks if p != "switch"]
    assert len(non_switch) == len(set(non_switch)), walks


def test_the_index_returns_the_same_files_on_a_second_ask(roms_root):
    from aynthor.core.romlist import RomIndex

    index = RomIndex(roms_root)
    first = index.files("psx")
    assert first == index.files("psx")
    assert first, "the fixture card has PS1 files"


def test_the_index_lowercases_names_once_for_scoring(roms_root):
    from aynthor.core.romlist import RomIndex

    for path, lowered in RomIndex(roms_root).files("psx"):
        assert lowered == path.stem.lower()


def test_an_index_can_be_shared_across_calls(roms_root):
    """Passing one in is what entries_to_queue does; it must not change results."""
    from aynthor.core.romlist import RomIndex

    index = RomIndex(roms_root)
    with_index = find_rom_files(roms_root, "psx", "Chrono Cross", index)
    without = find_rom_files(roms_root, "psx", "Chrono Cross")
    assert with_index == without

