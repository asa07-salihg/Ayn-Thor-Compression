"""Why a row failed, and the one thing to do about it.

Why
    A red "Failed" with the converter's own words in a tooltip told a
    first-time user nothing they could act on. Clicking it now opens this:
    the plain explanation from `core.explain`, a button for the fix when
    there is one, and the original text behind "Show technical details" for
    anyone reporting a bug.

    The dialog only records which fix was chosen. Carrying it out (opening
    Tools, choosing keys) needs the main window's settings and tools, so the
    main window does it after the dialog closes.

Used by
    `ui.main_window` (a Failed status clicked, or "What went wrong?" in the
    row menu).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.explain import Explanation, Fix
from aynthor.ui import icons

_FIX_LABELS = {
    Fix.OPEN_TOOLS: "Open Tools",
    Fix.CHOOSE_KEYS: "Choose prod.keys...",
    Fix.OPEN_FOLDER: "Open the folder",
    Fix.GET_7ZIP: "Get 7-Zip",
}


class FailureDialog(QDialog):
    def __init__(self, file_name: str, explanation: Explanation,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("What went wrong")
        self.setMinimumWidth(520)
        self.chosen_fix: Fix | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        name = QLabel(file_name)
        name.setProperty("role", "third")
        name.setWordWrap(True)
        layout.addWidget(name)

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel()
        badge.setPixmap(icons.pixmap("alert", "error", 32, self.devicePixelRatioF()))
        badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(badge)
        self.summary = QLabel(explanation.summary)
        self.summary.setProperty("role", "title")
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, stretch=1)
        layout.addLayout(top)

        self.advice = QLabel(explanation.advice)
        self.advice.setWordWrap(True)
        layout.addWidget(self.advice)

        self.details_button = QPushButton("Show technical details")
        self.details_button.setProperty("subtle", True)
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_details)
        self.details = QPlainTextEdit(explanation.details)
        self.details.setObjectName("log")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(140)
        self.details.hide()
        self.copy_button = QPushButton("Copy")
        self.copy_button.setProperty("subtle", True)
        self.copy_button.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(explanation.details))
        self.copy_button.hide()
        if explanation.details:
            detail_row = QHBoxLayout()
            detail_row.addWidget(self.details_button)
            detail_row.addStretch()
            detail_row.addWidget(self.copy_button)
            layout.addLayout(detail_row)
            layout.addWidget(self.details)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.fix_button: QPushButton | None = None
        label = _FIX_LABELS.get(explanation.fix)
        if label:
            self.fix_button = QPushButton(label)
            self.fix_button.setProperty("accent", True)
            self.fix_button.setDefault(True)
            self.fix_button.clicked.connect(lambda: self._choose(explanation.fix))
            buttons.addWidget(self.fix_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _toggle_details(self, shown: bool) -> None:
        self.details.setVisible(shown)
        self.copy_button.setVisible(shown)
        self.details_button.setText(
            "Hide technical details" if shown else "Show technical details")

    def _choose(self, fix: Fix) -> None:
        self.chosen_fix = fix
        self.accept()
