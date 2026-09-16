"""place_file: copy or in-place fold into a game folder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aynthor.core.converters.base import place_file
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode


def _job(src: Path, dst: Path) -> ConversionJob:
    return ConversionJob(
        input_path=src,
        output_path=dst,
        format=CompressionFormat.CHD,
        options={"mode": ConversionMode.MOVE.value},
    )


def test_place_file_folds_a_loose_rom_into_a_same_named_folder(tmp_path: Path):
    """Windows cannot mkdir Game.chd while Game.chd is still a file."""
    platform = tmp_path / "snes"
    platform.mkdir()
    rom = platform / "Front Mission.chd"
    rom.write_bytes(b"chd-bytes")
    out = platform / "Front Mission.chd" / "Front Mission.chd"

    ok, message = place_file(_job(rom, out))

    assert ok, message
    assert out.is_file()
    assert out.read_bytes() == b"chd-bytes"
    assert not rom.is_file()
    assert (platform / "Front Mission.chd").is_dir()


def test_place_file_copies_when_source_is_elsewhere(tmp_path: Path):
    src = tmp_path / "Downloads" / "Game.chd"
    src.parent.mkdir()
    src.write_bytes(b"x")
    out = tmp_path / "snes" / "Game.chd" / "Game.chd"

    ok, message = place_file(_job(src, out))

    assert ok, message
    assert out.read_bytes() == b"x"
    assert src.is_file()


def test_place_file_reports_copy_progress(tmp_path: Path):
    src = tmp_path / "big.bin"
    src.write_bytes(b"\0" * (3 * 1024 * 1024))
    out = tmp_path / "Game.chd" / "Game.chd"
    seen: list[int] = []

    ok, message = place_file(_job(src, out), on_progress=seen.append)

    assert ok, message
    assert out.stat().st_size == src.stat().st_size
    assert seen, "copy must report progress so a large Move does not sit on 99%"
    assert seen[-1] == 100
    assert all(0 <= p <= 100 for p in seen)


def test_a_copied_file_is_stamped_with_now_not_with_the_sources_time(tmp_path: Path):
    """`copystat` carried the source's mtime onto the new file. The runner
    proves an output belongs to this run by its mtime before it will delete a
    source, so with an old source delete-source silently never fired and the
    log said the output "was already there and this run did not write it"."""
    import os
    import time

    src = tmp_path / "Downloads" / "Game.chd"
    src.parent.mkdir()
    src.write_bytes(b"x" * 1024)
    week_ago = time.time() - 7 * 24 * 3600
    os.utime(src, (week_ago, week_ago))
    out = tmp_path / "snes" / "Game.chd" / "Game.chd"

    started = time.time()
    ok, message = place_file(_job(src, out))

    assert ok, message
    assert out.stat().st_mtime >= started - 2


@pytest.mark.skipif(sys.platform == "win32",
                    reason="RLIMIT_FSIZE is the only way to fill a disk on demand, "
                           "and it is POSIX only. The code under test is not.")
def test_a_copy_that_runs_out_of_room_leaves_nothing_behind(tmp_path: Path):
    """Writing straight to the destination left a truncated ROM there, and the
    default conflict policy is Skip, so the next run dropped that row and
    never mentioned the half-written file again."""
    import resource

    src = tmp_path / "big.bin"
    src.write_bytes(b"\0" * (12 * 1024 * 1024))
    out = tmp_path / "Game.chd" / "Game.chd"

    soft, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, hard))
    try:
        ok, message = place_file(_job(src, out))
    finally:
        resource.setrlimit(resource.RLIMIT_FSIZE, (soft, hard))

    assert not ok
    assert "copy" in message.lower()
    assert not out.exists()
    assert not list(out.parent.glob("*.aynthor-part"))
