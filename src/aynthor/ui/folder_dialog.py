"""Folder picker that can see a handheld sitting under This PC.

Used by
    The ROMs folder, the output folder, and Add a folder.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from aynthor.core.win_folder import win_pick_folder


def pick_folder(parent: QWidget | None, title: str) -> str:
    """The folder the user chose, or '' if they cancelled."""
    if sys.platform == "win32":
        try:
            hwnd = int(parent.winId()) if parent is not None else 0
            chosen = win_pick_folder(hwnd, title)
        except OSError:
            chosen = None
        if chosen is not None:
            if chosen == "":
                QMessageBox.information(
                    parent,
                    "That device has no folder path",
                    "Windows is showing this as a connected device, not as a drive. "
                    "The app can only open a normal folder. If the handheld can "
                    "connect as a USB drive, use that, then choose the drive here.",
                )
                return ""
            return chosen
    return QFileDialog.getExistingDirectory(parent, title)
