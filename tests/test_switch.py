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
        ("Ys VIII Lacrimosa of DANA Elixir Set 1.nsp", ContentType.DLC),
        ("Game ARCUS Cover Set A.nsp", ContentType.DLC),
        ("Ys X Nordics 1.0.3.nsp", ContentType.UPDATE),
        # Underscores: scene RARs use pack_dlc, and _ is a word char so \bdlc\b misses.
        ("v-ys_x_nordics_ys_x_advanced_pack_dlc.nsp", ContentType.DLC),
        ("v-ys_x_nordics_ys_x_costume_pack_dlc.nsp", ContentType.DLC),
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
        ("Ys VIII Lacrimosa of DANA [01007F200B0C0000][v0].nsp",
         "Ys VIII Lacrimosa of DANA"),
        ("Ys VIII Lacrimosa of DANA Elixir Set 1 [01007F200B0C0001][v0].nsp",
         "Ys VIII Lacrimosa of DANA"),
        ("Ys VIII Lacrimosa of DANA Free Set 2 [01007F200B0C0002][v0].nsp",
         "Ys VIII Lacrimosa of DANA"),
        ("Ys VIII Lacrimosa of DANA Tempest Set 3 [01007F200B0C0003][v0].nsp",
         "Ys VIII Lacrimosa of DANA"),
        ("Ys X Nordics 1.0.3.nsp", "Ys X Nordics"),
        ("Ys X Nordics.xci", "Ys X Nordics"),
        # Lettered cover packs, and dumpers that repeat the title in the DLC name.
        ("The Legend of Heroes Trails of Cold Steel III Trails of Cold Steel III "
         "ARCUS Cover Set A.nsp",
         "The Legend of Heroes Trails of Cold Steel III"),
        ("The Legend of Heroes Trails of Cold Steel III.nsp",
         "The Legend of Heroes Trails of Cold Steel III"),
        # Scene-style lowercase DLC: leading v, repeated short title, "… pack dlc".
        ("v ys x nordics ys x advanced pack dlc.nsz", "ys x nordics"),
        ("v ys x nordics ys x costume pack dlc.nsz", "ys x nordics"),
        ("v ys x nordics ys x freebie set a dlc.nsz", "ys x nordics"),
        ("v-ys_x_nordics_ys_x_advanced_pack_dlc.nsp", "ys x nordics"),
        ("Ys X Nordics.nsp", "Ys X Nordics"),
        # Cut at Costume; shared-prefix matching joins the short base name.
        ("Ys IX Monstrum Nox Crimson King's Ecliptic Errant Costume.nsz",
         "Ys IX Monstrum Nox Crimson King's Ecliptic Errant"),
        ("Ys IX Monstrum Nox.nsp", "Ys IX Monstrum Nox"),
    ],
)
def test_normalize_game_name(name, expected):
    assert normalize_game_name(Path(name)) == expected


def test_costume_dlc_shares_the_base_title():
    from aynthor.core.switch import titles_share_game

    dlc = normalize_game_name(Path(
        "Ys IX Monstrum Nox Crimson King's Ecliptic Errant Costume.nsz"))
    base = normalize_game_name(Path("Ys IX Monstrum Nox.nsp"))
    assert titles_share_game(dlc, base)


def test_any_name_starting_with_the_base_joins_it():
    """The rule: base header owns every longer name that starts with it."""
    from aynthor.core.switch import titles_share_game

    base = "Ys X Nordics"
    assert titles_share_game(base, "Ys X Nordics ys x advanced pack dlc")
    assert titles_share_game(
        base, "Ys IX Monstrum Nox Crimson King's Ecliptic Errant Costume") is False
    assert titles_share_game(
        "Ys IX Monstrum Nox",
        "Ys IX Monstrum Nox Crimson King's Ecliptic Errant Costume",
    )


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


def test_title_family_keeps_base_update_and_dlc_together():
    """The last three hex digits are the content type; the rest is the title."""
    from aynthor.core.switch import title_family

    base = Path("Ys [01007F200B0C0000][v0].nsp")
    update = Path("Ys [01007F200B0C0800][v1].nsp")
    dlc = Path("Ys Elixir Set 1 [01007F200B0C0001][v0].nsp")
    other = Path("Other [0100AAAAAAAAA000][v0].nsp")
    assert title_family(base) == title_family(update) == title_family(dlc)
    assert title_family(base) != title_family(other)


def test_group_switch_files_keeps_a_title_together():
    files = [Path("Mario Kart 8 [0100152000022000][v0].nsp"),
             Path("Mario Kart 8 [0100152000022800][v65536].nsp"),
             Path("Zelda [01007EF00011E000][v0].nsp")]
    groups = group_switch_files(files)
    assert len(groups) == 2
    assert max(len(v) for v in groups.values()) == 2


def test_dlc_sets_are_the_same_game_as_the_base():
    files = [
        Path("Ys VIII Lacrimosa of DANA [01007F200B0C0000][v0].nsp"),
        Path("Ys VIII Lacrimosa of DANA [01007F200B0C0800][v327680].nsp"),
        Path("Ys VIII Lacrimosa of DANA Elixir Set 1 [01007F200B0C0001][v0].nsp"),
        Path("Ys VIII Lacrimosa of DANA Tempest Set 3 [01007F200B0C0003][v0].nsp"),
    ]
    groups = group_switch_files(files)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 4
    assert "Ys VIII Lacrimosa of DANA" in groups


def test_cover_set_dlc_without_title_id_joins_the_base_by_name():
    """No title id in the name, but the DLC still starts with the base title."""
    files = [
        Path("The Legend of Heroes Trails of Cold Steel III.nsp"),
        Path("The Legend of Heroes Trails of Cold Steel III Update.nsp"),
        Path("The Legend of Heroes Trails of Cold Steel III Trails of Cold Steel III "
             "ARCUS Cover Set A.nsp"),
        Path("The Legend of Heroes Trails of Cold Steel III Trails of Cold Steel III "
             "ARCUS Cover Set B.nsp"),
    ]
    groups = group_switch_files(files)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 4
    assert list(groups) == ["The Legend of Heroes Trails of Cold Steel III"]


def test_scene_pack_dlc_names_share_one_title():
    """`v game game pack-name pack dlc` must not be twelve separate trees."""
    from aynthor.core.switch import titles_share_game

    files = [
        Path("Ys X Nordics.nsp"),
        Path("v ys x nordics ys x advanced pack dlc.nsz"),
        Path("v ys x nordics ys x attachment pack dlc.nsz"),
        Path("v ys x nordics ys x costume pack dlc.nsz"),
        Path("v ys x nordics ys x freebie set a dlc.nsz"),
    ]
    groups = group_switch_files(files)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 5
    assert titles_share_game("ys x nordics", "Ys X Nordics")


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
