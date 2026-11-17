"""Turning a This PC selection into the device folder games are sent to."""

from pathlib import Path

from aynthor.core.device import FoundDevice, FoundStorage, target_from_breadcrumb
from aynthor.core.esde import usable_pc_folder
from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.output import output_for
from aynthor.core.settings import FormatSettings


def _thor() -> FoundDevice:
    return FoundDevice("usb#thor", "AYN Thor", (
        FoundStorage("Internal shared storage", 1, 1, None),
        FoundStorage("disk", 1, 1, "ROMs"),
    ))


def test_choosing_the_roms_folder_roots_the_sd_card_there():
    target = target_from_breadcrumb(("AYN Thor", "disk", "ROMs"), [_thor()])
    assert target is not None
    assert (target.storage, target.root) == ("disk", "ROMs")


def test_choosing_the_sd_card_uses_the_roms_folder_already_on_it():
    target = target_from_breadcrumb(("AYN Thor", "disk"), [_thor()])
    assert target is not None
    assert target.root == "ROMs"


def test_a_folder_under_roms_still_roots_at_roms():
    target = target_from_breadcrumb(("AYN Thor", "disk", "ROMs", "psx"), [_thor()])
    assert target is not None
    assert target.root == "ROMs"


def test_a_saved_shell_id_is_not_a_folder_on_this_pc(tmp_path: Path):
    assert usable_pc_folder("::{20D04FE0-3AEA-1069-A2D8-08002B30309D}") == ""
    source = tmp_path / "Game.iso"
    settings = FormatSettings(esde_root="::{20D04FE0-3AEA-1069-A2D8-08002B30309D}")
    result = output_for(
        source, CompressionFormat.CHD, ConversionMode.COMPRESS, settings, platform="psx")
    assert result.parent == tmp_path
