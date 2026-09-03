"""The update flow: ask GitHub, show what is there, replace this build.

Why
    Checking and downloading both block on the network, so both happen on
    worker threads and the window stays responsive. The dialog exists rather
    than a message box because a release has something to read: what changed,
    and how big the download is.

    Nothing is automatic. There is no check on a timer and no silent install:
    the user opens this, sees the version and the notes, and presses a button.
    An app that replaces its own executable should never do it unasked.

Used by
    `ui.main_window` (the More menu), `ui.about_dialog`.

Reference
    The mechanism: `core.updates`.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from aynthor import LATEST_RELEASE_URL, __version__
from aynthor.core import updates
from aynthor.core.runtime import is_frozen


def _human(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB" if size else "unknown size"


class _CheckWorker(QThread):
    done = Signal(object)   # updates.Release or None
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.done.emit(updates.check())
        except updates.UpdateError as exc:
            self.failed.emit(str(exc))


class _DownloadWorker(QThread):
    progress = Signal(int)
    done = Signal(object)   # Path
    failed = Signal(str)

    def __init__(self, release: updates.Release) -> None:
        super().__init__()
        self._release = release

    def run(self) -> None:
        try:
            self.done.emit(updates.download_verified(self._release, self.progress.emit))
        except updates.UpdateError as exc:
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, release: updates.Release, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Update available")
        self.setMinimumWidth(520)
        self._release = release
        self._worker: _DownloadWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        heading = QLabel(f"Version {release.version} is available")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        subtitle = QLabel(f"You have {__version__}.  Download is {_human(release.asset_size)}.")
        subtitle.setProperty("role", "second")
        layout.addWidget(subtitle)

        if release.notes:
            notes = QTextBrowser()
            notes.setPlainText(release.notes)
            notes.setMaximumHeight(220)
            layout.addWidget(notes)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "second")
        self.status.hide()
        layout.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        open_page = QPushButton("Open release page")
        open_page.setProperty("subtle", True)
        open_page.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(release.page_url or LATEST_RELEASE_URL)))
        buttons.addWidget(open_page)
        buttons.addStretch()

        self.later = QPushButton("Later")
        self.later.clicked.connect(self.reject)
        buttons.addWidget(self.later)

        self.install = QPushButton("Download and install")
        self.install.setProperty("accent", True)
        self.install.clicked.connect(self._start_download)
        buttons.addWidget(self.install)
        layout.addLayout(buttons)

        blocked = self._why_not_installable(release)
        if blocked:
            self.install.setEnabled(False)
            self._say(blocked)

    @staticmethod
    def _why_not_installable(release: updates.Release) -> str:
        """Empty when this build can replace itself with that release."""
        if not release.is_installable:
            return ("This release has no verifiable Windows build attached, so it "
                    "cannot be installed from here. Use the release page.")
        if not is_frozen():
            return ("This is running from source, so there is no executable to "
                    "replace. Pull the new version with git, or use the release page.")
        if not updates.can_self_update():
            return ("The folder this exe sits in is not writable, so it cannot "
                    "replace itself. Move it somewhere you can write to, or "
                    "download the new build from the release page.")
        return ""

    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _start_download(self) -> None:
        self.install.setEnabled(False)
        self.later.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self._say("Downloading, then checking it against the release checksum.")

        self._worker = _DownloadWorker(self._release)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.done.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_failed(self, message: str) -> None:
        self.progress.hide()
        self.later.setEnabled(True)
        self.install.setEnabled(True)
        self._say(message)

    def _on_downloaded(self, download) -> None:
        self.progress.hide()
        self._say("Verified.")
        confirm = QMessageBox.question(
            self, "Restart to finish",
            f"Version {self._release.version} is downloaded and its checksum matches.\n\n"
            "The app will close, replace itself and start again. Anything still in "
            "the queue will be lost.\n\nGo ahead?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if confirm != QMessageBox.StandardButton.Yes:
            self._say(f"Left the download at {download}. Replace the exe yourself "
                      "whenever you like.")
            self.later.setEnabled(True)
            return

        try:
            updates.apply_update(download)
        except updates.UpdateError as exc:
            self._on_failed(str(exc))
            return

        self.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()


class UpdateCheck:
    """Runs a check and shows the right window for whatever comes back.

    Held by the main window so the worker is not garbage collected mid-flight.
    """

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._worker: _CheckWorker | None = None

    def run(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _CheckWorker()
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, release) -> None:
        if release is None:
            QMessageBox.information(
                self._parent, "Up to date",
                f"Version {__version__} is the latest release.")
            return
        UpdateDialog(release, self._parent).exec()

    def _on_failed(self, message: str) -> None:
        QMessageBox.warning(self._parent, "Could not check for updates", message)
