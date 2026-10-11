"""The drop target at the top of the window.

Why
    Dragging a folder in is how this app is used, so that has to be the most
    obvious thing on the screen rather than a hint painted behind an empty
    table. It is also the only place the three ways of adding files live, which
    is why there is no toolbar anywhere else.

    It has two sizes. Empty, it fills the top of the window and says what to
    do, with the whole job laid out as three numbered steps for someone who
    has never used a tool like this. Once the queue has rows it shrinks to a
    single strip, because at that point the table is what the user is looking
    at and a large empty rectangle above it is wasted screen.

Used by
    `ui.main_window`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from aynthor.ui import icons, theme

STEPS = ("Add your games", "Check what each one becomes", "Press Start")


class _DropIcon(QWidget):
    """An arrow going down into a tray, in the accent colour while dragging."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(64, 56)
        self.active = False

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(theme.color("accent" if self.active else "textThird"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        width = self.width()
        middle = width / 2
        painter.drawLine(QPointF(middle, 4), QPointF(middle, 28))
        painter.drawLine(QPointF(middle - 9, 19), QPointF(middle, 28))
        painter.drawLine(QPointF(middle + 9, 19), QPointF(middle, 28))

        tray = QPainterPath()
        tray.moveTo(8, 32)
        tray.lineTo(8, 50)
        tray.lineTo(width - 8, 50)
        tray.lineTo(width - 8, 32)
        tray.moveTo(8, 38)
        tray.lineTo(20, 38)
        tray.lineTo(24, 43)
        tray.lineTo(width - 24, 43)
        tray.lineTo(width - 20, 38)
        tray.lineTo(width - 8, 38)
        painter.drawPath(tray)


class DropZone(QFrame):
    paths_dropped = Signal(list)
    add_files = Signal()
    add_folder = Signal()
    import_list = Signal()
    expand_all = Signal()
    collapse_all = Signal()

    _MIN_TALL = 300
    _SHORT = 64

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "dropzone")
        self.setProperty("active", False)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 12)
        self._layout.setSpacing(10)

        # Everything shown only while the queue is empty lives in its own
        # container, so hiding it also removes its spacing. Loose spacers left
        # behind pushed the buttons out of the compact strip.
        self.intro = QWidget()
        intro = QVBoxLayout(self.intro)
        intro.setContentsMargins(0, 0, 0, 6)
        intro.setSpacing(10)
        self.icon = _DropIcon()
        self.headline = QLabel("Drop your games here")
        self.headline.setProperty("role", "hero")
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel("Single files, whole folders, and zip or RAR downloads all work.")
        self.hint.setProperty("role", "second")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        intro.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignCenter)
        intro.addWidget(self.headline)
        intro.addWidget(self.hint)

        self.buttons = self._build_buttons()
        self.steps = self._build_steps()

        self._layout.addStretch()
        self._layout.addWidget(self.intro)
        self._layout.addWidget(self.buttons, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self.steps, alignment=Qt.AlignmentFlag.AlignCenter)
        self._layout.addStretch()

        self.set_compact(False)

    def _build_buttons(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._icon_buttons: list[tuple[QPushButton, str]] = []
        for label, signal, tip, subtle, icon_name in (
            ("Add files", self.add_files, "Pick game files (Ctrl+O)", False, "add-file"),
            ("Add folder", self.add_folder,
             "Add a folder and every game in it (Ctrl+Shift+O)", False, "add-folder"),
            ("Import list", self.import_list,
             "For advanced use: load a text list of games and find them in a ROMs "
             "folder (Ctrl+I)", True, "list"),
        ):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.setProperty("subtle", subtle)
            button.setIconSize(QSize(16, 16))
            button.clicked.connect(signal.emit)
            self._icon_buttons.append((button, icon_name))
            layout.addWidget(button)
        self.apply_icons()
        self._spacer = QWidget()
        self._spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._spacer)
        self.expand_button = QPushButton("Expand all")
        self.expand_button.setProperty("subtle", True)
        self.expand_button.setToolTip("Open every folder in the queue")
        self.expand_button.clicked.connect(self.expand_all.emit)
        self.collapse_button = QPushButton("Collapse all")
        self.collapse_button.setProperty("subtle", True)
        self.collapse_button.setToolTip("Close every folder in the queue")
        self.collapse_button.clicked.connect(self.collapse_all.emit)
        layout.addWidget(self.expand_button)
        layout.addWidget(self.collapse_button)
        return row

    def apply_icons(self) -> None:
        """Recolour the button icons for the current theme."""
        for button, name in self._icon_buttons:
            button.setIcon(icons.icon(name))

    def _build_steps(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(22)
        for number, text in enumerate(STEPS, start=1):
            pair = QHBoxLayout()
            pair.setSpacing(8)
            badge = QLabel(str(number))
            badge.setProperty("role", "step")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(22, 22)
            label = QLabel(text)
            label.setProperty("role", "second")
            pair.addWidget(badge)
            pair.addWidget(label)
            layout.addLayout(pair)
        return row

    def set_compact(self, compact: bool) -> None:
        """Tall while the queue is empty, a strip once it is not."""
        if compact:
            self.setMinimumHeight(self._SHORT)
            self.setMaximumHeight(self._SHORT)
        else:
            self.setMinimumHeight(self._MIN_TALL)
            self.setMaximumHeight(16777215)
        for widget in (self.intro, self.steps):
            widget.setVisible(not compact)
        self._spacer.setVisible(compact)
        self.expand_button.setVisible(compact)
        self.collapse_button.setVisible(compact)
        if compact:
            self._layout.setContentsMargins(16, 8, 16, 8)
            self._layout.setAlignment(self.buttons, Qt.AlignmentFlag.AlignLeft)
        else:
            self._layout.setContentsMargins(16, 12, 16, 12)
            self._layout.setAlignment(self.buttons, Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------ drag and drop

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.icon.active = active
        self.icon.update()
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
