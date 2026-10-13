"""The folder picker must keep handhelds that have no drive letter."""

from aynthor.core.win_folder import (
    FOS_FORCEFILESYSTEM,
    FOS_PICKFOLDERS,
    folder_options,
)


def test_folder_dialog_does_not_hide_devices_without_a_drive_letter():
    options = folder_options(FOS_FORCEFILESYSTEM | 0x800)
    assert options & FOS_PICKFOLDERS
    assert not options & FOS_FORCEFILESYSTEM
