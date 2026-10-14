"""The window: a drop zone, a queue, and a bar along the bottom.

One screen. The previous design had four permanent panels, and three of
them were showing something the user was not looking at: a format list they
had already decided about, an options panel they consult once a month, and
a log that only matters when something fails.

So: the drop target is the largest thing on screen until there is something
in the queue, the queue is everything after that, and the bar at the bottom
holds the only two facts that stay true throughout a run (how much is
queued, how much has been saved) plus the one button that starts it.
Settings and the log are one click away and take no space until asked for.

The format lives on the row, set by auto-detection and changed from the
row's own context menu. There is no global "selected format" anywhere,
which is what removed the retargeting rules the old design needed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aynthor import CHANGELOG_URL, __version__
from aynthor.core.batch import Outcome
from aynthor.core.device import com_thread, open_target
from aynthor.core.esde import audit_folders, resolve_roms_root
from aynthor.core.explain import Fix, explain_failure
from aynthor.core.formats import file_dialog_filter, format_info, known_extensions
from aynthor.core.groups import discover_folders
from aynthor.core.intake import folder_label
from aynthor.core.jobs import build_jobs
from aynthor.core.models import CompressionFormat, ConversionJob, QueueItem
from aynthor.core.preflight import Problem, check_queue, missing_programs
from aynthor.core.presets import PRESETS
from aynthor.core.romlist import entries_to_queue, parse_list_file, summarize_list
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import ContentType, content_warnings, summarize_group
from aynthor.core.system import find_prod_keys
from aynthor.core.tools.manager import ToolsManager
from aynthor.core.tools.manifest import SPECS_BY_KEY
from aynthor.core.unpack import rom_files
from aynthor.ui import icons, state, theme
from aynthor.ui.about_dialog import AboutDialog
from aynthor.ui.destination import DestinationDialog
from aynthor.ui.destination import describe as describe_destination
from aynthor.ui.drop_zone import DropZone
from aynthor.ui.failure_dialog import FailureDialog
from aynthor.ui.finish_dialog import FinishDialog
from aynthor.ui.job_runner import JobRunner
from aynthor.ui.preflight_dialog import PreflightDialog
from aynthor.ui.queue_view import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SENDING,
    STATUS_SKIPPED,
    STATUS_WORKING,
    QueueTable,
    human_size,
)
from aynthor.ui.settings_dialog import SettingsDialog
from aynthor.ui.theme import Mode
from aynthor.ui.tools_dialog import ToolsDialog
from aynthor.ui.update_check import UpdateCheck
from aynthor.ui.welcome_dialog import WelcomeDialog

# List tokens that mean "leave this alone", not "no format chosen".
_NOT_CONVERTED = {"-", "Z64"}


def _existing_folder(path: Path) -> Path | None:
    """The nearest folder that exists, so Open folder never opens nothing."""
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # The version is in the title as well as in About, because a bug
        # report needs it and nobody opens About to find it.
        self.setWindowTitle(f"Ayn Thor Compression {__version__}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1060, 700)
        self.setMinimumSize(800, 500)

        self.settings = FormatSettings()
        self.tools = ToolsManager()
        self._runner: JobRunner | None = None
        self._done = 0
        self._total = 0
        self._current_percent = 0
        self._saved_bytes = 0
        self._ok_count = 0
        self._failed_count = 0
        self._skipped_count = 0
        self._sending: set[int] = set()
        self._cancelled = False
        self._last_output: Path | None = None
        self._finish_dialog: FinishDialog | None = None
        self._icon_buttons: list[tuple[QPushButton, str, str]] = []
        self._update_check = UpdateCheck(self)

        self._build()
        self._restore_session()

    # ---------------------------------------------------------------- building

    def _build(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 10, 14, 12)
        content_layout.setSpacing(10)

        self.drop_zone = DropZone()
        self.drop_zone.paths_dropped.connect(self._add)
        self.drop_zone.add_files.connect(self._pick_files)
        self.drop_zone.add_folder.connect(self._pick_folder)
        self.drop_zone.import_list.connect(self._import_list)
        # Stretches while the queue is empty, so an empty window is one large
        # drop target rather than a small one above an empty table.
        content_layout.addWidget(self.drop_zone, stretch=1)

        self.queue_card = self._build_queue_card()
        self.drop_zone.expand_all.connect(self.queue.expandAll)
        self.drop_zone.collapse_all.connect(self.queue.collapseAll)
        content_layout.addWidget(self.queue_card, stretch=4)
        self.queue.paths_dropped.connect(self._dropped_on_queue)
        # Anywhere in the window takes a drop: the log, the header, the gap
        # between the buttons. Widgets that take drops themselves (the drop
        # zone, the queue) get them first.
        self.setAcceptDrops(True)
        layout.addWidget(content, stretch=1)

        layout.addWidget(self._build_log())
        layout.addWidget(self._build_bottom_bar())

        self.setCentralWidget(root)
        self._install_shortcuts()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setProperty("role", "bar")
        row = QHBoxLayout(header)
        row.setContentsMargins(14, 10, 10, 10)
        row.setSpacing(8)

        self.logo = QLabel()
        self.logo.setPixmap(icons.logo(40, self.devicePixelRatioF()))
        row.addWidget(self.logo)
        row.addSpacing(4)

        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("Ayn Thor Compression")
        title.setProperty("role", "title")
        subtitle = QLabel("Shrink your games and put them where your handheld looks for them")
        subtitle.setProperty("role", "subtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        row.addLayout(title_column)
        row.addStretch()

        for label, slot, tip, icon_name in (
            ("Settings", self._show_settings,
             "Where finished games go, and advanced options (Ctrl+,)", "settings"),
            ("Tools", self._show_tools,
             "The free programs that do the converting (Ctrl+T)", "package"),
        ):
            button = QPushButton(label)
            button.setProperty("subtle", True)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            self._with_icon(button, icon_name)
            row.addWidget(button)

        self.more_button = QPushButton("More")
        self.more_button.setProperty("subtle", True)
        self.more_button.setToolTip("Appearance, documentation, about")
        self.more_button.setMenu(self._build_more_menu())
        row.addWidget(self.more_button)
        return header

    def _build_more_menu(self) -> QMenu:
        menu = QMenu(self)

        guide = QAction("Setup guide...", self)
        guide.setToolTip("Install the programs, choose where games go, find Switch keys.")
        guide.triggered.connect(self.show_welcome)
        menu.addAction(guide)
        menu.addSeparator()

        appearance = menu.addMenu("Appearance")
        group = QActionGroup(self)
        group.setExclusive(True)
        self.theme_actions: dict[Mode, QAction] = {}
        for label, mode in (("Match Windows", Mode.SYSTEM),
                            ("Light", Mode.LIGHT),
                            ("Dark", Mode.DARK)):
            action = QAction(label, self, checkable=True)
            action.triggered.connect(lambda _c, m=mode: self._set_theme(m))
            group.addAction(action)
            appearance.addAction(action)
            self.theme_actions[mode] = action

        menu.addSeparator()
        open_tools = QAction("Open tools folder", self)
        open_tools.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.tools.tools_root))))
        menu.addAction(open_tools)

        changelog = QAction(f"What's new in {__version__}", self)
        changelog.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(CHANGELOG_URL)))
        menu.addAction(changelog)

        check_updates = QAction("Check for updates", self)
        check_updates.setToolTip(
            "Ask GitHub whether a newer release exists. Nothing is downloaded "
            "or installed without asking.")
        check_updates.triggered.connect(self._update_check.run)
        menu.addAction(check_updates)

        about = QAction("About", self)
        about.triggered.connect(lambda: AboutDialog(self).exec())
        menu.addAction(about)
        return menu

    def _build_queue_card(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(1, 1, 1, 1)

        self.queue = QueueTable()
        self.queue.queue_changed.connect(self._on_queue_changed)
        self.queue.settings_requested.connect(self._show_settings)
        self.queue.failure_clicked.connect(self._explain_failure)
        layout.addWidget(self.queue)
        return card

    def _build_log(self) -> QWidget:
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(150)
        self.log_view.setMaximumBlockCount(5000)  # a full SD card is a long log
        self.log_view.hide()
        return self.log_view

    def _build_bottom_bar(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("role", "bar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 9, 14, 9)
        row.setSpacing(10)

        self.summary_label = QLabel()
        self.summary_label.setProperty("role", "second")
        row.addWidget(self.summary_label)

        self.skipped_button = QPushButton()
        self.skipped_button.setProperty("subtle", True)
        self.skipped_button.setToolTip("Some files were not added. Click to see why.")
        self.skipped_button.clicked.connect(lambda: self.log_button.setChecked(True))
        self._with_icon(self.skipped_button, "alert", "warn")
        self.skipped_button.hide()
        row.addWidget(self.skipped_button)

        self.destination_button = QPushButton()
        self.destination_button.setProperty("pill", True)
        self.destination_button.setToolTip("Where finished games go. Click to change it.")
        self.destination_button.clicked.connect(lambda: self._choose_destination())
        self._with_icon(self.destination_button, "folder")
        row.addWidget(self.destination_button)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(190)
        self.progress.hide()
        row.addWidget(self.progress)
        row.addStretch()

        self.log_button = QPushButton("Log")
        self.log_button.setProperty("subtle", True)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Show what the converters are printing (Ctrl+L)")
        self._with_icon(self.log_button, "log")
        self.log_button.toggled.connect(self._toggle_log)
        row.addWidget(self.log_button)

        self.clear_button = QPushButton("Clear queue")
        self.clear_button.setProperty("subtle", True)
        self.clear_button.clicked.connect(self.queue.clear_queue)
        self.clear_button.clicked.connect(self.skipped_button.hide)
        self._with_icon(self.clear_button, "trash")
        row.addWidget(self.clear_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self._with_icon(self.cancel_button, "stop")
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)

        self.start_button = QPushButton("Start")
        self.start_button.setProperty("accent", True)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
        self._with_icon(self.start_button, "play", "accentText")
        row.addWidget(self.start_button)
        return bar

    def _install_shortcuts(self) -> None:
        for keys, slot in (
            ("Ctrl+O", self._pick_files),
            ("Ctrl+Shift+O", self._pick_folder),
            ("Ctrl+I", self._import_list),
            ("Ctrl+,", self._show_settings),
            ("Ctrl+T", self._show_tools),
            ("Ctrl+Return", self._start),
        ):
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(slot)
            self.addAction(action)

        toggle_log = QAction(self)
        toggle_log.setShortcut(QKeySequence("Ctrl+L"))
        toggle_log.triggered.connect(self.log_button.toggle)
        self.addAction(toggle_log)

        remove = QAction(self)
        remove.setShortcut(QKeySequence.StandardKey.Delete)
        remove.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove.triggered.connect(self.queue.remove_selected)
        self.queue.addAction(remove)

    # --------------------------------------------------------------- lifecycle

    def _restore_session(self) -> None:
        state.load_into(self.settings)
        state.load_presets_into(PRESETS)

        keys = Path(self.settings.keys_path) if self.settings.keys_path else find_prod_keys()
        if keys and keys.is_file():
            self.settings.keys_path = str(keys)
            # The folder, not the file: the log pane is what people paste into
            # bug reports, and where somebody keeps their console keys is not
            # a detail they should have to notice they are sharing.
            self._log(f"Switch keys: found in {keys.parent.name or keys.parent}")

        self.theme_actions[state.load_mode()].setChecked(True)

        geometry = state.restore_geometry()
        if geometry:
            self.restoreGeometry(geometry)

        self.queue.apply_settings(self.settings)
        self._refresh_summary()
        self._refresh_tool_warning()

    def maybe_show_welcome(self) -> None:
        """Open the setup guide once, after the window is on screen."""
        if not state.welcome_done():
            QTimer.singleShot(0, self.show_welcome)

    def show_welcome(self) -> None:
        WelcomeDialog(self.settings, self.tools, self).exec()
        state.save(self.settings, self.saveGeometry())
        self.tools.refresh()
        self.queue.apply_settings(self.settings)
        self._refresh_summary()
        self._refresh_tool_warning()

    def closeEvent(self, event) -> None:
        if self._runner is not None and self._runner.isRunning():
            answer = QMessageBox.question(
                self, "Still converting",
                "A conversion is still running. Stop it and close?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._runner.cancel()
            self._runner.wait(5000)

        state.save(self.settings, self.saveGeometry())
        state.save_presets(PRESETS)
        super().closeEvent(event)

    # ------------------------------------------------------------------- queue

    def _on_queue_changed(self) -> None:
        """The queue gained, lost or re-targeted rows."""
        self._refresh_summary()
        self._refresh_tool_warning()

    def _refresh_summary(self) -> None:
        """Cheap enough to call after every finished job."""
        count = self.queue.rowCount()
        running = self._runner is not None and self._runner.isRunning()
        populated = self.queue.topLevelItemCount() > 0

        self.drop_zone.set_compact(populated)
        self.queue_card.setVisible(populated)

        parts: list[str] = []
        if running and self._total:
            parts.append(f"Working on {min(self._done + 1, self._total)} of {self._total}")
        elif count:
            parts.append(f"{count} file{'s' if count != 1 else ''}")
            parts.append(human_size(self.queue.total_input_bytes()))
        if self._saved_bytes > 0:
            parts.append(f"saved {human_size(self._saved_bytes)}")
        self.summary_label.setText("   ".join(parts))

        self.start_button.setEnabled(count > 0 and not running)
        self.clear_button.setEnabled(populated and not running)
        self._refresh_destination()

    def _refresh_destination(self) -> None:
        """Say where finished games will go, all the time, not only in Settings."""
        text = describe_destination(self.settings)
        metrics = self.destination_button.fontMetrics()
        self.destination_button.setText(
            metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, 380))
        self.destination_button.setToolTip(f"{text}\nClick to change where games go.")
        name = "handheld" if self.settings.device is not None else "folder"
        self._icon_buttons = [(b, name if b is self.destination_button else n, c)
                              for b, n, c in self._icon_buttons]
        self.destination_button.setIcon(icons.icon(name))
        self.destination_button.setProperty("device", self.settings.device is not None)
        theme.restyle(self.destination_button)

    def _refresh_tool_warning(self) -> None:
        """Which programs the queue needs that are not installed.

        Kept off the per-job path: it walks every row and probes the filesystem
        for each program, and nothing it depends on changes while a batch runs.
        """
        missing = missing_programs(self.queue.queue_items(), self.tools.is_available)
        if not missing:
            self.start_button.setToolTip("Convert everything in the queue (Ctrl+Enter)")
            return
        names = ", ".join(sorted(
            SPECS_BY_KEY[key].label if key in SPECS_BY_KEY else key for key in missing))
        self.start_button.setToolTip(
            f"Not installed yet: {names}. Press Start and the app offers to install them.")

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", "", file_dialog_filter())
        if paths:
            self._add([Path(p) for p in paths])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder")
        if folder:
            self._add([Path(folder)])

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if QueueTable.dropped_paths(event):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [p for p in QueueTable.dropped_paths(event) if p.exists()]
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if paths:
            self._add(paths)

    def _dropped_on_queue(self, paths: list[Path], folder) -> None:
        before = self.queue.last_id()
        self._add(paths)
        if folder is not None and all(p.is_file() for p in paths):
            joined = self.queue.adopt(folder, before)
            if joined:
                self._log(f"Joined {joined} file{'s' if joined != 1 else ''} to "
                          f"{folder.text(QueueTable.COL_FILE)}.")

    def _add(self, paths: list[Path]) -> None:
        extensions = known_extensions()
        files: list[Path] = []
        labels: dict[Path, str] = {}
        folders_added = 0
        for path in paths:
            if path.is_dir():
                folders_added += self.queue.add_folder_tree(
                    path, discover_folders(path), self.settings)
                found = rom_files(sorted(
                    p for p in path.rglob("*")
                    if p.is_file() and p.suffix.lower() in extensions))
                for found_file in found:
                    files.append(found_file)
                    labels[found_file] = folder_label(path, found_file)
            elif path.is_file():
                files.append(path)

        added, skipped = self.queue.add_paths(files, self.settings, labels)
        self.skipped_button.setText(
            f"{len(skipped)} skipped" if skipped else "")
        self.skipped_button.setVisible(bool(skipped))
        pruned = self.queue.apply_empty_folder_setting()
        folders_added = max(0, folders_added - pruned)
        if added:
            self._log(f"Added {added} file{'s' if added != 1 else ''}.")
        if folders_added:
            self._log(
                f"Added {folders_added} folder{'s' if folders_added != 1 else ''}.")
        elif not added and not skipped and not files:
            if any(p.is_dir() for p in paths) and not self.settings.show_empty_folders:
                self._log(
                    "No ROMs found. Empty folders are hidden; turn them on in "
                    "Settings > General.")
            else:
                self._log(f"No recognised ROMs or folders in {paths[0]}" if paths else
                          "Nothing to add.")
        for reason in skipped:
            self._log(f"Skipped {reason}")
        if files and not added and not skipped:
            self._log("Nothing added: those files are already queued.")
        self._refresh_summary()

    # ------------------------------------------------------------ list import

    def _import_list(self) -> None:
        """Load a list file, match it against a ROMs folder, queue what it finds."""
        list_path, _ = QFileDialog.getOpenFileName(
            self, "Choose a list file", "", "Text and Markdown (*.txt *.md);;All files (*)")
        if not list_path:
            return
        roms_root = QFileDialog.getExistingDirectory(self, "Where are the ROMs?")
        if not roms_root:
            return

        entries = parse_list_file(Path(list_path))
        if not entries:
            QMessageBox.warning(
                self, "Nothing to import",
                "No entries were found in that file.\n\n"
                "A line should read either\n"
                "    Chrono Cross -> psx -> CHD\n"
                "or\n"
                "    | Chrono Cross | psx | CHD |")
            return

        # An import is the one action that reports more than it shows, so the
        # log opens with it rather than leaving the findings unread.
        self.log_button.setChecked(True)
        root = resolve_roms_root(Path(roms_root))
        self._log(f"ROMs root: {root}")

        compressible = self._report_list_contents(entries, root)
        matched = entries_to_queue(entries, root)

        added = self.queue.add_from_list(
            [(m.path, m.format, m.options) for m in matched], self.settings)
        self._log(f"Matched and queued {added} file{'s' if added != 1 else ''}.")

        self._report_switch_sets(matched)
        if added < compressible:
            self._log("Some entries had no match. Check the folder names and file names.")
        self._refresh_summary()

    def _report_list_contents(self, entries: list, root: Path) -> int:
        """Log which platform folders were found, and how much is convertible.

        Returns the number of entries that should end up queued, which is what
        the caller compares the result against to spot silent misses.
        """
        wanted = {e.platform for e in entries if e.target_format not in _NOT_CONVERTED}
        audit = audit_folders(root, wanted)
        if audit.found:
            found = ", ".join(f"{p} ({', '.join(v)})" for p, v in sorted(audit.found.items()))
            self._log(f"Found folders: {found}")
        if audit.missing:
            self._log("No folder for: " + ", ".join(sorted(audit.missing)))

        summary = summarize_list(entries)
        skipped = sum(count for fmt, count in summary.items() if fmt in _NOT_CONVERTED)
        compressible = len(entries) - skipped
        self._log(f"List has {len(entries)} entries, {compressible} of them compressible.")
        return compressible

    def _report_switch_sets(self, matched: list) -> None:
        """Warn about a Switch title queued without its base game.

        An update or DLC installs as nothing without the base, and the failure
        happens on the console long after the compression looked fine.
        """
        sets: dict[str, list[ContentType]] = {}
        for entry in matched:
            if entry.platform != "switch":
                continue
            game = entry.options.get("game_group", entry.path.stem)
            sets.setdefault(game, []).append(
                ContentType(entry.options.get("content_type", ContentType.BASE.value)))

        for game, parts in sorted(sets.items()):
            if len(parts) > 1:
                self._log(f"  {game}: {summarize_group(parts)}")
            for warning in content_warnings(parts):
                self._log(f"  Warning, {game}: {warning}")

    # ---------------------------------------------------------------- running

    def _start(self) -> None:
        if self.queue.rowCount() == 0 or not self.start_button.isEnabled():
            return

        queue = self.queue.queue_items()
        skipped = self._preflight(queue)
        if skipped is None:
            return
        for row in skipped:
            self.queue.update_status(row, STATUS_SKIPPED, "Left out of this run.")

        jobs = build_jobs([(row, item) for row, item in queue if row not in skipped],
                          self.settings)
        if not jobs:
            self.log_button.setChecked(True)
            self._log("Nothing left to run: every file was skipped." if skipped
                      else "Nothing to run.")
            return

        self._done = 0
        self._total = len(jobs)
        self._current_percent = 0
        self._saved_bytes = 0
        self._ok_count = 0
        self._failed_count = 0
        self._skipped_count = len(skipped)
        self._cancelled = False
        self._last_output = None

        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.start_button.hide()
        self.clear_button.setEnabled(False)

        self._sending.clear()
        self._runner = JobRunner(jobs, policy=self.settings.on_conflict,
                                 device=self.settings.device)
        self._runner.log.connect(self._log)
        self._runner.job_started.connect(self._on_job_started)
        self._runner.job_progress.connect(self._on_job_progress)
        self._runner.job_stage.connect(self._on_job_stage)
        self._runner.job_finished.connect(self._on_job_finished)
        self._runner.finished.connect(self._on_all_finished)
        self._runner.start()
        self._refresh_summary()

    def _preflight(self, queue: list[tuple[int, QueueItem]]) -> set[int] | None:
        """Rows to leave out of this run, or None when the user cancelled."""
        problems = check_queue(queue, self.settings, is_available=self.tools.is_available,
                               device_ready=self._device_ready)
        if not problems and not self.settings.delete_source:
            return set()
        dialog = PreflightDialog(problems, self.settings, self._recheck,
                                 use_keys=self._use_keys,
                                 deletes_sources=self.settings.delete_source, parent=self)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self.tools.refresh()
        self._refresh_tool_warning()
        return dialog.skipped_rows() if accepted else None

    def _recheck(self) -> list[Problem]:
        self.tools.refresh()
        return check_queue(self.queue.queue_items(), self.settings,
                           is_available=self.tools.is_available,
                           device_ready=self._device_ready)

    def _device_ready(self) -> str:
        """"" when the chosen device opens and has its storage, or why not.
        Runs on this thread: it is a second or two of USB, once, before Start."""
        target = self.settings.device
        if target is None:
            return ""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            with com_thread() as runtime, open_target(target, runtime):
                return ""
        except OSError as exc:
            return str(exc)
        finally:
            QApplication.restoreOverrideCursor()

    def _use_keys(self, path: Path) -> None:
        """Point every Switch row, and every one added later, at this prod.keys.

        Rows carry the NSZ page's own `keys_path`, which wins over the general
        setting, so changing only the general one left a stale path in place.
        """
        self.settings.keys_path = str(path)
        self.settings.options.setdefault(CompressionFormat.NSZ, {})["keys_path"] = str(path)
        self.queue.apply_format_options(CompressionFormat.NSZ, {"keys_path": str(path)})
        self._log(f"Switch keys: using the file in {path.parent.name or path.parent}")

    def _cancel(self) -> None:
        if self._runner is not None and self._runner.isRunning():
            self._cancelled = True
            self._runner.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Stopping")

    def _on_job_started(self, row: int) -> None:
        self._current_percent = 0
        self.queue.update_status(row, STATUS_WORKING)
        node = self.queue.file_at(row)
        if node is not None:
            self.queue.scrollToItem(node)

    def _on_job_progress(self, row: int, percent: int) -> None:
        self._current_percent = percent
        prefix = f"{STATUS_SENDING} " if row in self._sending else ""
        self.queue.update_status(row, f"{prefix}{percent}%")
        self._update_progress()

    def _on_job_stage(self, row: int, stage: str) -> None:
        self._sending.add(row)
        self._log(f"  {stage}…")

    def _on_job_finished(self, row: int, job: ConversionJob, outcome: str, message: str) -> None:
        self._done += 1
        self._current_percent = 0
        self._sending.discard(row)
        self._update_progress()
        ok = outcome != Outcome.FAILED.value
        if outcome == Outcome.SKIPPED.value:
            self._skipped_count += 1
            self.queue.update_status(row, STATUS_SKIPPED, message)
            self._log(f"SKIPPED  {job.input_path.name}: {message}")
            self._refresh_summary()
            return
        self.queue.update_status(row, STATUS_DONE if ok else STATUS_FAILED, message)
        if ok:
            self._ok_count += 1
            self._last_output = job.output_path
            self.queue.record_result(row, job.input_size, job.output_size)
            if job.output_size:
                self._saved_bytes += job.input_size - job.output_size
        else:
            self._failed_count += 1
            # A failure is the one thing worth interrupting for.
            self.log_button.setChecked(True)
        self._log(f"{'OK' if ok else 'FAILED'}  {job.input_path.name}: {message}")
        self._refresh_summary()

    def _update_progress(self) -> None:
        if not self._total:
            return
        self.progress.setValue(int((self._done * 100 + self._current_percent) / self._total))

    def _on_all_finished(self) -> None:
        self.progress.hide()
        self.cancel_button.hide()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.start_button.show()
        self._refresh_summary()
        if self._saved_bytes > 0:
            self._log(f"Finished. Total saved: {human_size(self._saved_bytes)}")
        else:
            self._log("Finished.")
        if not self._cancelled:
            # Flashes the taskbar button when the window is behind something
            # else; a long batch is exactly when people switch away.
            QApplication.alert(self)
            self._show_finish()

    def _show_finish(self) -> None:
        dialog = FinishDialog(
            self._ok_count, self._failed_count, self._skipped_count,
            max(0, self._saved_bytes), self._results_folder(), self)
        dialog.finished.connect(lambda _code, d=dialog: self._after_finish(d))
        self._finish_dialog = dialog
        dialog.open()

    def _after_finish(self, dialog: FinishDialog) -> None:
        if dialog.choice == FinishDialog.OPEN_FOLDER:
            self._open_folder(self._results_folder())
        elif dialog.choice == FinishDialog.SHOW_FAILURES:
            failed = self.queue.failed_ids()
            node = self.queue.file_at(failed[0]) if failed else None
            if node is not None:
                self.queue.scrollToItem(node)
                self.queue.setCurrentItem(node)
                self._explain_failure(failed[0])

    def _results_folder(self) -> Path | None:
        """The folder a user would open to find what this run wrote. None for a
        device, which has no folder Windows can open by path."""
        if self.settings.device is not None:
            return None
        if self.settings.esde_root:
            return resolve_roms_root(Path(self.settings.esde_root))
        if self.settings.output_dir:
            return Path(self.settings.output_dir)
        if self._last_output is not None:
            return _existing_folder(self._last_output.parent)
        return None

    @staticmethod
    def _open_folder(folder: Path | None) -> None:
        if folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _explain_failure(self, item_id: int) -> None:
        message = self.queue.failure_message(item_id)
        if message is None:
            return
        node = self.queue.file_at(item_id)
        name = node.text(self.queue.COL_FILE) if node is not None else ""
        dialog = FailureDialog(name, explain_failure(message), self)
        dialog.exec()
        self._apply_fix(dialog.chosen_fix, item_id)

    def _apply_fix(self, fix: Fix | None, item_id: int) -> None:
        if fix is Fix.OPEN_TOOLS:
            self._show_tools()
        elif fix is Fix.CHOOSE_KEYS:
            path, _ = QFileDialog.getOpenFileName(
                self, "Choose prod.keys", "", "Switch keys (*.keys);;All files (*)")
            if path:
                self._use_keys(Path(path))
        elif fix is Fix.OPEN_FOLDER:
            output = self.queue.output_of(item_id)
            self._open_folder(
                _existing_folder(output.parent) if output else self._results_folder())
        elif fix is Fix.GET_7ZIP:
            QDesktopServices.openUrl(QUrl("https://www.7-zip.org/"))

    # -------------------------------------------------------------------- misc

    def _show_settings(self, fmt: CompressionFormat | None = None) -> None:
        dialog = SettingsDialog(self.settings, PRESETS, self)
        if isinstance(fmt, CompressionFormat):
            dialog.show_format(fmt)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        self.settings = dialog.result_settings()
        if dialog.presets_touched:
            # Presets decide what a file becomes when it is added, so an edit
            # affects the next drop rather than what is already queued.
            self._log("Platform presets updated. Files added from now on will use them.")
        self.queue.apply_settings(self.settings)
        # Only the pages the user actually edited are pushed onto queued rows.
        # Applying all of them would wipe the per-platform values auto-detection
        # worked out, such as the codec a PS2 row needs for NetherSX2.
        for changed in dialog.changed_formats():
            rows = self.queue.apply_format_options(changed, self.settings.for_format(changed))
            if rows:
                info = format_info(changed)
                self._log(f"Applied {info.label} settings to {rows} queued row(s).")
        self._refresh_summary()

    def _choose_destination(self) -> None:
        dialog = DestinationDialog(self.settings, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.queue.apply_settings(self.settings)
        self._log(describe_destination(self.settings) + ".")
        self._refresh_summary()

    def _show_tools(self) -> None:
        ToolsDialog(self).exec()
        # Something may have been installed while that was open.
        self.tools.refresh()
        self._refresh_summary()
        self._refresh_tool_warning()

    def _toggle_log(self, visible: bool) -> None:
        self.log_view.setVisible(visible)

    def _set_theme(self, mode: Mode) -> None:
        app = QApplication.instance()
        if app is None:
            return
        theme.apply_theme(app, mode)
        self.queue.refresh_colours()
        self._apply_icons()
        state.save_mode(mode)

    def _with_icon(self, button: QPushButton, name: str, colour: str = "text") -> None:
        """Give a button its icon, and remember it so a theme change recolours it."""
        self._icon_buttons.append((button, name, colour))
        button.setIcon(icons.icon(name, colour))
        button.setIconSize(QSize(16, 16))

    def _apply_icons(self) -> None:
        for button, name, colour in self._icon_buttons:
            button.setIcon(icons.icon(name, colour))
        self.drop_zone.apply_icons()

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
