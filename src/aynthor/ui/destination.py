"""Choosing where finished games go: a handheld on USB, a folder, or nowhere new.

A handheld plugged in over USB has no drive letter, so the ordinary folder
picker cannot reach it; Windows shows it under This PC and nothing else can.
This dialog lists what is plugged in, the way Explorer does, and lets the user
pick its SD card or its internal storage. The ROMs folder at the top of that
storage is found by name.

Talking to USB takes a moment, so it happens on a worker thread and the dialog
says what it is doing. The scan and the folder listing are passed in, which
is how the tests run this dialog without a device.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.device import (
    BREADCRUMB,
    DeviceTarget,
    FoundDevice,
    FoundStorage,
    available,
    com_thread,
    open_target,
    scan,
)
from aynthor.core.esde import resolve_roms_root
from aynthor.core.settings import FormatSettings
from aynthor.ui import icons, theme
from aynthor.ui.queue_view import human_size

Scanner = Callable[[], list[FoundDevice]]
FolderLister = Callable[[DeviceTarget, PurePosixPath], list[str]]


class Where(str, Enum):
    DEVICE = "device"
    FOLDER = "folder"
    BESIDE = "beside"


@dataclass(frozen=True)
class Choice:
    where: Where
    device: DeviceTarget | None = None
    folder: str = ""

    def apply_to(self, settings: FormatSettings) -> None:
        """A device and a ROMs folder are alternatives; setting one clears the
        other, so there is never a question of which one wins."""
        settings.device = self.device if self.where is Where.DEVICE else None
        settings.esde_root = self.folder if self.where is Where.FOLDER else ""

    @classmethod
    def from_settings(cls, settings: FormatSettings) -> Choice:
        if settings.device is not None:
            return cls(Where.DEVICE, settings.device)
        if settings.esde_root:
            return cls(Where.FOLDER, folder=settings.esde_root)
        return cls(Where.BESIDE)


def describe(settings: FormatSettings) -> str:
    """One line for the bottom bar and the settings page."""
    if settings.device is not None:
        return f"Sending to {settings.device.label}"
    if settings.esde_root:
        return f"Saving to {resolve_roms_root(Path(settings.esde_root))}"
    if settings.output_dir:
        return f"Saving to {settings.output_dir}"
    return "Saving next to the original files"


# --------------------------------------------------------------- USB work


def scan_devices() -> list[FoundDevice]:
    if not available():
        return []
    with com_thread() as runtime:
        return scan(runtime)


def list_folders(target: DeviceTarget, path: PurePosixPath) -> list[str]:
    """Folder names under `path`, which is relative to the storage's top."""
    with com_thread() as runtime, open_target(
            DeviceTarget(target.device_id, target.device_name, target.storage, "."),
            runtime) as fs:
        return sorted((e.name for e in fs.listdir(path) if e.is_dir), key=str.casefold)


class _Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Callable[[], object]) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            self.done.emit(self._job())
        except OSError as exc:
            self.failed.emit(str(exc))


class _Background:
    """Run one call on a thread and deliver its result on the window's."""

    def __init__(self, parent: QObject) -> None:
        self._parent = parent
        self._running: list[tuple[QThread, _Worker]] = []

    def start(self, job: Callable[[], object], done: Callable[[object], None],
              failed: Callable[[str], None]) -> None:
        thread = QThread(self._parent)
        worker = _Worker(job)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(done)
        worker.failed.connect(failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        pair = (thread, worker)
        self._running.append(pair)
        thread.finished.connect(lambda p=pair: self._finished(p))
        thread.start()

    def _finished(self, pair: tuple[QThread, _Worker]) -> None:
        if pair in self._running:
            self._running.remove(pair)
        pair[0].deleteLater()

    def wait(self) -> None:
        for thread, _worker in list(self._running):
            thread.quit()
            thread.wait(5000)


# ----------------------------------------------------------- the picker


class _StorageRow(QWidget):
    """One storage of one device: name, how full it is, and its ROMs folder."""

    def __init__(self, device: FoundDevice, storage: FoundStorage) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(12)
        badge = QLabel()
        badge.setPixmap(icons.pixmap(
            "sd-card" if "internal" not in storage.name.casefold() else "handheld",
            "textSecond", 28, self.devicePixelRatioF()))
        row.addWidget(badge, alignment=Qt.AlignmentFlag.AlignTop)

        column = QVBoxLayout()
        column.setSpacing(5)
        title = QLabel(f"{device.name}  {BREADCRUMB}  {storage.name}")
        title.setProperty("role", "strong")
        column.addWidget(title)
        room = (f"{human_size(storage.free)} free of {human_size(storage.capacity)}"
                if storage.capacity else "Size unknown")
        roms = ("ROMs folder found" if storage.roms
                else "No ROMs folder yet")
        detail = QLabel(f"{room}   \u00b7   {roms}")
        detail.setProperty("role", "third")
        detail.setToolTip("" if storage.roms else
                          "A ROMs folder is made at the top of it on the first send.")
        column.addWidget(detail)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        used = max(0, storage.capacity - storage.free)
        bar.setRange(0, 1000)
        bar.setValue(int(used * 1000 / storage.capacity) if storage.capacity else 0)
        bar.setToolTip(f"{human_size(used)} used")
        column.addWidget(bar)
        self.setMinimumHeight(72)
        row.addLayout(column, stretch=1)


class DevicePicker(QWidget):
    """The handhelds and phones plugged in, one row per storage."""

    changed = Signal()

    def __init__(self, scanner: Scanner, lister: FolderLister,
                 current: DeviceTarget | None = None) -> None:
        super().__init__()
        self._scanner = scanner
        self._lister = lister
        self._background = _Background(self)
        self._found: list[tuple[FoundDevice, FoundStorage]] = []
        self._root_override: dict[tuple[str, str], str] = {}
        self._current = current

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.list = QListWidget()
        self.list.setObjectName("deviceList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMinimumHeight(96)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentRowChanged.connect(lambda _r: self._selection_changed())
        layout.addWidget(self.list)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("role", "second")
        layout.addWidget(self.status)

        buttons = QHBoxLayout()
        self.rescan_button = QPushButton("Look again")
        self.rescan_button.setIcon(icons.icon("refresh"))
        self.rescan_button.clicked.connect(self.rescan)
        buttons.addWidget(self.rescan_button)
        self.folder_button = QPushButton("Use another folder on it...")
        self.folder_button.clicked.connect(self._choose_folder)
        buttons.addWidget(self.folder_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        if current is not None:
            self._root_override[(current.device_name, current.storage)] = current.root
        self.rescan()

    # -------------------------------------------------------------- scanning

    def rescan(self) -> None:
        self.list.clear()
        self._found = []
        self.rescan_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.status.setText("Looking for devices plugged in over USB...")
        self._background.start(self._scanner, self._show, self._scan_failed)

    def _scan_failed(self, message: str) -> None:
        self.rescan_button.setEnabled(True)
        self.status.setText(message)
        self.changed.emit()

    def _show(self, found: object) -> None:
        self.rescan_button.setEnabled(True)
        devices: list[FoundDevice] = list(found)  # type: ignore[call-overload]
        problems = [d for d in devices if d.problem]
        height = 0
        for device in devices:
            for storage in device.storages:
                self._found.append((device, storage))
                item = QListWidgetItem()
                row = _StorageRow(device, storage)
                hint = row.sizeHint().expandedTo(QSize(0, 76))
                item.setSizeHint(hint)
                height += hint.height()
                self.list.addItem(item)
                self.list.setItemWidget(item, row)
        # Every storage in view without scrolling; a handheld has two.
        self.list.setFixedHeight(max(96, min(height, 3 * 80) + 2 * self.list.frameWidth() + 12))
        if self._found:
            self.status.setText(problems[0].problem if problems else "")
            self.list.setCurrentRow(self._preferred_row())
        elif problems:
            self.status.setText(problems[0].problem)
        else:
            self.status.setText(
                "Nothing is plugged in. Connect your handheld with a USB cable, unlock "
                "it, and choose File transfer in the USB notification on it.")
        self._selection_changed()

    def _preferred_row(self) -> int:
        """The storage chosen last time; otherwise one that already has a ROMs
        folder, the SD card before internal storage; otherwise the first."""
        if self._current is not None:
            for index, (device, storage) in enumerate(self._found):
                if (device.name, storage.name) == (self._current.device_name,
                                                   self._current.storage):
                    return index
        for index, (_device, storage) in enumerate(self._found):
            if storage.roms and "internal" not in storage.name.casefold():
                return index
        for index, (_device, storage) in enumerate(self._found):
            if storage.roms:
                return index
        return 0

    def _selection_changed(self) -> None:
        self.folder_button.setEnabled(self.target() is not None)
        self.changed.emit()

    # -------------------------------------------------------------- choosing

    def target(self) -> DeviceTarget | None:
        index = self.list.currentRow()
        if not 0 <= index < len(self._found):
            return None
        device, storage = self._found[index]
        root = self._root_override.get((device.name, storage.name))
        return device.target(storage, root)

    def _choose_folder(self) -> None:
        target = self.target()
        if target is None:
            return
        dialog = DeviceFolderDialog(target, self._lister, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.chosen is not None:
            self._root_override[(target.device_name, target.storage)] = \
                dialog.chosen.as_posix()
            self.status.setText(f"Games go to {self.target().label}.")  # type: ignore[union-attr]
            self.changed.emit()

    def close_down(self) -> None:
        self._background.wait()


class DeviceFolderDialog(QDialog):
    """Browse the folders of one storage on a device, one level at a time."""

    def __init__(self, target: DeviceTarget, lister: FolderLister,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Choose a folder on {target.device_name}")
        self.resize(460, 420)
        self.target = target
        self._lister = lister
        self._background = _Background(self)
        self.chosen: PurePosixPath | None = None

        layout = QVBoxLayout(self)
        intro = QLabel("Pick the folder ES-DE uses as its ROMs folder. The folder for "
                       "each console goes inside it.")
        intro.setWordWrap(True)
        intro.setProperty("role", "second")
        layout.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self._load)
        layout.addWidget(self.tree, stretch=1)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.use_button = QPushButton("Use this folder")
        self.use_button.setProperty("accent", True)
        self.use_button.clicked.connect(self._use)
        buttons.addWidget(self.use_button)
        layout.addLayout(buttons)

        top = QTreeWidgetItem([target.storage])
        top.setData(0, Qt.ItemDataRole.UserRole, ".")
        top.setIcon(0, icons.icon("sd-card"))
        self.tree.addTopLevelItem(top)
        self._placeholder(top)
        top.setExpanded(True)
        self.tree.setCurrentItem(top)

    def _placeholder(self, item: QTreeWidgetItem) -> None:
        loading = QTreeWidgetItem(["Loading..."])
        loading.setData(0, Qt.ItemDataRole.UserRole, None)
        loading.setFlags(Qt.ItemFlag.NoItemFlags)
        item.addChild(loading)

    def _load(self, item: QTreeWidgetItem) -> None:
        if item.childCount() != 1 or item.child(0).data(0, Qt.ItemDataRole.UserRole) is not None:
            return
        path = PurePosixPath(item.data(0, Qt.ItemDataRole.UserRole))
        self._background.start(
            lambda: self._lister(self.target, path),
            lambda names, i=item, p=path: self._fill(i, p, names),
            lambda message, i=item: i.child(0).setText(0, message))

    def _fill(self, item: QTreeWidgetItem, path: PurePosixPath, names: object) -> None:
        item.takeChildren()
        for name in names:  # type: ignore[attr-defined]
            child = QTreeWidgetItem([name])
            child.setData(0, Qt.ItemDataRole.UserRole, (path / name).as_posix())
            child.setIcon(0, icons.icon("folder"))
            item.addChild(child)
            self._placeholder(child)

    def _use(self) -> None:
        item = self.tree.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if value is None:
            return
        self.chosen = PurePosixPath(value)
        self.accept()

    def done(self, result: int) -> None:
        self._background.wait()
        super().done(result)


class DestinationDialog(QDialog):
    """Where finished games go. Three answers, one of them a device."""

    def __init__(self, settings: FormatSettings, parent: QWidget | None = None, *,
                 scanner: Scanner = scan_devices, lister: FolderLister = list_folders) -> None:
        super().__init__(parent)
        self.setWindowTitle("Where should finished games go?")
        self.setMinimumWidth(600)
        self.settings = settings
        current = Choice.from_settings(settings)
        self._folder = current.folder

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)
        heading = QLabel("Where should finished games go?")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        self.group = QButtonGroup(self)
        self.device_radio = QRadioButton("Straight onto my handheld, over USB")
        self.folder_radio = QRadioButton("Into a ROMs folder on this PC or an SD card")
        self.beside_radio = QRadioButton("Next to the original files")

        self.picker = DevicePicker(scanner, lister, settings.device)
        layout.addWidget(self._card(self.device_radio, self.picker,
                                    "Windows only. Leave the handheld unlocked while games "
                                    "are being sent."))

        folder_box = QWidget()
        folder_row = QHBoxLayout(folder_box)
        folder_row.setContentsMargins(0, 0, 0, 0)
        self.folder_label = QLabel()
        self.folder_label.setProperty("role", "second")
        folder_row.addWidget(self.folder_label, stretch=1)
        choose = QPushButton("Choose...")
        choose.clicked.connect(self._pick_folder)
        folder_row.addWidget(choose)
        layout.addWidget(self._card(self.folder_radio, folder_box,
                                    "The folder with psx, snes, switch and so on inside it. "
                                    "Each game goes into the folder for its console."))
        layout.addWidget(self._card(self.beside_radio, None,
                                    "Good for freeing up space on this PC."))

        layout.addStretch()
        buttons = QHBoxLayout()
        self.hint = QLabel()
        self.hint.setProperty("role", "warn")
        buttons.addWidget(self.hint, stretch=1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.ok_button = QPushButton("Use this")
        self.ok_button.setProperty("accent", True)
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)

        # Connected last: a toggle refreshes the hint and the OK button, which
        # do not exist until here.
        self.picker.changed.connect(self._refresh)
        for radio in (self.device_radio, self.folder_radio, self.beside_radio):
            self.group.addButton(radio)
        {Where.DEVICE: self.device_radio, Where.FOLDER: self.folder_radio,
         Where.BESIDE: self.beside_radio}[current.where].setChecked(True)
        for radio in (self.device_radio, self.folder_radio, self.beside_radio):
            radio.toggled.connect(lambda _on: self._refresh())
        self._refresh()

    def _card(self, radio: QRadioButton, body: QWidget | None, hint: str) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        column = QVBoxLayout(card)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(6)
        column.addWidget(radio)
        note = QLabel(hint)
        note.setWordWrap(True)
        note.setProperty("role", "third")
        note.setContentsMargins(26, 0, 0, 0)
        column.addWidget(note)
        if body is not None:
            body.setContentsMargins(26, 0, 0, 0)
            column.addWidget(body)
        return card

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose your ROMs folder")
        if path:
            self._folder = str(resolve_roms_root(Path(path)))
            self.folder_radio.setChecked(True)
            self._refresh()

    def choice(self) -> Choice:
        if self.device_radio.isChecked():
            return Choice(Where.DEVICE, self.picker.target())
        if self.folder_radio.isChecked():
            return Choice(Where.FOLDER, folder=self._folder)
        return Choice(Where.BESIDE)

    def _refresh(self) -> None:
        self.folder_label.setText(self._folder or "No folder chosen yet")
        chosen = self.choice()
        missing = ""
        if chosen.where is Where.DEVICE and chosen.device is None:
            missing = "Plug in a device and choose its storage, or pick another option."
        elif chosen.where is Where.FOLDER and not chosen.folder:
            missing = "Choose the ROMs folder first."
        self.hint.setText(missing)
        self.ok_button.setEnabled(not missing)
        self.picker.setEnabled(self.device_radio.isChecked())
        theme.restyle(self)

    def done(self, result: int) -> None:
        if result == QDialog.DialogCode.Accepted:
            self.choice().apply_to(self.settings)
        self.picker.close_down()
        super().done(result)
