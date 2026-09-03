"""Guessing a format from an extension and a folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PRESETS, PresetTable, detect_platform_format


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("game.cue", CompressionFormat.CHD),
        ("game.gdi", CompressionFormat.CHD),
        ("game.wbfs", CompressionFormat.RVZ),
        ("game.cci", CompressionFormat.Z3DS),
        ("game.nds", CompressionFormat.NDS_TRIM),
        ("game.nsp", CompressionFormat.NSZ),
        ("game.sfc", CompressionFormat.SEVEN_ZIP),
        ("game.gba", CompressionFormat.SEVEN_ZIP),
        ("game.wud", CompressionFormat.WUA),
    ],
)
def test_unambiguous_extensions(name, expected):
    assert detect_platform_format(Path(name)).format is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/ROMs/gc/Metroid Prime.iso", CompressionFormat.RVZ),
        ("/ROMs/wii/Twilight Princess.iso", CompressionFormat.RVZ),
        ("/ROMs/ps2/Persona 4.iso", CompressionFormat.CHD),
        ("/ROMs/psp/Daxter.iso", CompressionFormat.CHD),
    ],
)
def test_iso_is_resolved_by_the_folder_it_sits_in(path, expected):
    """A .iso can be four different systems; only the folder can say which."""
    assert detect_platform_format(Path(path)).format is expected


def test_iso_with_no_folder_hint_falls_back_to_ps2():
    """Documented fallback: PS2 is the largest ISO library on this class of device."""
    result = detect_platform_format(Path("Persona 4.iso"))
    assert result.platform == "ps2"
    assert result.format is CompressionFormat.CHD


def test_n64_is_skipped_with_a_reason():
    """z64 is already the most compatible form; compressing it helps nobody."""
    result = detect_platform_format(Path("Mario 64.z64"))
    assert result.skip is True
    assert result.skip_reason


def test_unrecognised_file_is_skipped_with_a_reason():
    result = detect_platform_format(Path("readme.txt"))
    assert result.skip is True
    assert result.skip_reason


def test_ps2_preset_avoids_zstd():
    """NetherSX2 cannot read zstd CHDs, so the PS2 preset must not offer it."""
    preset = PRESETS.default("ps2")
    assert preset.format is CompressionFormat.CHD
    assert preset.options["codecs"] == ["zlib"]
    assert preset.options["hunk_size"] == 2048


def test_arcade_presets_use_zip_not_7z():
    """FBNeo and MAME will not look inside a 7z."""
    for platform in ("fbneo", "mame"):
        preset = PRESETS.default(platform)
        assert preset.format is CompressionFormat.SEVEN_ZIP
        assert preset.options["archive_type"] == "zip"


def test_cartridge_presets_use_7z():
    for platform in ("snes", "gba", "gb", "gbc", "megadrive"):
        assert PRESETS.default(platform).options["archive_type"] == "7z"


def test_every_preset_has_a_readable_label():
    for preset in PRESETS:
        assert preset.label and preset.label != preset.platform


# ---------------------------------------------------------------- editing them

def test_editing_a_preset_changes_what_new_files_become():
    table = PresetTable()
    table.set_options("ps2", {"chd_type": "createdvd", "codecs": ["zstd"], "hunk_size": 0})
    result = detect_platform_format(Path("/ROMs/ps2/game.iso"), table)
    assert result.tool_options["codecs"] == ["zstd"]


def test_changing_a_preset_format_drops_the_old_tool_flags():
    """chdman's hunk size means nothing to DolphinTool, so it must not survive."""
    table = PresetTable()
    table.set_format("ps2", CompressionFormat.RVZ)
    preset = table.get("ps2")
    assert preset.format is CompressionFormat.RVZ
    assert preset.options == {}


def test_a_default_row_is_not_reported_as_modified():
    assert PresetTable().is_modified("ps2") is False


def test_an_edited_row_is_reported_as_modified():
    table = PresetTable()
    table.set_options("ps2", {"hunk_size": 4096})
    assert table.is_modified("ps2") is True


def test_reset_puts_one_platform_back():
    table = PresetTable()
    table.set_options("ps2", {"hunk_size": 4096})
    table.reset("ps2")
    assert table.get("ps2").options == PRESETS.default("ps2").options


def test_reset_all_puts_everything_back():
    table = PresetTable()
    table.set_format("ps2", CompressionFormat.RVZ)
    table.set_options("snes", {"level": 1})
    table.reset()
    assert not any(table.is_modified(p.platform) for p in table)


def test_only_edited_rows_are_persisted():
    """A default that improves later should still reach anyone who never
    touched that platform."""
    table = PresetTable()
    table.set_options("ps2", {"hunk_size": 4096})
    overrides = table.overrides()
    assert set(overrides) == {"ps2"}
    assert overrides["ps2"]["options"]["hunk_size"] == 4096


def test_overrides_survive_a_round_trip():
    table = PresetTable()
    table.set_format("psp", CompressionFormat.CSO)
    table.set_options("psp", {"cso_format": "zso"})
    restored = PresetTable()
    restored.apply_overrides(table.overrides())
    assert restored.get("psp").format is CompressionFormat.CSO
    assert restored.get("psp").options == {"cso_format": "zso"}


def test_unknown_platforms_in_stored_overrides_are_ignored():
    table = PresetTable()
    table.apply_overrides({"dreamcast64": {"format": "chd", "options": {}}})
    assert table.get("dreamcast64") is None


def test_a_corrupt_stored_format_is_ignored():
    table = PresetTable()
    table.apply_overrides({"ps2": {"format": "not-a-format", "options": {}}})
    assert table.get("ps2").format is CompressionFormat.CHD


def test_detection_returns_a_copy_so_a_row_cannot_edit_the_preset():
    table = PresetTable()
    first = detect_platform_format(Path("/ROMs/ps2/a.iso"), table).tool_options
    first["hunk_size"] = 9999
    assert table.get("ps2").options["hunk_size"] == 2048


def test_detected_options_are_a_copy_not_the_preset_itself():
    """A queue row edits its own options; the preset must not travel with it."""
    first = detect_platform_format(Path("/ROMs/ps2/a.iso")).tool_options
    first["hunk_size"] = 9999
    second = detect_platform_format(Path("/ROMs/ps2/b.iso")).tool_options
    assert second["hunk_size"] == 2048
