"""The Tools window: what is installed, what is missing, what is behind.

Why
    The app converts nothing without binaries it does not ship, so the first
    question a new user has is why nothing works. This answers it in one place:
    which tool each format needs, whether it is present, which version is
    pinned, and what licence it carries.

    Downloads run on a worker thread with a live log rather than a spinner,
    because a failed download is common (a release asset moves, a proxy
    interferes) and the reason matters more than the progress.

    **Check for updates** asks each project for its tags and marks anything
    behind. It does not offer to install what it finds, and that is deliberate
    rather than unfinished: the guarantee this app makes is that nothing
    reaches `tools/` unless it matches a checksum recorded in the manifest.
    Fetching a version that is by definition not in the manifest would mean
    running an executable nobody checked. A newer tool ships in the next
    release of this app, after someone has read the upstream changelog for
    flag changes.

    DolphinTool is offered two ways. Dolphin publishes no checksums for its
    Windows builds, so if the user already has Dolphin, copying the exe they
    already trust is the better option and the button says so.

Used by
    `ui.main_window`.

Reference
    The tool list: `core.tools.manifest`, with licences and provenance in
    THIRD-PARTY-NOTICES.md.
    The version check: `core.tools.versions`.
"""

from __future__ import annotations

import shutil
from typing import ClassVar

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.tools.manager import ToolsManager
from aynthor.core.tools.manifest import INSTALLABLE
from aynthor.core.tools.versions import Status, VersionReport, check_all, releases_url
from aynthor.ui import theme

_ROLE_KEY = Qt.ItemDataRole.UserRole


class _InstallWorker(QThread):
    log = Signal(str)
    done = Signal(list)

    def run(self) -> None:
        self.done.emit(ToolsManager().install_all(progress=self.log.emit))


class _VersionWorker(QThread):
    reported = Signal(object)  # VersionReport
    done = Signal()

    def run(self) -> None:
        check_all(INSTALLABLE, on_report=self.reported.emit)
        self.done.emit()


class ToolsDialog(QDialog):
    COL_TOOL, COL_STATUS, COL_PINNED, COL_LATEST, COL_FORMATS, COL_LICENCE = range(6)

    _STATUS_TEXT: ClassVar[dict[Status, str]] = {
        Status.CURRENT: "latest",
        Status.BEHIND: "newer available",
        Status.MANUAL: "check by hand",
        Status.UNKNOWN: "could not check",
        Status.PIP: "pip",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tools")
        self.resize(920, 600)
        self.manager = ToolsManager()
        self._install_worker: _InstallWorker | None = None
        self._version_worker: _VersionWorker | None = None
        # Reasons already written to the log this run; see `_on_version_report`.
        self._reasons_logged: set[str] = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(9)

        intro = QLabel(
            "Converters are downloaded from their own projects and checked against a "
            "pinned SHA-256 before they are installed. Nothing is bundled with this app.")
        intro.setWordWrap(True)
        intro.setProperty("role", "second")
        layout.addWidget(intro)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Tool", "Installed", "Pinned", "Upstream", "Used for", "Licence"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(30)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        for column, mode in (
            (self.COL_TOOL, QHeaderView.ResizeMode.ResizeToContents),
            (self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents),
            (self.COL_PINNED, QHeaderView.ResizeMode.ResizeToContents),
            (self.COL_LATEST, QHeaderView.ResizeMode.ResizeToContents),
            (self.COL_FORMATS, QHeaderView.ResizeMode.ResizeToContents),
            (self.COL_LICENCE, QHeaderView.ResizeMode.Stretch),
        ):
            header.setSectionResizeMode(column, mode)
        for column in range(self.table.columnCount()):
            self.table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.cellDoubleClicked.connect(self._open_project)
        layout.addWidget(self.table, stretch=1)

        self.location = QLabel()
        self.location.setProperty("role", "third")
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.location)

        layout.addLayout(self._build_buttons())

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        layout.addWidget(self.log)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

        self.refresh()

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(7)

        self.download_button = QPushButton("Download missing")
        self.download_button.setProperty("accent", True)
        self.download_button.clicked.connect(self._download)
        row.addWidget(self.download_button)

        self.check_button = QPushButton("Check for updates")
        self.check_button.setToolTip(
            "Ask each project for its latest tag.\n\n"
            "Nothing is installed from this: every download is verified against a\n"
            "checksum recorded in this release, so a newer tool arrives with the\n"
            "next update of the app.")
        self.check_button.clicked.connect(self._check_versions)
        row.addWidget(self.check_button)

        refresh = QPushButton("Rescan")
        refresh.setToolTip("Look again at what is in the tools folder.")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)

        pick_dolphin = QPushButton("Use my DolphinTool...")
        pick_dolphin.setToolTip(
            "Copy DolphinTool.exe out of a Dolphin install you already have.\n"
            "Preferred over downloading: Dolphin publishes no checksum to verify against.")
        pick_dolphin.clicked.connect(self._pick_dolphin)
        row.addWidget(pick_dolphin)

        row.addStretch()
        return row

    # ------------------------------------------------------------------ table

    def refresh(self) -> None:
        self.manager.refresh()
        status = self.manager.status()
        self.table.setRowCount(len(INSTALLABLE))

        for row, spec in enumerate(INSTALLABLE):
            installed = status.get(spec.key, False)
            unverifiable = any(f.sha256 is None for f in spec.files)

            name = QTableWidgetItem(spec.label)
            name.setData(_ROLE_KEY, spec.key)
            name.setToolTip(f"{spec.description}\n{spec.homepage}\n\nDouble-click to open.")
            licence_note = ("ctrtool and makerom come from Project_CTR, also MIT."
                            if spec.key == "3ds-decryptor" else spec.homepage)
            self.table.setItem(row, self.COL_TOOL, name)

            state = QTableWidgetItem("yes" if installed else "no")
            state.setForeground(theme.color("ok" if installed else "textThird"))
            self.table.setItem(row, self.COL_STATUS, state)

            pinned = QTableWidgetItem(spec.version + ("  (unverified)" if unverifiable else ""))
            if unverifiable:
                pinned.setForeground(theme.color("warn"))
                pinned.setToolTip(
                    "This project publishes no checksum for its builds, so the download "
                    "cannot be verified. Prefer a copy you already have.")
            self.table.setItem(row, self.COL_PINNED, pinned)

            self.table.setItem(row, self.COL_LATEST, QTableWidgetItem(""))
            self.table.setItem(row, self.COL_FORMATS, QTableWidgetItem(", ".join(spec.formats)))
            licence = QTableWidgetItem(spec.license)
            licence.setToolTip(licence_note)
            self.table.setItem(row, self.COL_LICENCE, licence)

        missing = sum(1 for ready in status.values() if not ready)
        self.download_button.setEnabled(missing > 0)
        self.download_button.setText(
            "Everything installed" if missing == 0 else f"Download {missing} missing")
        self.location.setText(f"Installed in: {self.manager.tools_root}")

    def _row_of(self, key: str) -> int:
        for row in range(self.table.rowCount()):
            if self.table.item(row, self.COL_TOOL).data(_ROLE_KEY) == key:
                return row
        return -1

    def _open_project(self, row: int, _column: int) -> None:
        key = self.table.item(row, self.COL_TOOL).data(_ROLE_KEY)
        spec = next((s for s in INSTALLABLE if s.key == key), None)
        if spec is not None:
            QDesktopServices.openUrl(QUrl(releases_url(spec)))

    # -------------------------------------------------------------- installing

    def _download(self) -> None:
        self.download_button.setEnabled(False)
        self.log.appendPlainText("Starting.")
        self._install_worker = _InstallWorker()
        self._install_worker.log.connect(self.log.appendPlainText)
        self._install_worker.done.connect(self._on_installed)
        self._install_worker.start()

    def _on_installed(self, errors: list[str]) -> None:
        self.refresh()
        if not errors:
            self.log.appendPlainText("Done.")
            return
        for error in errors:
            self.log.appendPlainText(error)

    def _pick_dolphin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select DolphinTool.exe", "", "DolphinTool (DolphinTool.exe)")
        if not path:
            return
        shutil.copy2(path, self.manager.tools_root / "DolphinTool.exe")
        self.log.appendPlainText(f"Copied DolphinTool from {path}")
        self.refresh()

    # ---------------------------------------------------------- version check

    def _check_versions(self) -> None:
        if self._version_worker is not None and self._version_worker.isRunning():
            return
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking...")
        self._reasons_logged.clear()
        for row in range(self.table.rowCount()):
            self.table.item(row, self.COL_LATEST).setText("...")

        self._version_worker = _VersionWorker()
        self._version_worker.reported.connect(self._on_version_report)
        self._version_worker.done.connect(self._on_versions_done)
        self._version_worker.start()

    def _on_version_report(self, report: VersionReport) -> None:
        row = self._row_of(report.spec.key)
        if row < 0:
            return
        cell = self.table.item(row, self.COL_LATEST)
        cell.setText(report.latest or self._STATUS_TEXT[report.status])
        cell.setToolTip(report.detail or "")

        if report.status is Status.BEHIND:
            cell.setForeground(theme.color("warn"))
            self.log.appendPlainText(
                f"{report.spec.label}: pinned {report.spec.version}, {report.detail}")
        elif report.status in (Status.UNKNOWN, Status.MANUAL):
            cell.setForeground(theme.color("textThird"))
            # "could not check" on its own reads as a fault in the tool. Say why,
            # but only once: when GitHub is rate limiting, every remaining row
            # carries the same sentence and nine copies of it is not a log.
            if report.status is Status.UNKNOWN and report.detail not in self._reasons_logged:
                self._reasons_logged.add(report.detail)
                self.log.appendPlainText(report.detail)
        else:
            cell.setForeground(theme.color("ok"))

    def _on_versions_done(self) -> None:
        self.check_button.setEnabled(True)
        self.check_button.setText("Check for updates")
        self.log.appendPlainText(
            "A tool marked as having a newer version is not installed from here: every "
            "download is verified against a checksum recorded in this release, so an "
            "updated tool arrives with the next update of the app. Double-click a row "
            "to open its release page.")
