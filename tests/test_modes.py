"""What Becomes should say for each action (Move / Unzip / Decompress)."""

from __future__ import annotations

from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.modes import becomes_label, reverse_mode, reverse_verb
from aynthor.core.unpack import is_archive


def test_move_label_is_move():
    assert becomes_label(CompressionFormat.NSZ, ConversionMode.MOVE) == "Move"
    assert becomes_label(CompressionFormat.CHD, ConversionMode.MOVE) == "Move"
    assert becomes_label(
        CompressionFormat.NSZ, ConversionMode.MOVE, intent="unzip") == "Move"


def test_seven_zip_reverse_is_unzip():
    assert reverse_verb(CompressionFormat.SEVEN_ZIP) == "Unzip"
    assert reverse_mode(CompressionFormat.SEVEN_ZIP) is ConversionMode.DECOMPRESS


def test_archive_member_has_no_separate_unzip_action():
    """RAR is already peeked into an NSP row — Move or convert, not Unzip."""
    from aynthor.core.modes import supports_reverse

    assert supports_reverse(CompressionFormat.NSZ, from_archive=True) is False
    assert reverse_mode(CompressionFormat.NSZ, from_archive=True) is ConversionMode.MOVE
    assert reverse_verb(CompressionFormat.CHD, from_archive=False) == "Decompress"
    assert reverse_mode(CompressionFormat.CHD, from_archive=False) is ConversionMode.DECOMPRESS


def test_source_is_archive_when_member_or_rar():
    from aynthor.core.modes import source_is_archive

    assert source_is_archive(Path("dump.rar"), "game.nsp")
    assert source_is_archive(Path("game.zip"), "")
    assert not source_is_archive(Path("game.nsp"), "")
    assert is_archive(Path("x.rar"))
