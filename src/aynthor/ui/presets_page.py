"""The Platform presets page: what each system becomes, and with what settings.

Why
    These choices used to be invisible. A PS2 file quietly became a zlib CHD
    with hunk 2048, a GameCube ISO became a level 5 zstd RVZ, and nothing on
    screen said so, let alone let anyone change it. That is fine until it is
    wrong for your setup, at which point there was no way to find out what the
    app had decided, never mind adjust it.

    So the table is here in full: every platform, what it converts to, and the
    exact flags. Pick a row and the format's own options panel appears below it,
    filled in with that platform's values. Rows that differ from the built-in
    defaults are marked, and any of them can be put back, because several of
    the defaults exist to work around one specific emulator and are easy to
    break by accident.

Used by
    `ui.settings_dialog`.

Reference
    The table itself: `core.presets`. Why each default is what it is:
    `core.presets`, where every default carries the reason it exists.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.formats import FORMAT_CATALOG
from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PresetTable
from aynthor.ui.option_panels import PANEL_TYPES, BaseFormatPanel

# Keys whose raw value would mean nothing in a summary line.
_LABELS = {
    "chd_type": "", "codecs": "", "hunk_size": "hunk", "num_processors": "cpu",
    "out_fmt": "", "codec": "", "level": "level", "block_size": "block",
    "cso_format": "", "methods": "", "archive_type": "", "comp_mode": "",
    "bs_exp": "block 2^", "threads": "threads", "multi": "parallel",
}
_HIDDEN = {"game_group", "content_type", "keys_path", "key_path", "mode",
           "on_conflict", "delete_source"}


def describe(options: dict) -> str:
    """A one-line summary of a preset's flags, in the order they were written."""
    parts: list[str] = []
    for key, value in options.items():
        if key in _HIDDEN or value in (None, "", 0, [], False):
            continue
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        label = _LABELS.get(key, key.replace("_", " "))
        parts.append(f"{label} {value}".strip())
    return "  ·  ".join(parts) if parts else "tool defaults"


class PresetsPage(QWidget):
    changed = Signal()

    COL_PLATFORM, COL_FORMAT, COL_SETTINGS = range(3)

    def __init__(self, presets: PresetTable) -> None:
        super().__init__()
        self.presets = presets
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro = QLabel(
            "What a file becomes when it is added, worked out from its extension "
            "and the folder it sits in. Pick a row to see and change that "
            "platform's settings.")
        intro.setWordWrap(True)
        intro.setProperty("role", "second")
        layout.addWidget(intro)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Platform", "Converts to", "Settings"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(self.COL_PLATFORM, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_FORMAT, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(self.COL_SETTINGS, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(self.COL_PLATFORM, 150)
        self.table.setColumnWidth(self.COL_FORMAT, 150)
        for column in range(self.table.columnCount()):
            self.table.horizontalHeaderItem(column).setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setMinimumHeight(240)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_panel(row))
        layout.addWidget(self.table)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setProperty("role", "third")
        layout.addWidget(self.note)

        self.panels = QStackedWidget()
        self._panels: dict[CompressionFormat, BaseFormatPanel] = {}
        for fmt, panel_type in PANEL_TYPES.items():
            panel = panel_type(fmt)
            panel.changed.connect(lambda f=fmt: self._on_panel_changed(f))
            self._panels[fmt] = panel
            self.panels.addWidget(panel)
        layout.addWidget(self.panels)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.reset_one = QPushButton("Reset this platform")
        self.reset_one.clicked.connect(self._reset_current)
        reset_all = QPushButton("Reset all")
        reset_all.setToolTip("Put every platform back to the built-in defaults.")
        reset_all.clicked.connect(self._reset_all)
        buttons.addWidget(self.reset_one)
        buttons.addWidget(reset_all)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.reload()

    # ------------------------------------------------------------------ table

    def reload(self) -> None:
        self._loading = True
        current = self.table.currentRow()
        self.table.setRowCount(0)

        for preset in self.presets:
            row = self.table.rowCount()
            self.table.insertRow(row)

            modified = self.presets.is_modified(preset.platform)
            name = QTableWidgetItem(f"{preset.label}   *" if modified else preset.label)
            name.setData(Qt.ItemDataRole.UserRole, preset.platform)
            name.setToolTip(f"ES-DE folder: {preset.platform}"
                            + ("\n\nChanged from the default." if modified else ""))
            self.table.setItem(row, self.COL_PLATFORM, name)

            self.table.setItem(row, self.COL_FORMAT, QTableWidgetItem())
            self.table.setCellWidget(row, self.COL_FORMAT, self._format_combo(preset.platform))

            summary = QTableWidgetItem(describe(preset.options))
            summary.setToolTip(preset.note or describe(preset.options))
            self.table.setItem(row, self.COL_SETTINGS, summary)

        self._loading = False
        self.table.setCurrentCell(max(0, current), 0)
        self._show_panel(max(0, current))

    def _format_combo(self, platform: str) -> QComboBox:
        combo = QComboBox()
        for info in FORMAT_CATALOG:
            combo.addItem(info.label, info.format.value)
        preset = self.presets.get(platform)
        if preset is not None:
            index = combo.findData(preset.format.value)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _i, p=platform, c=combo: self._on_format_changed(p, c))
        return combo

    def _platform_at(self, row: int) -> str | None:
        item = self.table.item(row, self.COL_PLATFORM)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _current_platform(self) -> str | None:
        return self._platform_at(self.table.currentRow())

    # ----------------------------------------------------------------- panels

    def _show_panel(self, row: int) -> None:
        platform = self._platform_at(row)
        preset = self.presets.get(platform) if platform else None
        if preset is None:
            self.panels.setVisible(False)
            self.reset_one.setEnabled(False)
            self.note.clear()
            return

        panel = self._panels[preset.format]
        was_loading, self._loading = self._loading, True
        panel.load(preset.options)
        self._loading = was_loading

        self.panels.setCurrentWidget(panel)
        self.panels.setVisible(True)
        self.reset_one.setEnabled(self.presets.is_modified(platform))
        self.reset_one.setText(f"Reset {preset.label}")

        # Only the platform's own note. The format's general hint is already
        # inside the panel below, and printing both said the same thing twice.
        self.note.setText(preset.note)
        self.note.setVisible(bool(preset.note))

    def _on_panel_changed(self, fmt: CompressionFormat) -> None:
        if self._loading:
            return
        platform = self._current_platform()
        if platform is None or self.presets.get(platform).format != fmt:
            return
        self.presets.set_options(platform, self._panels[fmt].options())
        self._refresh_row(self.table.currentRow())
        self.changed.emit()

    def _on_format_changed(self, platform: str, combo: QComboBox) -> None:
        if self._loading:
            return
        try:
            fmt = CompressionFormat(combo.currentData())
        except ValueError:
            return
        if self.presets.get(platform).format == fmt:
            return
        # set_format drops the old flags, which belonged to a different tool.
        self.presets.set_format(platform, fmt)
        self._refresh_row(self.table.currentRow())
        self._show_panel(self.table.currentRow())
        self.changed.emit()

    def _refresh_row(self, row: int) -> None:
        platform = self._platform_at(row)
        preset = self.presets.get(platform) if platform else None
        if preset is None:
            return
        modified = self.presets.is_modified(platform)
        self.table.item(row, self.COL_PLATFORM).setText(
            f"{preset.label}   *" if modified else preset.label)
        self.table.item(row, self.COL_SETTINGS).setText(describe(preset.options))
        self.reset_one.setEnabled(modified)

    # ----------------------------------------------------------------- resets

    def _reset_current(self) -> None:
        platform = self._current_platform()
        if platform is None:
            return
        self.presets.reset(platform)
        self.reload()
        self.changed.emit()

    def _reset_all(self) -> None:
        self.presets.reset()
        self.reload()
        self.changed.emit()
