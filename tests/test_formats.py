"""The format catalogue and output naming."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.formats import (
    FORMAT_CATALOG,
    detect_format,
    format_info,
    known_extensions,
    suggest_output_path,
)
from aynthor.core.models import CompressionFormat, ConversionMode


def test_every_format_except_unknown_is_in_the_catalogue():
    catalogued = {info.format for info in FORMAT_CATALOG}
    expected = set(CompressionFormat) - {CompressionFormat.UNKNOWN}
    assert catalogued == expected


def test_no_format_appears_twice():
    formats = [info.format for info in FORMAT_CATALOG]
    assert len(formats) == len(set(formats))


def test_every_entry_explains_itself():
    """`reason` is what the options panel shows; an empty one is a bug."""
    for info in FORMAT_CATALOG:
        assert info.reason, f"{info.label} has no reason"
        assert info.extensions, f"{info.label} claims no extensions"


def test_decrypt_3ds_is_last_so_auto_detect_prefers_compression():
    # A .cia is far more often headed for compression than for decryption, and
    # detect_format returns the first entry that claims the extension.
    assert FORMAT_CATALOG[-1].format == CompressionFormat.DEC_3DS
    assert detect_format(Path("game.cia")).format == CompressionFormat.Z3DS


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("game.cue", CompressionFormat.CHD),
        ("game.gdi", CompressionFormat.CHD),
        ("game.wbfs", CompressionFormat.RVZ),
        ("game.nds", CompressionFormat.NDS_TRIM),
        ("game.nsp", CompressionFormat.NSZ),
        ("game.sfc", CompressionFormat.SEVEN_ZIP),
        ("game.wud", CompressionFormat.WUA),
        ("game.zcci", CompressionFormat.Z3DS),
    ],
)
def test_detect_format_by_extension(name, expected):
    assert detect_format(Path(name)).format is expected


def test_detect_format_is_case_insensitive():
    assert detect_format(Path("GAME.CUE")).format is CompressionFormat.CHD


def test_unknown_extension_detects_nothing():
    assert detect_format(Path("notes.txt")) is None


def test_known_extensions_covers_the_catalogue():
    extensions = known_extensions()
    assert ".chd" in extensions and ".nsz" in extensions
    assert all(ext.startswith(".") for ext in extensions)


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("game.cue", CompressionFormat.CHD, "game.chd"),
        ("game.iso", CompressionFormat.RVZ, "game.rvz"),
        ("game.iso", CompressionFormat.CSO, "game.cso"),
        ("game.sfc", CompressionFormat.SEVEN_ZIP, "game.7z"),
        ("game.wud", CompressionFormat.WUA, "game.wua"),
        # Z3DS keeps the original container's identity in the extension.
        ("game.cci", CompressionFormat.Z3DS, "game.zcci"),
        ("game.3ds", CompressionFormat.Z3DS, "game.zcci"),
        ("game.cia", CompressionFormat.Z3DS, "game.zcia"),
        ("game.cxi", CompressionFormat.Z3DS, "game.zcxi"),
        ("game.3dsx", CompressionFormat.Z3DS, "game.z3dsx"),
        ("game.nsp", CompressionFormat.NSZ, "game.nsz"),
        ("game.xci", CompressionFormat.NSZ, "game.xcz"),
    ],
)
def test_compress_output_names(source, target, expected):
    assert suggest_output_path(Path(source), target).name == expected


@pytest.mark.parametrize(
    ("source", "target", "expected"),
    [
        ("game.chd", CompressionFormat.CHD, "game.cue"),
        ("game.rvz", CompressionFormat.RVZ, "game.iso"),
        ("game.cso", CompressionFormat.CSO, "game.iso"),
        ("game.zcci", CompressionFormat.Z3DS, "game.cci"),
        ("game.zcia", CompressionFormat.Z3DS, "game.cia"),
        ("game.nsz", CompressionFormat.NSZ, "game.nsp"),
        ("game.xcz", CompressionFormat.NSZ, "game.xci"),
    ],
)
def test_open_output_names(source, target, expected):
    result = suggest_output_path(Path(source), target, ConversionMode.DECOMPRESS)
    assert result.name == expected


def test_nds_trim_writes_over_its_input():
    """ndstrim edits in place; there is no second file to name."""
    source = Path("game.nds")
    assert suggest_output_path(source, CompressionFormat.NDS_TRIM) == source


@pytest.mark.parametrize(
    ("source", "expected"),
    [("game.cia", "game-decrypted.cia"),
     ("game.3ds", "game-decrypted.cci"),
     ("game.cci", "game-decrypted.cci")],
)
def test_decrypt_output_names(source, expected):
    """A .3ds and a .cci are both NCSD carts and both come back out as .cci."""
    assert suggest_output_path(Path(source), CompressionFormat.DEC_3DS).name == expected


def test_archive_open_targets_a_folder():
    result = suggest_output_path(Path("/roms/pack.7z"), CompressionFormat.SEVEN_ZIP,
                                 ConversionMode.DECOMPRESS)
    assert result.suffix == ""
    assert result.name == "pack"


def test_format_info_round_trip():
    for info in FORMAT_CATALOG:
        assert format_info(info.format) is info
