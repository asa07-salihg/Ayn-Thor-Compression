"""place_file: copy or in-place fold into a game folder."""

from __future__ import annotations

from pathlib import Path

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
