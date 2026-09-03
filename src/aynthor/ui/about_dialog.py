"""The About box.

Why
    An app that runs nine third-party tools owes the user a list of them and
    their licences somewhere reachable from inside the app, not only in a
    README they will never open. It is also where the version goes, which is
    the first thing anyone is asked for in a bug report.

Used by
    `ui.main_window` (Help menu).

Reference
    The full notice file: THIRD-PARTY-NOTICES.md.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from aynthor import PROJECT_URL, __version__
from aynthor.core.tools.manifest import INSTALLABLE


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Ayn Thor Compression")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)

        title = QLabel(f"Ayn Thor Compression {__version__}")
        font = title.font()
        font.setPointSizeF(font.pointSizeF() + 3)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        summary = QLabel(
            "A desktop front end for the ROM compression tools each emulator expects. "
            "It converts nothing itself: every format is handled by the project that "
            "defined it.<br><br>"
            f'<a href="{PROJECT_URL}">{PROJECT_URL}</a>'
        )
        summary.setWordWrap(True)
        summary.setOpenExternalLinks(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        layout.addWidget(summary)

        credits = QLabel(self._credits_html())
        credits.setWordWrap(True)
        credits.setOpenExternalLinks(True)
        credits.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        credits.setProperty("role", "dim")
        layout.addWidget(credits)

        legal = QLabel(
            "No ROMs, console keys or copyrighted game data are distributed with this "
            "project. Switch support requires keys you dump from your own console."
        )
        legal.setWordWrap(True)
        legal.setProperty("role", "faint")
        layout.addWidget(legal)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

    @staticmethod
    def _credits_html() -> str:
        rows = "<br>".join(
            f'&nbsp;&nbsp;<a href="{spec.homepage}">{spec.label}</a> &mdash; {spec.license}'
            for spec in INSTALLABLE
        )
        return f"<b>Built on</b><br>{rows}"
