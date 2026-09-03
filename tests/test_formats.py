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


# ------------------------------------------------------- direction on adding

def test_a_file_already_in_the_target_format_is_queued_as_an_expand():
    """A .chd queued as "compress to CHD" wrote its own input path."""
    from aynthor.core.formats import natural_mode
    from aynthor.core.models import CompressionFormat, ConversionMode

    assert natural_mode(Path("Chrono Cross.chd"), CompressionFormat.CHD) \
        is ConversionMode.DECOMPRESS
    assert natural_mode(Path("Chrono Cross.cue"), CompressionFormat.CHD) \
        is ConversionMode.COMPRESS


@pytest.mark.parametrize("name, fmt", [
    ("game.rvz", CompressionFormat.RVZ),
    ("game.cso", CompressionFormat.CSO),
    ("game.zso", CompressionFormat.CSO),
    ("game.zcci", CompressionFormat.Z3DS),
    ("game.zcia", CompressionFormat.Z3DS),
    ("game.nsz", CompressionFormat.NSZ),
    ("game.xcz", CompressionFormat.NSZ),
])
def test_every_compressed_container_expands_on_the_way_in(name, fmt):
    from aynthor.core.formats import natural_mode
    from aynthor.core.models import ConversionMode

    assert natural_mode(Path(name), fmt) is ConversionMode.DECOMPRESS


@pytest.mark.parametrize("name, fmt", [
    # A cartridge archive is the form RetroArch reads, and a folder of MAME
    # romsets is meant to stay zipped: expanding these on sight would be wrong.
    ("Chrono Trigger.7z", CompressionFormat.SEVEN_ZIP),
    ("sf2.zip", CompressionFormat.SEVEN_ZIP),
    # Nothing in the name says whether a cart has been trimmed or decrypted.
    ("game.nds", CompressionFormat.NDS_TRIM),
    ("game.cci", CompressionFormat.DEC_3DS),
    # Nothing reverses a WUA.
    ("game.wua", CompressionFormat.WUA),
])
def test_the_formats_that_must_not_auto_expand_do_not(name, fmt):
    from aynthor.core.formats import natural_mode
    from aynthor.core.models import ConversionMode

    assert natural_mode(Path(name), fmt) is ConversionMode.COMPRESS


def test_reverse_on_only_names_extensions_the_format_already_claims():
    """Otherwise a file could auto-expand into a format that will not take it."""
    from aynthor.core.formats import FORMAT_CATALOG

    for info in FORMAT_CATALOG:
        assert set(info.reverse_on) <= set(info.extensions), info.label


def test_a_format_that_auto_expands_has_a_direction_to_expand_into():
    from aynthor.core.formats import FORMAT_CATALOG
    from aynthor.core.models import ConversionMode
    from aynthor.core.modes import FORMAT_MODES

    for info in FORMAT_CATALOG:
        if not info.reverse_on:
            continue
        modes = {m.mode for m in FORMAT_MODES[info.format]}
        assert ConversionMode.DECOMPRESS in modes, info.label


def test_each_format_names_its_reverse_after_what_it_actually_does():
    """One verb does not cover unzipping an archive and decompressing a CHD."""
    from aynthor.core.modes import FORMAT_MODES

    verbs = {
        fmt: [m.description for m in modes if m.mode is ConversionMode.DECOMPRESS]
        for fmt, modes in FORMAT_MODES.items()
    }
    assert verbs[CompressionFormat.SEVEN_ZIP] == ["Unzip"]
    assert verbs[CompressionFormat.CHD] == ["Decompress"]
    assert verbs[CompressionFormat.NSZ] == ["Decompress"]
    # And nothing is still called "Open", which said nothing.
    for fmt, modes in FORMAT_MODES.items():
        for info in modes:
            assert info.description != "Open", fmt
