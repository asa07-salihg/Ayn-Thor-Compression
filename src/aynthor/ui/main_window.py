"""The window: a drop zone, a queue, and a bar along the bottom.

Why
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

Used by
    `app.run`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
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
from aynthor.core.esde import audit_folders, resolve_roms_root
from aynthor.core.formats import format_info, known_extensions
from aynthor.core.jobs import build_jobs
from aynthor.core.models import CompressionFormat, ConversionJob
from aynthor.core.presets import PRESETS
from aynthor.core.romlist import entries_to_queue, parse_list_file, summarize_list
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import ContentType, content_warnings, summarize_group
from aynthor.core.system import find_prod_keys
from aynthor.core.tools.manager import ToolsManager
from aynthor.ui import state, theme
from aynthor.ui.about_dialog import AboutDialog
from aynthor.ui.drop_zone import DropZone
from aynthor.ui.job_runner import JobRunner
from aynthor.ui.queue_view import QueueTable, human_size
from aynthor.ui.settings_dialog import SettingsDialog
from aynthor.ui.theme import Mode
from aynthor.ui.tools_dialog import ToolsDialog
from aynthor.ui.update_check import UpdateCheck

# List tokens that mean "leave this alone", not "no format chosen".
_NOT_CONVERTED = {"-", "Z64"}

# Which manifest entry a format needs before it can run.
_REQUIRED_TOOL = {
    CompressionFormat.CHD: "chdman",
    CompressionFormat.RVZ: "DolphinTool",
    CompressionFormat.CSO: "maxcso",
    CompressionFormat.NDS_TRIM: "ndstrim",
    CompressionFormat.NSZ: "nsz",
    CompressionFormat.SEVEN_ZIP: "7z",
    CompressionFormat.WUA: "rom-converto",
    CompressionFormat.DEC_3DS: "3ds-decryptor",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        # The version is in the title as well as in About, because a bug
        # report needs it and nobody opens About to find it.
        self.setWindowTitle(f"Ayn Thor Compression {__version__}")
        self.setWindowIcon(theme.app_icon())
        self.resize(1060, 700)
        self.setMinimumSize(760, 480)

        self.settings = FormatSettings()
        self.tools = ToolsManager()
        self._runner: JobRunner | None = None
        self._done = 0
        self._total = 0
        self._current_percent = 0
        self._saved_bytes = 0
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
        content_layout.addWidget(self.queue_card, stretch=4)
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

        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        title = QLabel("Ayn Thor Compression")
        title.setProperty("role", "title")
        subtitle = QLabel("CHD, RVZ, CSO, ZCCI, NSZ, 7z, WUA")
        subtitle.setProperty("role", "subtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        row.addLayout(title_column)
        row.addStretch()

        for label, slot, tip in (
            ("Settings", self._show_settings,
             "Output folder, and options for each format (Ctrl+,)"),
            ("Tools", self._show_tools, "Check and install the converter programs (Ctrl+T)"),
        ):
            button = QPushButton(label)
            button.setProperty("subtle", True)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            row.addWidget(button)

        self.more_button = QPushButton("More")
        self.more_button.setProperty("subtle", True)
        self.more_button.setToolTip("Appearance, documentation, about")
        self.more_button.setMenu(self._build_more_menu())
        row.addWidget(self.more_button)
        return header

    def _build_more_menu(self) -> QMenu:
        menu = QMenu(self)

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
        self.log_button.toggled.connect(self._toggle_log)
        row.addWidget(self.log_button)

        self.clear_button = QPushButton("Clear queue")
        self.clear_button.setProperty("subtle", True)
        self.clear_button.clicked.connect(self.queue.clear_queue)
        row.addWidget(self.clear_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        self.cancel_button.hide()
        row.addWidget(self.cancel_button)

        self.start_button = QPushButton("Start")
        self.start_button.setProperty("accent", True)
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start)
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

        self.drop_zone.set_compact(count > 0)
        self.queue_card.setVisible(count > 0)

        parts: list[str] = []
        if count:
            parts.append(f"{count} file{'s' if count != 1 else ''}")
            parts.append(human_size(self.queue.total_input_bytes()))
        if self._saved_bytes > 0:
            parts.append(f"saved {human_size(self._saved_bytes)}")
        self.summary_label.setText("   ".join(parts))

        self.start_button.setEnabled(count > 0 and not running)
        self.clear_button.setEnabled(count > 0 and not running)

    def _refresh_tool_warning(self) -> None:
        """Which formats in the queue need something that is not installed.

        Kept off the per-job path: it walks every row and probes the filesystem
        for each format, and nothing it depends on changes while a batch runs.
        """
        missing = {
            format_info(fmt).tool
            for fmt in self.queue.formats_in_queue()
            if self._tool_is_missing(fmt) and format_info(fmt)
        }
        if not missing:
            self.start_button.setToolTip("Convert everything in the queue (Ctrl+Enter)")
            return
        names = ", ".join(sorted(missing))
        self.start_button.setToolTip(
            f"Not installed yet: {names}. Open Tools to install them.")

    def _tool_is_missing(self, fmt: CompressionFormat) -> bool:
        if fmt == CompressionFormat.Z3DS:
            # Opening falls back to the built-in decoder, and compressing is
            # happy with either 3DS engine.
            return not (self.tools.is_available("rom-converto")
                        or self.tools.is_available("z3ds_compress"))
        key = _REQUIRED_TOOL.get(fmt)
        return bool(key) and not self.tools.is_available(key)

    def _pick_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(known_extensions()))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", "", f"ROMs and disc images ({patterns});;All files (*)")
        if paths:
            self._add([Path(p) for p in paths])

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add every ROM in a folder")
        if folder:
            self._add([Path(folder)])

    def _add(self, paths: list[Path]) -> None:
        extensions = known_extensions()
        files: list[Path] = []
        for path in paths:
            if path.is_dir():
                found = sorted(p for p in path.rglob("*")
                               if p.is_file() and p.suffix.lower() in extensions)
                if not found:
                    self._log(f"No recognised ROMs in {path}")
                files.extend(found)
            elif path.is_file():
                files.append(path)

        added, skipped = self.queue.add_paths(files, self.settings)
        if added:
            self._log(f"Added {added} file{'s' if added != 1 else ''}.")
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

        jobs = build_jobs(self.queue.queue_items(), self.settings)
        if not jobs:
            self.log_button.setChecked(True)
            self._log("Nothing to do: every output already exists, and 'If the output "
                      "exists' is set to Skip. Change it in Settings to run them anyway.")
            return

        if self.settings.delete_source:
            confirm = QMessageBox.warning(
                self, "Delete sources",
                f"'Delete the source after converting' is on.\n\n"
                f"{len(jobs)} original file(s) will be removed once they convert "
                f"successfully.\n\nContinue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return

        self._done = 0
        self._total = len(jobs)
        self._current_percent = 0
        self._saved_bytes = 0

        self.progress.setValue(0)
        self.progress.show()
        self.cancel_button.show()
        self.start_button.hide()
        self.clear_button.setEnabled(False)

        self._runner = JobRunner(jobs)
        self._runner.log.connect(self._log)
        self._runner.job_started.connect(self._on_job_started)
        self._runner.job_progress.connect(self._on_job_progress)
        self._runner.job_finished.connect(self._on_job_finished)
        self._runner.finished.connect(self._on_all_finished)
        self._runner.start()

    def _cancel(self) -> None:
        if self._runner is not None and self._runner.isRunning():
            self._runner.cancel()
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Stopping")

    def _on_job_started(self, row: int) -> None:
        self._current_percent = 0
        self.queue.update_status(row, "Running")
        self.queue.scrollToItem(self.queue.item(row, 0))

    def _on_job_progress(self, row: int, percent: int) -> None:
        self._current_percent = percent
        self.queue.update_status(row, f"{percent}%")
        self._update_progress()

    def _on_job_finished(self, row: int, job: ConversionJob, ok: bool, message: str) -> None:
        self._done += 1
        self._current_percent = 0
        self._update_progress()
        self.queue.update_status(row, "Done" if ok else "Failed", message)
        if ok:
            self.queue.record_result(row, job.input_size, job.output_size)
            if job.output_size:
                self._saved_bytes += job.input_size - job.output_size
        else:
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
        state.save_mode(mode)

    def _log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
