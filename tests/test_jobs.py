"""Turning queue rows into jobs, and the conflict policy that drops some."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.jobs import build_jobs, job_options, resolve_output_path
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.settings import FormatSettings


def row(path: Path, output: Path, *, fmt=CompressionFormat.CHD,
        mode=ConversionMode.COMPRESS, options=None) -> tuple[int, QueueItem]:
    return (0, QueueItem(path=path, format=fmt, mode=mode, output=output,
                         tool_options=options or {}))


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    path = tmp_path / "game.cue"
    path.write_bytes(b"\0" * 2048)
    return path


def test_skip_is_the_default_so_a_rerun_does_nothing(source, tmp_path):
    existing = tmp_path / "game.chd"
    existing.write_bytes(b"done")
    assert build_jobs([row(source, existing)], FormatSettings(on_conflict="skip")) == []


def test_overwrite_keeps_the_same_path(source, tmp_path):
    existing = tmp_path / "game.chd"
    existing.write_bytes(b"done")
    jobs = build_jobs([row(source, existing)], FormatSettings(on_conflict="overwrite"))
    assert jobs[0][1].output_path == existing


def test_rename_finds_the_first_free_name(tmp_path):
    (tmp_path / "game.chd").write_bytes(b"a")
    (tmp_path / "game_1.chd").write_bytes(b"b")
    assert resolve_output_path(tmp_path / "game.chd", "rename").name == "game_2.chd"


def test_no_conflict_returns_the_path_unchanged(tmp_path):
    target = tmp_path / "fresh.chd"
    assert resolve_output_path(target, "skip") == target


def test_input_size_is_recorded_so_savings_can_be_shown(source, tmp_path):
    job = build_jobs([row(source, tmp_path / "out.chd")], FormatSettings())[0][1]
    assert job.input_size == 2048


def test_a_row_without_a_format_is_dropped(source, tmp_path):
    assert build_jobs([row(source, tmp_path / "out", fmt=None)], FormatSettings()) == []


def test_row_options_beat_the_format_defaults(source, tmp_path):
    """A row's options came from a platform preset or an imported list, both of
    which know more than a format-wide default does."""
    settings = FormatSettings(options={
        CompressionFormat.CHD: {"hunk_size": 0, "codecs": ["zstd"]},
    })
    jobs = build_jobs(
        [row(source, tmp_path / "out.chd", options={"hunk_size": 2048, "codecs": ["zlib"]})],
        settings)
    assert jobs[0][1].options["hunk_size"] == 2048
    assert jobs[0][1].options["codecs"] == ["zlib"]


def test_format_defaults_are_used_when_the_row_says_nothing(source, tmp_path):
    settings = FormatSettings(options={CompressionFormat.CHD: {"hunk_size": 4096}})
    jobs = build_jobs([row(source, tmp_path / "out.chd")], settings)
    assert jobs[0][1].options["hunk_size"] == 4096


def test_each_format_gets_only_its_own_options(source, tmp_path):
    settings = FormatSettings(options={
        CompressionFormat.CHD: {"hunk_size": 4096},
        CompressionFormat.RVZ: {"level": 9},
    })
    jobs = build_jobs([row(source, tmp_path / "out.chd")], settings)
    assert "level" not in jobs[0][1].options


def test_the_row_carries_its_own_direction(source, tmp_path):
    """A queue can hold a decrypt and a compress at the same time."""
    jobs = build_jobs(
        [row(source, tmp_path / "out.cue", mode=ConversionMode.DECOMPRESS)],
        FormatSettings())
    assert jobs[0][1].options["mode"] == ConversionMode.DECOMPRESS.value


def test_keys_path_reaches_the_nsz_converter(source, tmp_path):
    settings = FormatSettings(keys_path="C:/keys/prod.keys")
    item = QueueItem(source, CompressionFormat.NSZ, ConversionMode.COMPRESS,
                     tmp_path / "out.nsz")
    assert job_options(settings, item)["keys_path"] == "C:/keys/prod.keys"


def test_a_keys_path_set_in_the_panel_is_not_overwritten(source, tmp_path):
    settings = FormatSettings(
        keys_path="C:/global/prod.keys",
        options={CompressionFormat.NSZ: {"keys_path": "C:/panel/prod.keys"}})
    item = QueueItem(source, CompressionFormat.NSZ, ConversionMode.COMPRESS,
                     tmp_path / "out.nsz")
    assert job_options(settings, item)["keys_path"] == "C:/panel/prod.keys"


def test_keys_path_is_not_pushed_at_other_formats(source, tmp_path):
    settings = FormatSettings(keys_path="C:/keys/prod.keys")
    item = QueueItem(source, CompressionFormat.CHD, ConversionMode.COMPRESS,
                     tmp_path / "out.chd")
    assert "keys_path" not in job_options(settings, item)


def test_delete_source_reaches_the_runner(source, tmp_path):
    settings = FormatSettings(delete_source=True)
    jobs = build_jobs([row(source, tmp_path / "out.chd")], settings)
    assert jobs[0][1].options["delete_source"] is True


def test_rows_keep_their_table_index(source, tmp_path):
    rows = [(3, QueueItem(source, CompressionFormat.CHD, ConversionMode.COMPRESS,
                          tmp_path / "out.chd"))]
    assert build_jobs(rows, FormatSettings())[0][0] == 3
