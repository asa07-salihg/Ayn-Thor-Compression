"""What would stop a batch, found before Start runs anything."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.preflight import ProblemKind, check_queue, missing_programs
from aynthor.core.settings import FormatSettings


def _row(path: str, fmt: CompressionFormat | None, *,
         mode: ConversionMode = ConversionMode.COMPRESS, output: str = "",
         platform: str = "psx", member: str = "", **options) -> QueueItem:
    source = Path(path)
    return QueueItem(
        path=source,
        format=fmt,
        mode=mode,
        output=Path(output) if output else source.with_suffix(".out"),
        tool_options=options,
        platform=platform,
        member=member,
    )


def _nothing_installed(_key: str) -> bool:
    return False


def _no_keys() -> Path | None:
    return None


def test_a_row_names_the_program_it_cannot_run_without():
    queue = [(1, _row("game.cue", CompressionFormat.CHD, output="game.chd")),
             (2, _row("game.iso", CompressionFormat.RVZ, platform="gc", output="game.rvz"))]
    missing = missing_programs(queue, lambda key: key == "DolphinTool")
    assert missing == {"chdman": [1]}


def test_moving_a_file_needs_no_program():
    queue = [(1, _row("game.chd", CompressionFormat.CHD, mode=ConversionMode.MOVE,
                      output="game.chd/game.chd"))]
    assert missing_programs(queue, _nothing_installed) == {}


def test_a_file_already_in_its_container_is_only_copied():
    """The runner places it instead of converting, so chdman is not needed."""
    queue = [(1, _row("snes/Game.7z", CompressionFormat.SEVEN_ZIP,
                      output="snes/Game.7z/Game.7z", platform="snes"))]
    assert missing_programs(queue, _nothing_installed) == {}


def test_taking_a_file_out_of_a_7z_needs_seven_zip_even_for_a_move():
    queue = [(1, _row("Game.7z", CompressionFormat.NSZ, mode=ConversionMode.MOVE,
                      member="Game.nsp", output="Game.nsp/Game.nsp", platform="switch"))]
    assert missing_programs(queue, _nothing_installed) == {"7z": [1]}


def test_either_3ds_engine_compresses_and_opening_needs_neither():
    compress = _row("game.cci", CompressionFormat.Z3DS, output="game.zcci", platform="n3ds")
    opening = _row("game.zcci", CompressionFormat.Z3DS, mode=ConversionMode.DECOMPRESS,
                   output="game.cci", platform="n3ds")
    assert missing_programs([(1, compress)], lambda key: key == "z3ds_compress") == {}
    assert missing_programs([(1, compress)], _nothing_installed) == {"rom-converto": [1]}
    assert missing_programs([(2, opening)], _nothing_installed) == {}


def test_rows_already_on_the_card_are_never_checked():
    on_card = _row("ROMs/switch/Game.nsp/Game.nsp", None, platform="switch", on_disk=True)
    assert check_queue([(1, on_card)], FormatSettings(), is_available=_nothing_installed,
                       find_keys=_no_keys) == []


def test_switch_rows_without_keys_are_flagged(tmp_path):
    compress = _row("game.nsp", CompressionFormat.NSZ, output="game.nsz", platform="switch")
    moved = _row("dlc.nsp", CompressionFormat.NSZ, mode=ConversionMode.MOVE,
                 output="Game.nsp/dlc.nsp", platform="switch")
    problems = check_queue([(1, compress), (2, moved)], FormatSettings(),
                           is_available=lambda _key: True, find_keys=_no_keys)
    assert [(p.kind, p.rows) for p in problems] == [(ProblemKind.NO_SWITCH_KEYS, (1,))]

    keys = tmp_path / "prod.keys"
    keys.write_text("x")
    assert check_queue([(1, compress)], FormatSettings(keys_path=str(keys)),
                       is_available=lambda _key: True, find_keys=_no_keys) == []
    assert check_queue([(1, compress)], FormatSettings(),
                       is_available=lambda _key: True, find_keys=lambda: keys) == []


def test_a_chosen_keys_file_that_is_gone_is_not_rescued_by_a_search(tmp_path):
    """The NSZ converter does not fall back to searching once a path is set,
    so the check must not promise that it will."""
    compress = _row("game.nsp", CompressionFormat.NSZ, output="game.nsz", platform="switch",
                    keys_path=str(tmp_path / "moved.keys"))
    found = tmp_path / "prod.keys"
    found.write_text("x")
    problems = check_queue([(1, compress)], FormatSettings(),
                           is_available=lambda _key: True, find_keys=lambda: found)
    assert [p.kind for p in problems] == [ProblemKind.NO_SWITCH_KEYS]


def test_an_unknown_console_only_matters_when_a_card_is_set(tmp_path):
    unknown = _row("mystery.iso", CompressionFormat.CHD, output="mystery.chd", platform="")
    known = _row("game.cue", CompressionFormat.CHD, output="game.chd", platform="psx")
    queue = [(1, unknown), (2, known)]

    assert check_queue(queue, FormatSettings(), is_available=lambda _key: True,
                       find_keys=_no_keys) == []
    problems = check_queue(queue, FormatSettings(esde_root=str(tmp_path)),
                           is_available=lambda _key: True, find_keys=_no_keys)
    assert [(p.kind, p.rows) for p in problems] == [(ProblemKind.UNKNOWN_PLATFORM, (1,))]
    assert problems[0].blocking is False


def test_problems_come_in_a_fixed_order_and_list_their_programs(tmp_path):
    queue = [
        (1, _row("game.nsp", CompressionFormat.NSZ, output="game.nsz", platform="switch")),
        (2, _row("mystery.iso", CompressionFormat.CHD, output="mystery.chd", platform="")),
    ]
    problems = check_queue(queue, FormatSettings(esde_root=str(tmp_path)),
                           is_available=_nothing_installed, find_keys=_no_keys)
    assert [p.kind for p in problems] == [
        ProblemKind.MISSING_TOOLS, ProblemKind.NO_SWITCH_KEYS, ProblemKind.UNKNOWN_PLATFORM]
    assert problems[0].tools == ("nsz", "chdman")
    assert problems[0].rows == (1, 2)
    assert problems[0].blocking and problems[1].blocking
