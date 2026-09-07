"""Queue size: archive members must not report the whole archive's size."""

from __future__ import annotations

import zipfile
from pathlib import Path

from aynthor.core.intake import queue_items_for
from aynthor.core.jobs import build_jobs
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.settings import FormatSettings


def test_archive_member_rows_carry_the_member_size_not_the_archive(tmp_path: Path):
    archive = tmp_path / "ps2" / "Game.zip"
    archive.parent.mkdir()
    payload = b"\0" * 4096
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Game.iso", payload)
    # Pad the zip so archive size != member size.
    archive.write_bytes(archive.read_bytes() + b"\0" * 50_000)

    items, reason = queue_items_for(archive, FormatSettings())
    assert reason is None
    assert len(items) == 1
    assert items[0].source_bytes == 4096
    assert items[0].source_bytes != archive.stat().st_size


def test_build_jobs_uses_source_bytes_for_archive_members(tmp_path: Path):
    archive = tmp_path / "game.zip"
    archive.write_bytes(b"archive-padding" * 200)
    item = QueueItem(
        path=archive,
        format=CompressionFormat.CHD,
        mode=ConversionMode.MOVE,
        output=tmp_path / "out" / "Game.chd" / "Game.iso",
        member="Game.iso",
        source_bytes=4096,
    )
    job = build_jobs([(0, item)], FormatSettings())[0][1]
    assert job.input_size == 4096
