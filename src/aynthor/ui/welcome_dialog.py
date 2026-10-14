"""The setup guide: get the programs, pick where games go, find the Switch keys.

A first launch used to open on an empty window with nothing installed.
Someone who had never heard of chdman added their games, pressed Start,
and watched every row turn red. The three things a first batch needs (the
converter programs, a place to put the results, and `prod.keys` for
Switch) are asked for here, once, in that order, and every step can be
skipped.

The destination is a ROMs folder, wherever it lives: on an SD card in a
card reader, on a USB drive, or on this computer to copy over later. Each
console's folder inside it is created when the first game for it is
written. The only other choice is to keep results beside the originals.
A handheld on a USB cable appears as a media device rather than a drive
letter, and nothing can write to it with ordinary file calls, so the
guide says so instead of letting the user find out.

ES-DE folder layout: `core.esde`.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QCloseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.esde import resolve_roms_root
from aynthor.core.settings import FormatSettings
from aynthor.core.system import find_prod_keys
from aynthor.core.tools.manager import ToolsManager
from aynthor.ui import icons, state, theme
from aynthor.ui.destination import (
    DevicePicker,
    FolderLister,
    Scanner,
    list_folders,
    scan_devices,
)
from aynthor.ui.tools_dialog import InstallWorker


class Destination(str, Enum):
    DEVICE = "device"
    ROMS = "roms"
    BESIDE = "beside"


class _StepBar(QWidget):
    """One short bar per step, filled up to the current one."""

    def __init__(self, count: int) -> None:
        super().__init__()
        self.count = count
        self.current = 0
        self.setFixedSize(count * 30, 10)

    def set_current(self, index: int) -> None:
        self.current = index
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(self.count):
            painter.setBrush(theme.color("accent" if index <= self.current else "subtleHover"))
            painter.drawRoundedRect(QRectF(index * 30, 2, 24, 6), 3, 3)


class WelcomeDialog(QDialog):
    def __init__(self, settings: FormatSettings, tools: ToolsManager,
                 parent: QWidget | None = None, *,
                 scanner: Scanner = scan_devices, lister: FolderLister = list_folders) -> None:
        super().__init__(parent)
        self._scanner = scanner
        self._lister = lister
        self.setWindowTitle("Setup guide")
        self.setMinimumWidth(620)
        self.settings = settings
        self.tools = tools
        self._roms: Path | None = None
        self._keys: Path | None = None
        self._worker: InstallWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        self.step_label = QLabel()
        self.step_label.setProperty("role", "third")
        self.step_bar = _StepBar(3)
        progress = QHBoxLayout()
        progress.setSpacing(10)
        progress.addWidget(self.step_bar)
        progress.addWidget(self.step_label)
        progress.addStretch()
        layout.addLayout(progress)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._programs_page())
        self.pages.addWidget(self._destination_page())
        self.pages.addWidget(self._keys_page())
        layout.addWidget(self.pages, stretch=1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.skip_button = QPushButton("Skip setup")
        self.skip_button.setProperty("subtle", True)
        self.skip_button.setToolTip("You can open this guide again from More > Setup guide.")
        self.skip_button.clicked.connect(self.reject)
        buttons.addWidget(self.skip_button)
        buttons.addStretch()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back)
        buttons.addWidget(self.back_button)
        self.next_button = QPushButton("Next")
        self.next_button.setProperty("accent", True)
        self.next_button.setDefault(True)
        self.next_button.clicked.connect(self.next_page)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self._show(0)

    # ------------------------------------------------------------------ pages

    def _page(self, title: str, intro: str, icon_name: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        body = QVBoxLayout(page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel()
        badge.setPixmap(icons.pixmap(icon_name, "accent", 32, self.devicePixelRatioF()))
        top.addWidget(badge)
        heading = QLabel(title)
        heading.setProperty("role", "title")
        top.addWidget(heading, stretch=1)
        body.addLayout(top)
        if intro:
            text = QLabel(intro)
            text.setWordWrap(True)
            text.setProperty("role", "second")
            body.addWidget(text)
        return page, body

    def _programs_page(self) -> QWidget:
        page, body = self._page(
            "Get the converter programs",
            "This app doesn't convert anything itself. It runs free programs made by "
            "each format's own project. They are downloaded once, from those "
            "projects, and checked against a known fingerprint before they are used.",
            "download")
        self.programs_status = QLabel()
        self.programs_status.setWordWrap(True)
        body.addWidget(self.programs_status)
        self.install_button = QPushButton("Install programs")
        self.install_button.setProperty("accent", True)
        self.install_button.clicked.connect(self._install)
        body.addWidget(self.install_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.install_log = QPlainTextEdit()
        self.install_log.setObjectName("log")
        self.install_log.setReadOnly(True)
        self.install_log.setMaximumHeight(120)
        self.install_log.hide()
        body.addWidget(self.install_log)
        body.addStretch()
        self._refresh_programs()
        return page

    def _destination_page(self) -> QWidget:
        page, body = self._page("Where should finished games go?", "", "folder")
        self.destination_group = QButtonGroup(self)

        self.device_radio = QRadioButton("Straight onto my handheld, over USB")
        self.device_picker = DevicePicker(self._scanner, self._lister, self.settings.device)
        self.device_picker.changed.connect(self._update_next)
        device_box = self._choice(
            self.device_radio, "", None,
            "Plug it in with a USB cable, unlock it, and choose File transfer in the "
            "USB notification. Games are converted on this PC and then sent across.",
            body=self.device_picker)

        self.roms_radio = QRadioButton("Into a ROMs folder on this PC or an SD card")
        self.roms_path = QLabel()
        roms_box = self._choice(
            self.roms_radio, "Choose the ROMs folder...", self.roms_path,
            "The folder with a folder for each console inside it (psx, snes, switch "
            "and so on). Each game goes into the folder for its console, which is "
            "created if missing.")

        beside_text = (f"In my output folder ({self.settings.output_dir})"
                       if self.settings.output_dir else "Next to the original files")
        self.beside_radio = QRadioButton(beside_text)
        beside_box = self._choice(
            self.beside_radio, "", None, "Good for freeing up space on this computer.")

        radios = ((self.device_radio, Destination.DEVICE),
                  (self.roms_radio, Destination.ROMS),
                  (self.beside_radio, Destination.BESIDE))
        for radio, kind in radios:
            self.destination_group.addButton(radio)
            radio.setProperty("destination", kind.value)
        for box in (device_box, roms_box, beside_box):
            body.addWidget(box)

        self.destination_hint = QLabel(
            "Choose the ROMs folder or a device first, or pick another option.")
        self.destination_hint.setProperty("role", "warn")
        body.addWidget(self.destination_hint)
        body.addStretch()

        if self.settings.device is not None:
            self.device_radio.setChecked(True)
        elif self.settings.esde_root:
            self._roms = Path(self.settings.esde_root)
            self.roms_radio.setChecked(True)
        elif self.settings.output_dir:
            self.beside_radio.setChecked(True)
        else:
            self.roms_radio.setChecked(True)
        self._refresh_paths()
        # Connected after the preselection above: the Next button does not
        # exist yet while the pages are being built.
        for radio, _kind in radios:
            radio.toggled.connect(lambda _on: self._update_next())
        return page

    def _choice(self, radio: QRadioButton, button_text: str,
                path_label: QLabel | None, hint: str, *,
                body: QWidget | None = None) -> QWidget:
        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(radio)
        details = QWidget()
        inner = QVBoxLayout(details)
        inner.setContentsMargins(26, 0, 0, 0)
        inner.setSpacing(4)
        if button_text and path_label is not None:
            row = QHBoxLayout()
            row.setSpacing(8)
            pick = QPushButton(button_text)
            pick.clicked.connect(self._pick)
            row.addWidget(pick)
            path_label.setProperty("role", "second")
            path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row.addWidget(path_label, stretch=1)
            inner.addLayout(row)
        text = QLabel(hint)
        text.setWordWrap(True)
        text.setProperty("role", "third")
        inner.addWidget(text)
        if body is not None:
            inner.addWidget(body)
        column.addWidget(details)
        return box

    def _keys_page(self) -> QWidget:
        page, body = self._page(
            "Switch games (optional)",
            "Switch games can only be compressed with a prod.keys file from your own "
            "Switch. The app never downloads or shares it.",
            "key")
        self.keys_status = QLabel()
        self.keys_status.setWordWrap(True)
        body.addWidget(self.keys_status)
        choose = QPushButton("Choose prod.keys...")
        choose.clicked.connect(self._pick_keys)
        body.addWidget(choose, alignment=Qt.AlignmentFlag.AlignLeft)
        note = QLabel("No Switch games? Just press Finish.")
        note.setProperty("role", "third")
        body.addWidget(note)
        body.addStretch()
        self._refresh_keys()
        return page

    # ------------------------------------------------------------- programs

    def _refresh_programs(self) -> None:
        self.tools.refresh()
        status = self.tools.status()
        total = len(status)
        missing = sum(1 for ready in status.values() if not ready)
        stale = len(self.tools.outdated())
        if not missing and not stale:
            self.programs_status.setText(f"All {total} programs are ready.")
            self.install_button.hide()
            return
        if missing and stale:
            text = (f"{missing + stale} of {total} programs need to be installed "
                    "or updated.")
        elif missing:
            text = f"{missing} of {total} programs still need to be installed."
        else:
            text = f"{stale} of {total} programs need an update."
        self.programs_status.setText(text)
        self.install_button.show()

    def _install(self) -> None:
        self._set_busy(True)
        self.install_button.setText("Installing...")
        self.install_log.show()
        self.install_log.appendPlainText("Starting.")
        self._worker = InstallWorker()
        self._worker.log.connect(self.install_log.appendPlainText)
        self._worker.done.connect(self._installed)
        self._worker.start()

    def _installed(self, errors: list[str]) -> None:
        for error in errors:
            self.install_log.appendPlainText(error)
        self.install_log.appendPlainText(
            "Some programs could not be installed. You can try again later from Tools."
            if errors else "Done.")
        self.install_button.setText("Install programs")
        self._set_busy(False)
        self._refresh_programs()

    def _set_busy(self, busy: bool) -> None:
        for button in (self.install_button, self.skip_button,
                       self.back_button, self.next_button):
            button.setEnabled(not busy)
        if not busy:
            self._update_next()

    def _installing(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    # ---------------------------------------------------------- destination

    def selected_destination(self) -> Destination:
        checked = self.destination_group.checkedButton()
        if checked is None:
            return Destination.BESIDE
        return Destination(checked.property("destination"))

    def choose_destination(self, kind: Destination, path: Path | None = None) -> None:
        """Select an option; for the ROMs folder, also record which folder.

        Picking the drive or the folder that holds `ROMs` works too: ES-DE's
        own layout rules find the ROMs folder inside it.
        """
        if kind is Destination.BESIDE:
            self.beside_radio.setChecked(True)
            return
        if kind is Destination.DEVICE:
            self.device_radio.setChecked(True)
            self._update_next()
            return
        if path is not None:
            self._roms = resolve_roms_root(path)
        self.roms_radio.setChecked(True)
        self._refresh_paths()
        self._update_next()

    def _pick(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose your ROMs folder")
        if folder:
            self.choose_destination(Destination.ROMS, Path(folder))

    def _refresh_paths(self) -> None:
        if self._roms is None:
            self.roms_path.setText("Nothing chosen yet")
            self.roms_path.setToolTip("")
            return
        self.roms_path.setText(self.roms_path.fontMetrics().elidedText(
            str(self._roms), Qt.TextElideMode.ElideMiddle, 360))
        self.roms_path.setToolTip(str(self._roms))

    # ----------------------------------------------------------------- keys

    def choose_keys(self, path: Path) -> None:
        self._keys = path
        self._refresh_keys()

    def _pick_keys(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose prod.keys", "", "Switch keys (*.keys);;All files (*)")
        if path:
            self.choose_keys(Path(path))

    def _current_keys(self) -> Path | None:
        if self._keys is not None:
            return self._keys
        if self.settings.keys_path and Path(self.settings.keys_path).is_file():
            return Path(self.settings.keys_path)
        return find_prod_keys()

    def _refresh_keys(self) -> None:
        found = self._current_keys()
        self.keys_status.setText(
            f"Found prod.keys in {found.parent}." if found else "No prod.keys found yet.")

    # ------------------------------------------------------------ navigation

    def _show(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.step_label.setText(f"Step {index + 1} of {self.pages.count()}")
        self.step_bar.set_current(index)
        self.back_button.setVisible(index > 0)
        last = index == self.pages.count() - 1
        self.next_button.setText("Finish" if last else "Next")
        self._update_next()

    def _update_next(self) -> None:
        if self._installing():
            return
        on_destination = self.pages.currentIndex() == 1
        chosen = self.selected_destination()
        ready = (chosen is Destination.BESIDE
                 or (chosen is Destination.ROMS and self._roms is not None)
                 or (chosen is Destination.DEVICE
                     and self.device_picker.target() is not None))
        self.next_button.setEnabled(ready or not on_destination)
        self.destination_hint.setVisible(on_destination and not ready)

    def next_page(self) -> None:
        index = self.pages.currentIndex()
        if index == self.pages.count() - 1:
            self.finish()
            return
        self._show(index + 1)

    def back(self) -> None:
        self._show(max(0, self.pages.currentIndex() - 1))

    def finish(self) -> None:
        self.apply()
        state.save_welcome_done()
        self.accept()

    def apply(self) -> None:
        """Write the choices into the settings this dialog was given."""
        chosen = self.selected_destination()
        if chosen is Destination.BESIDE:
            self.settings.esde_root = ""
            self.settings.device = None
        elif chosen is Destination.DEVICE and self.device_picker.target() is not None:
            self.settings.device = self.device_picker.target()
            self.settings.esde_root = ""
        elif chosen is Destination.ROMS and self._roms is not None:
            self.settings.esde_root = str(self._roms)
            self.settings.device = None
        if self._keys is not None:
            self.settings.keys_path = str(self._keys)

    def reject(self) -> None:
        if self._installing():
            return
        state.save_welcome_done()
        super().reject()

    def done(self, result: int) -> None:
        self.device_picker.close_down()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._installing():
            event.ignore()
            return
        super().closeEvent(event)
