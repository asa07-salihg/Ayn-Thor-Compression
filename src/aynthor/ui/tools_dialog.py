"""The Tools window: what is installed, what is missing, what is behind.

The app converts nothing without binaries it does not ship, so the first
question a new user has is why nothing works. This answers it in one place:
which tool each format needs, whether it is present, which version is
pinned, and what licence it carries.

Downloads run on a worker thread with a live log rather than a spinner,
because a failed download is common (a release asset moves, a proxy
interferes) and the reason matters more than the progress.

**Check for updates** asks each project for its tags. When something is
behind, **Update N tools** downloads that tag, hashes it, and remembers
the hash in `tools/pins.json` so the next open still trusts it.

A tool can also be present and still not be the one this release pins,
which is what happens after an app update moves a pin. Those rows say
**Needs update** and the Download button replaces them from the manifest.

DolphinTool is offered two ways. Dolphin publishes no checksums for its
Windows builds, so if the user already has Dolphin, copying the exe they
already trust is the better option and the button says so.

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
    QCheckBox,
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
from aynthor.core.tools.pins import effective_version
from aynthor.core.tools.versions import Status, VersionReport, check_all, releases_url
from aynthor.ui import theme

_ROLE_KEY = Qt.ItemDataRole.UserRole

# What each program is for, in the words of someone filling a card.
_USED_FOR = {
    "chdman": "PlayStation, PS2, PSP, Dreamcast and other disc games",
    "DolphinTool": "GameCube and Wii games",
    "maxcso": "PSP games",
    "7z": "Cartridge and arcade games, and opening .7z downloads",
    "ndstrim": "Nintendo DS games",
    "rom-converto": "Nintendo 3DS and Wii U games",
    "3ds-decryptor": "Getting Nintendo 3DS games ready to compress",
    "z3ds_compress": "Nintendo 3DS games",
    "nsz": "Nintendo Switch games",
}


class InstallWorker(QThread):
    """Installs every missing or outdated program off the UI thread."""

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


class _UpgradeWorker(QThread):
    """Installs each behind tool's newest tag off the UI thread."""

    log = Signal(str)
    done = Signal(list)

    def __init__(self, updates: list[tuple[str, str]]) -> None:
        super().__init__()
        self._updates = updates

    def run(self) -> None:
        self.done.emit(ToolsManager().upgrade_all(self._updates, progress=self.log.emit))


class ToolsDialog(QDialog):
    COL_TOOL, COL_STATUS, COL_PINNED, COL_LATEST, COL_FORMATS, COL_LICENCE = range(6)

    _DETAIL_COLUMNS = (COL_PINNED, COL_LATEST, COL_LICENCE)

    _STATUS_TEXT: ClassVar[dict[Status, str]] = {
        Status.CURRENT: "latest",
        Status.BEHIND: "newer available",
        Status.MANUAL: "check by hand",
        Status.UNKNOWN: "could not check",
        Status.PIP: "pip",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Converter programs")
        self.resize(920, 600)
        self.manager = ToolsManager()
        self._install_worker: InstallWorker | None = None
        self._version_worker: _VersionWorker | None = None
        self._upgrade_worker: _UpgradeWorker | None = None
        # Reasons already written to the log this run; see `_on_version_report`.
        self._reasons_logged: set[str] = set()
        # (key, tag) found by the last Check for updates run.
        self._pending_upgrades: list[tuple[str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(9)

        intro = QLabel(
            "These free programs do the actual converting. Each one is downloaded from "
            "its own project and checked against a known fingerprint before it is used.")
        intro.setWordWrap(True)
        intro.setProperty("role", "second")
        layout.addWidget(intro)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Program", "Status", "Version", "Newest", "Used for", "Licence"])
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
            (self.COL_FORMATS, QHeaderView.ResizeMode.Stretch),
            (self.COL_LICENCE, QHeaderView.ResizeMode.ResizeToContents),
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

        self.details_box = QCheckBox("Show details (versions, licences, update check)")
        self.details_box.toggled.connect(self._show_details)
        layout.addWidget(self.details_box)

        layout.addLayout(self._build_buttons())

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.hide()
        layout.addWidget(self.log)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(self.reject)
        box.accepted.connect(self.accept)
        layout.addWidget(box)

        self.refresh()
        self._show_details(False)

    def _say(self, text: str) -> None:
        self.log.show()
        self.log.appendPlainText(text)

    def _show_details(self, shown: bool) -> None:
        for column in self._DETAIL_COLUMNS:
            self.table.setColumnHidden(column, not shown)
        self.check_button.setVisible(shown)
        self.upgrade_button.setVisible(shown and bool(self._pending_upgrades))
        self.location.setVisible(shown)

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(7)

        self.download_button = QPushButton("Download missing")
        self.download_button.setProperty("accent", True)
        self.download_button.clicked.connect(self._download)
        row.addWidget(self.download_button)

        self.check_button = QPushButton("Check for updates")
        self.check_button.setToolTip(
            "Ask each project for its latest tag. If something is newer, an\n"
            "Update button appears that downloads it and records its checksum.")
        self.check_button.clicked.connect(self._check_versions)
        row.addWidget(self.check_button)

        self.upgrade_button = QPushButton("Update tools")
        self.upgrade_button.setVisible(False)
        self.upgrade_button.setProperty("accent", True)
        self.upgrade_button.setToolTip(
            "Download the newer builds found by Check for updates.\n"
            "Each file is hashed and the hash is kept next to the tool.")
        self.upgrade_button.clicked.connect(self._upgrade_behind)
        row.addWidget(self.upgrade_button)

        refresh = QPushButton("Look again")
        refresh.setToolTip("Check the tools folder again, after copying a program in by hand.")
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)

        pick_dolphin = QPushButton("Use my own DolphinTool...")
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
        # Installed is not the same question as current: a pin that moved in a
        # newer release of this app leaves the old binary sitting in tools/.
        stale = set(self.manager.outdated())
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

            outdated = spec.key in stale
            state = QTableWidgetItem(
                "Needs update" if outdated else ("Ready" if installed else "Not installed"))
            if outdated:
                state.setForeground(theme.color("warn"))
                state.setToolTip(
                    f"The copy in tools/ is not the {spec.version} this release pins.\n"
                    "Press the button below to replace it with the pinned build.")
            else:
                state.setForeground(theme.color("ok" if installed else "textThird"))
            self.table.setItem(row, self.COL_STATUS, state)

            shown_version = effective_version(spec)
            pinned = QTableWidgetItem(
                shown_version + ("  (unverified)" if unverifiable else ""))
            if unverifiable:
                pinned.setForeground(theme.color("warn"))
                pinned.setToolTip(
                    "This project publishes no checksum for its builds, so the download "
                    "cannot be verified. Prefer a copy you already have.")
            elif shown_version != spec.version:
                pinned.setToolTip(
                    f"Installed from Check for updates. This release pins {spec.version}.")
            self.table.setItem(row, self.COL_PINNED, pinned)

            self.table.setItem(row, self.COL_LATEST, QTableWidgetItem(""))
            used_for = QTableWidgetItem(_USED_FOR.get(spec.key, ", ".join(spec.formats)))
            used_for.setToolTip(f"Formats: {', '.join(spec.formats)}")
            self.table.setItem(row, self.COL_FORMATS, used_for)
            licence = QTableWidgetItem(spec.license)
            licence.setToolTip(licence_note)
            self.table.setItem(row, self.COL_LICENCE, licence)

        missing = sum(1 for ready in status.values() if not ready)
        self.download_button.setEnabled(missing + len(stale) > 0)
        if missing == 0 and not stale:
            self.download_button.setText("Everything is installed")
        elif missing == 0:
            self.download_button.setText(
                f"Update {len(stale)} program{'s' if len(stale) != 1 else ''}")
        elif stale:
            self.download_button.setText(f"Install {missing} missing, update {len(stale)}")
        else:
            self.download_button.setText(
                f"Install {missing} missing program{'s' if missing != 1 else ''}")
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
        self._say("Starting.")
        self._install_worker = InstallWorker()
        self._install_worker.log.connect(self._say)
        self._install_worker.done.connect(self._on_installed)
        self._install_worker.start()

    def _on_installed(self, errors: list[str]) -> None:
        self.refresh()
        if not errors:
            self._say("Done.")
            return
        for error in errors:
            self._say(error)

    def _pick_dolphin(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select DolphinTool.exe", "", "DolphinTool (DolphinTool.exe)")
        if not path:
            return
        shutil.copy2(path, self.manager.tools_root / "DolphinTool.exe")
        self._say(f"Copied DolphinTool from {path}")
        self.refresh()

    # ---------------------------------------------------------- version check

    def _check_versions(self) -> None:
        if self._version_worker is not None and self._version_worker.isRunning():
            return
        self.check_button.setEnabled(False)
        self.check_button.setText("Checking...")
        self.upgrade_button.setVisible(False)
        self.upgrade_button.setEnabled(False)
        self._pending_upgrades.clear()
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
            current = effective_version(report.spec)
            self._say(f"{report.spec.label}: installed {current}, {report.detail}")
            if report.latest and not any(f.sha256 is None for f in report.spec.files):
                self._pending_upgrades.append((report.spec.key, report.latest))
        elif report.status in (Status.UNKNOWN, Status.MANUAL):
            cell.setForeground(theme.color("textThird"))
            # "could not check" on its own reads as a fault in the tool. Say why,
            # but only once: when GitHub is rate limiting, every remaining row
            # carries the same sentence and nine copies of it is not a log.
            if report.status is Status.UNKNOWN and report.detail not in self._reasons_logged:
                self._reasons_logged.add(report.detail)
                self._say(report.detail)
        else:
            cell.setForeground(theme.color("ok"))

    def _on_versions_done(self) -> None:
        self.check_button.setEnabled(True)
        self.check_button.setText("Check for updates")
        count = len(self._pending_upgrades)
        if count == 0:
            self.upgrade_button.setVisible(False)
            self._say("Everything checked is current. Double-click a row to open its release page.")
            return
        label = "tool" if count == 1 else "tools"
        self.upgrade_button.setText(f"Update {count} {label}")
        self.upgrade_button.setVisible(self.details_box.isChecked())
        self.upgrade_button.setEnabled(True)
        self._say(
            f"{count} {label} can be updated. Press Update {count} {label} to download "
            "them. Each file is hashed and the hash is kept next to the tool.")

    def _upgrade_behind(self) -> None:
        if not self._pending_upgrades:
            return
        if self._upgrade_worker is not None and self._upgrade_worker.isRunning():
            return
        updates = list(self._pending_upgrades)
        self.upgrade_button.setEnabled(False)
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self._say("Updating.")
        self._upgrade_worker = _UpgradeWorker(updates)
        self._upgrade_worker.log.connect(self._say)
        self._upgrade_worker.done.connect(self._on_upgraded)
        self._upgrade_worker.start()

    def _on_upgraded(self, errors: list[str]) -> None:
        self._pending_upgrades.clear()
        self.upgrade_button.setVisible(False)
        self.check_button.setEnabled(True)
        self.refresh()
        if not errors:
            self._say("Done.")
            return
        for error in errors:
            self._say(error)
