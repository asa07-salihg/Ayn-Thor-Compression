"""The drop target at the top of the window.

Why
    Dragging a folder in is how this app is used, so that has to be the most
    obvious thing on the screen rather than a hint painted behind an empty
    table. It is also the only place the three ways of adding files live, which
    is why there is no toolbar anywhere else.

    It has two sizes. Empty, it fills the top of the window and says what to
    do. Once the queue has rows it shrinks to a single strip, because at that
    point the table is what the user is looking at and a large empty rectangle
    above it is wasted screen.

Used by
    `ui.main_window`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aynthor.ui import theme


class DropZone(QFrame):
    paths_dropped = Signal(list)
    add_files = Signal()
    add_folder = Signal()
    import_list = Signal()

    _MIN_TALL = 190
    _SHORT = 56

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "dropzone")
        self.setProperty("active", False)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(10)

        self.headline = QLabel("Drop ROMs or a folder here")
        self.headline.setProperty("role", "drop")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.buttons = self._build_buttons()

        self._layout.addStretch()
        self._layout.addWidget(self.headline)
        self._layout.addWidget(self.buttons, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addStretch()

        self.set_compact(False)

    def _build_buttons(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for label, signal, tip in (
            ("Add files", self.add_files, "Pick ROM files (Ctrl+O)"),
            ("Add folder", self.add_folder, "Add every recognised ROM in a folder (Ctrl+Shift+O)"),
            ("Import list", self.import_list,
             "Load a list and match it against a ROMs folder (Ctrl+I)"),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(signal.emit)
            layout.addWidget(button)
        return row

    def set_compact(self, compact: bool) -> None:
        """Tall while the queue is empty, a strip once it is not."""
        if compact:
            self.setMinimumHeight(self._SHORT)
            self.setMaximumHeight(self._SHORT)
        else:
            self.setMinimumHeight(self._MIN_TALL)
            self.setMaximumHeight(16777215)
        self.headline.setVisible(not compact)
        if compact:
            self._layout.setContentsMargins(16, 8, 16, 8)
            self._layout.setAlignment(self.buttons, Qt.AlignmentFlag.AlignLeft)
        else:
            self._layout.setContentsMargins(16, 12, 16, 12)
            self._layout.setAlignment(self.buttons, Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------ drag and drop

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        theme.restyle(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        real = [p for p in paths if p.exists()]
        if real:
            self.paths_dropped.emit(real)
        event.acceptProposedAction()
