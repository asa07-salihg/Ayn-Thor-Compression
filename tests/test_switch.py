"""Telling Switch base games, updates and DLC apart."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.switch import (
    ContentType,
    content_warnings,
    detect_content_type,
    group_switch_files,
    is_switch_rom,
    normalize_game_name,
    sort_switch_files,
    summarize_group,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # A title id is definitive: the last three hex digits carry the type.
        ("Game [0100152000022000][v0].nsp", ContentType.BASE),
        ("Game [0100152000022800][v65536].nsp", ContentType.UPDATE),
        ("Game [0100152000022001][v0].nsp", ContentType.DLC),
        # Failing that, the markers dumpers actually use.
        ("Game [UPD].nsp", ContentType.UPDATE),
        ("Game (update).nsp", ContentType.UPDATE),
        ("Game [DLC] Expansion.nsp", ContentType.DLC),
        ("Game [AOC].nsp", ContentType.DLC),
        ("Game v1.2.0.nsp", ContentType.UPDATE),
        # An untagged dump is almost always a base game.
        ("Game.nsp", ContentType.BASE),
    ],
)
def test_detect_content_type(name, expected):
    assert detect_content_type(Path(name)) is expected


def test_markers_beat_the_title_id_only_when_the_id_is_absent():
    tagged = Path("Game [DLC] [0100152000022000][v0].nsp")
    assert detect_content_type(tagged) is ContentType.DLC


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Mario Kart 8 Deluxe [0100152000022000][v0].nsp", "Mario Kart 8 Deluxe"),
        ("Mario Kart 8 Deluxe [0100152000022800][v65536].nsp", "Mario Kart 8 Deluxe"),
        ("Mario_Kart_8_Deluxe.nsp", "Mario Kart 8 Deluxe"),
        ("Game [DLC] Pack 2.nsp", "Game"),
    ],
)
def test_normalize_game_name(name, expected):
    assert normalize_game_name(Path(name)) == expected


def test_normalize_never_returns_an_empty_name():
    assert normalize_game_name(Path("[DLC].nsp")) != ""


@pytest.mark.parametrize(
    ("name", "expected"),
    [("game.nsp", True), ("game.xci", True), ("game.nsz", True),
     ("game.xcz", True), ("game.iso", False)],
)
def test_is_switch_rom(name, expected):
    assert is_switch_rom(Path(name)) is expected


def test_sort_puts_base_first():
    files = [Path("G [0100000000000800][v1].nsp"),
             Path("G [0100000000000001][v0].nsp"),
             Path("G [0100000000000000][v0].nsp")]
    ordered = [detect_content_type(p) for p in sort_switch_files(files)]
    assert ordered == [ContentType.BASE, ContentType.UPDATE, ContentType.DLC]


def test_a_base_and_its_update_normalise_to_the_same_name():
    """The version token has to go, or a set never groups.

    Every base game carries v0 and its update a large version number, so
    leaving the token in produced two different names for one title.
    """
    base = normalize_game_name(Path("Zelda TOTK [01007EF00011E000][v0].nsp"))
    update = normalize_game_name(Path("Zelda TOTK [01007EF00011E800][v65536].nsp"))
    assert base == update


def test_group_switch_files_keeps_a_title_together():
    files = [Path("Mario Kart 8 [0100152000022000][v0].nsp"),
             Path("Mario Kart 8 [0100152000022800][v65536].nsp"),
             Path("Zelda [01007EF00011E000][v0].nsp")]
    groups = group_switch_files(files)
    assert len(groups) == 2
    assert max(len(v) for v in groups.values()) == 2


def test_group_ignores_non_switch_files():
    assert group_switch_files([Path("game.iso")]) == {}


def test_update_without_a_base_is_flagged():
    """Installing an update with no base game does nothing, so say so."""
    assert content_warnings([ContentType.UPDATE]) == ["Update without Base"]


def test_dlc_without_a_base_is_flagged():
    assert content_warnings([ContentType.DLC]) == ["DLC without Base"]


def test_a_complete_set_is_not_flagged():
    assert content_warnings([ContentType.BASE, ContentType.UPDATE, ContentType.DLC]) == []


def test_summarize_group_reads_as_a_sentence():
    summary = summarize_group([ContentType.BASE, ContentType.DLC, ContentType.DLC])
    assert summary == "Base + 2 DLC"
