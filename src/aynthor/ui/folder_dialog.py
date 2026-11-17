"""Folder picker that can see a handheld sitting under This PC.

Used by
    The ROMs folder choice. A drive letter stays a path on this PC. A
    handheld comes back as the names under This PC, and the destination
    dialog turns those into the device it already knows how to send to.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QFileDialog, QWidget

from aynthor.core.win_folder import PickedFolder, win_pick_folder

__all__ = ["PickedFolder", "pick_folder"]


def pick_folder(parent: QWidget | None, title: str) -> PickedFolder | None:
    """The folder the user chose, or None if they cancelled."""
    if sys.platform == "win32":
        try:
            hwnd = int(parent.winId()) if parent is not None else 0
            return win_pick_folder(hwnd, title)
        except OSError:
            pass
    path = QFileDialog.getExistingDirectory(parent, title)
    if not path:
        return None
    return PickedFolder(path=path)
