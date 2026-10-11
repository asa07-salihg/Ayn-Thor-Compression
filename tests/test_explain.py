"""A failed row, explained in words someone filling their first card can act on.

Every message here comes from the code that really produces it: a converter
run against an empty tools folder, `place_file` hitting a full disk, an
archive that does not hold the file. Matching on hand-written copies of those
strings would keep passing after the real wording changed.
"""

from __future__ import annotations

import errno
import os
import zipfile
from pathlib import Path

import pytest

from aynthor.core.explain import Fix, explain_failure
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode


def _job(tmp_path: Path, name: str, fmt: CompressionFormat,
         mode: ConversionMode = ConversionMode.COMPRESS, **options) -> ConversionJob:
    source = tmp_path / name
    source.write_bytes(b"\0" * 64)
    return ConversionJob(
        input_path=source,
        output_path=tmp_path / "out" / f"{source.stem}.out",
        format=fmt,
        options={"mode": mode.value, **options},
    )


@pytest.mark.parametrize(
    ("module", "cls", "name", "fmt", "options"),
    [
        ("chd", "ChdmanConverter", "game.iso", CompressionFormat.CHD, {}),
        ("cso", "MaxcsoConverter", "game.iso", CompressionFormat.CSO, {}),
        ("rvz", "DolphinConverter", "game.iso", CompressionFormat.RVZ, {}),
        ("archive", "SevenZipConverter", "game.sfc", CompressionFormat.SEVEN_ZIP, {}),
        ("nds", "NdsTrimConverter", "game.nds", CompressionFormat.NDS_TRIM, {}),
        ("wua", "WuaConverter", "game.wua", CompressionFormat.WUA, {}),
        # A blank file reads as an unknown cart; skip the encryption check
        # so the run gets as far as looking for its program.
        ("z3ds", "Z3dsConverter", "game.cci", CompressionFormat.Z3DS,
         {"allow_encrypted": True}),
    ],
)
def test_a_missing_program_points_at_the_tools_window(
        tmp_path, monkeypatch, module, cls, name, fmt, options):
    import importlib

    converter_module = importlib.import_module(f"aynthor.core.converters.{module}")
    empty = tmp_path / "tools"
    empty.mkdir()
    monkeypatch.setattr(converter_module, "tool_path", lambda tool: empty / f"{tool}.exe")

    ok, message = getattr(converter_module, cls)().convert(
        _job(tmp_path, name, fmt, **options))

    assert ok is False
    explained = explain_failure(message)
    assert explained.fix is Fix.OPEN_TOOLS, message
    assert "isn't installed" in explained.summary
    assert explained.details == message


def test_the_missing_program_is_named(tmp_path, monkeypatch):
    from aynthor.core.converters import chd

    monkeypatch.setattr(chd, "tool_path", lambda tool: tmp_path / f"{tool}.exe")
    _ok, message = chd.ChdmanConverter().convert(
        _job(tmp_path, "game.iso", CompressionFormat.CHD))

    assert explain_failure(message).summary.startswith("chdman ")


def test_missing_switch_keys_offers_to_choose_them(tmp_path, monkeypatch):
    from aynthor.core.converters import nsz

    monkeypatch.setattr(nsz, "find_prod_keys", lambda: None)
    job = _job(tmp_path, "game.nsp", CompressionFormat.NSZ,
               keys_path=str(tmp_path / "nowhere.keys"))
    ok, message = nsz.NszConverter().convert(job)

    assert ok is False
    explained = explain_failure(message)
    assert explained.fix is Fix.CHOOSE_KEYS
    assert "prod.keys" in explained.summary


def test_a_full_card_says_there_is_no_room(tmp_path, monkeypatch):
    from aynthor.core.converters import base

    def full(*_args, **_kwargs):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(base, "_copy_with_progress", full)
    job = _job(tmp_path, "game.chd", CompressionFormat.CHD, ConversionMode.MOVE)
    ok, message = base.place_file(job)

    assert ok is False
    explained = explain_failure(message)
    assert "space" in explained.summary
    assert explained.fix is Fix.OPEN_FOLDER


def test_the_windows_wording_of_a_full_disk_is_recognised_too():
    explained = explain_failure(
        "Could not copy into its folder: [WinError 112] There is not enough space on the disk")
    assert "space" in explained.summary


@pytest.mark.parametrize(
    "message",
    [
        "Could not copy into its folder: [WinError 19] The media is write protected",
        "Could not copy into its folder: [Errno 13] Permission denied: 'E:\\\\psx'",
        "Could not copy into its folder: [WinError 5] Access is denied",
    ],
)
def test_a_locked_card_mentions_the_lock_switch(message):
    explained = explain_failure(message)
    assert "wouldn't let" in explained.summary
    assert "lock switch" in explained.advice


def test_a_file_held_open_says_to_close_the_program():
    explained = explain_failure(
        "Could not copy into its folder: [WinError 32] The process cannot access the "
        "file because it is being used by another process")
    assert "open" in explained.summary


def test_a_rar_without_seven_zip_points_at_seven_zip():
    from aynthor.core import unpack

    try:
        unpack._rar_tool()
    except unpack.UnpackError as exc:
        message = str(exc)
    else:
        pytest.skip("7-Zip is installed on this machine")
    assert explain_failure(message).fix is Fix.GET_7ZIP


def test_an_archive_without_the_file_says_download_again(tmp_path):
    from aynthor.core.unpack import UnpackError, extract_member_to

    archive = tmp_path / "game.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("other.nsp", b"x")
    with pytest.raises(UnpackError) as caught:
        extract_member_to(archive, "game.nsp", tmp_path / "out" / "game.nsp")

    explained = explain_failure(str(caught.value))
    assert "archive" in explained.summary.casefold()
    assert "download" in explained.advice.casefold()


def test_asking_for_something_a_format_cannot_do_points_at_becomes(tmp_path):
    from aynthor.core.converters.wua import WuaConverter

    _ok, message = WuaConverter().convert(
        _job(tmp_path, "game.wua", CompressionFormat.WUA, ConversionMode.DECOMPRESS))

    assert "Becomes" in explain_failure(message).advice


def test_a_source_that_vanished_says_add_it_again(tmp_path):
    from aynthor.core.converters.chd import ChdmanConverter

    job = _job(tmp_path, "game.iso", CompressionFormat.CHD)
    job.input_path.unlink()
    _ok, message = ChdmanConverter().convert(job)

    explained = explain_failure(message)
    assert "isn't there" in explained.summary
    assert "add" in explained.advice.casefold()


def test_anything_else_keeps_the_tools_own_words():
    message = "Error: file is not a valid CD image"
    explained = explain_failure(message)
    assert explained.fix is Fix.NONE
    assert explained.details == message
    assert "stopped" in explained.summary


def test_no_explanation_uses_a_dash_for_punctuation():
    """The wording is read by people, and a long dash reads as boilerplate."""
    from aynthor.core import explain

    for text in explain.all_wording():
        assert "\u2014" not in text and "\u2013" not in text, text
