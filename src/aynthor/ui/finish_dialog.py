"""The summary at the end of a batch: what worked, what did not, where it went.

A finished batch used to end with one line in a log that was usually
closed, so the only sign was the progress bar disappearing. Someone
filling a card needs to know it is done, how much it saved, whether
anything failed, and where to find the games. This says all four and
offers the two obvious next steps: open the folder, or look at what
went wrong.

It is shown with `open()` rather than `exec()`. The batch has already
finished, so nothing waits on the answer, and a modal loop at the end of
a run would only get in the way of whatever the user does next.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from aynthor.ui import icons
from aynthor.ui.queue_view import human_size


def summary_lines(done: int, failed: int, skipped: int, saved: int) -> list[str]:
    """The sentences the dialog shows, in order."""
    games = f"{done} game{'s' if done != 1 else ''}"
    lines = [f"{games} done." + (f" You saved {human_size(saved)}." if saved > 0 else "")]
    if failed:
        lines.append(f"{failed} didn't work.")
    if skipped:
        lines.append(f"{skipped} skipped.")
    return lines


class FinishDialog(QDialog):
    SHOW_FAILURES = "failures"
    OPEN_FOLDER = "folder"

    def __init__(self, done: int, failed: int, skipped: int, saved: int,
                 folder: Path | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Finished")
        self.setMinimumWidth(460)
        self.choice = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel()
        badge.setPixmap(icons.pixmap(
            "check-circle" if not failed else "alert", "ok" if not failed else "warn",
            32, self.devicePixelRatioF()))
        top.addWidget(badge)
        heading = QLabel("All done" if not failed else "Finished, with problems")
        heading.setProperty("role", "title")
        top.addWidget(heading, stretch=1)
        layout.addLayout(top)

        self.lines = summary_lines(done, failed, skipped, saved)
        self.body = QLabel("\n".join(self.lines))
        self.body.setWordWrap(True)
        layout.addWidget(self.body)

        if folder is not None:
            where = QLabel(f"Your games are in {folder}")
            where.setWordWrap(True)
            where.setProperty("role", "second")
            layout.addWidget(where)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.failures_button: QPushButton | None = None
        if failed:
            self.failures_button = QPushButton("Show what went wrong")
            self.failures_button.clicked.connect(lambda: self._choose(self.SHOW_FAILURES))
            buttons.addWidget(self.failures_button)
        self.folder_button: QPushButton | None = None
        if folder is not None:
            self.folder_button = QPushButton("Open folder")
            self.folder_button.setProperty("accent", True)
            self.folder_button.clicked.connect(lambda: self._choose(self.OPEN_FOLDER))
            buttons.addWidget(self.folder_button)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _choose(self, choice: str) -> None:
        self.choice = choice
        self.accept()
