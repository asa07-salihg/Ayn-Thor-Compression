"""The queue table: what will happen to each file, and what it saved.

Why
    The table is the app. Every row has to answer, without being clicked: what
    is this file, what will it become, and afterwards, what did it save. The
    savings column is the one most tools of this kind leave out, and it is the
    reason anyone runs a compressor.

    There is no format selector anywhere else in the window, because the format
    belongs to the row rather than to the app. Auto-detection sets it; the
    right-click menu changes it, for one row or for everything selected. That
    removed an entire mechanism from the old design, where a global format had
    to be pushed onto rows that had already been added.

    Game and Type are hidden until a Switch file appears, because those columns
    mean nothing for anything else and they crowd out the filename.

Used by
    `ui.main_window`.

Reference
    Output naming: `core.formats.suggest_output_path`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
)

from aynthor.core import esde
from aynthor.core.esde import ESDE_PLATFORM_FOLDERS
from aynthor.core.formats import (
    FORMAT_CATALOG,
    format_info,
    natural_mode,
    suggest_output_path,
)
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.modes import FORMAT_MODES
from aynthor.core.presets import PRESETS, detect_platform_format
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import detect_content_type, is_switch_rom, normalize_game_name
from aynthor.ui import theme

_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_OPTIONS = Qt.ItemDataRole.UserRole + 1
_ROLE_SORT = Qt.ItemDataRole.UserRole + 2

# Formats whose output container is chosen per row rather than fixed, so the
# Becomes cell reads the extension instead of the format's family name.
_NAMED_BY_OUTPUT = frozenset({
    CompressionFormat.Z3DS,
    CompressionFormat.CSO,
    CompressionFormat.SEVEN_ZIP,
})
_ROLE_FORMAT = Qt.ItemDataRole.UserRole + 3
_ROLE_MODE = Qt.ItemDataRole.UserRole + 4
_ROLE_PLATFORM = Qt.ItemDataRole.UserRole + 5


def human_size(num_bytes: float) -> str:
    if num_bytes <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.{0 if unit in ('B', 'KB') else 1}f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


class _BecomesDelegate(QStyledItemDelegate):
    """Draws the Becomes cell as something you can click.

    A chevron on the left of the label, the same one a combo box uses, because
    a cell that changes a value on click has to look different from a cell that
    just reports one. Painted rather than an embedded widget: a real combo box
    in every row costs a widget per file, and the queue can hold hundreds.
    """

    CHEVRON_WIDTH = 16

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        shifted = QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(self.CHEVRON_WIDTH, 0, 0, 0)
        super().paint(painter, shifted, index)

        if not index.data(Qt.ItemDataRole.DisplayRole):
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(theme.color("text" if hovered else "textThird"), 1.3))

        box = QRect(option.rect.left() + 8, option.rect.center().y() - 2, 7, 5)
        painter.drawLine(box.left(), box.top(), box.center().x(), box.bottom())
        painter.drawLine(box.center().x(), box.bottom(), box.right(), box.top())
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        hint = super().sizeHint(option, index)
        hint.setWidth(hint.width() + self.CHEVRON_WIDTH)
        return hint


class QueueTable(QTableWidget):
    queue_changed = Signal()
    settings_requested = Signal(object)  # CompressionFormat

    (COL_FILE, COL_GAME, COL_TYPE, COL_PLATFORM,
     COL_BECOMES, COL_SIZE, COL_SAVED, COL_STATUS) = range(8)
    _HEADERS = ("File", "Game", "Part", "Platform", "Becomes", "Size", "Saved", "Status")
    _NUMERIC = (COL_SIZE, COL_SAVED)
    # Both open a menu on a single click, so both draw the chevron.
    _CLICKABLE = (COL_PLATFORM, COL_BECOMES)

    _STATUS_COLOURS: ClassVar[dict[str, str]] = {
        "Done": "ok", "Failed": "error", "Waiting": "textThird",
    }

    def __init__(self) -> None:
        super().__init__(0, len(_HEADERS := QueueTable._HEADERS))
        self.setHorizontalHeaderLabels(_HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setFrameShape(QTableWidget.Shape.NoFrame)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # The Becomes cell is a control, not a label: one click opens the list
        # of formats that accept the file. Right-click still reaches the same
        # menu plus everything else a row can do.
        for column in self._CLICKABLE:
            self.setItemDelegateForColumn(column, _BecomesDelegate(self))
        self.setMouseTracking(True)
        self.cellClicked.connect(self._on_cell_clicked)

        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(60)
        for column, mode, width in (
            (self.COL_FILE, QHeaderView.ResizeMode.Stretch, 0),
            (self.COL_GAME, QHeaderView.ResizeMode.Interactive, 150),
            (self.COL_TYPE, QHeaderView.ResizeMode.ResizeToContents, 0),
            (self.COL_PLATFORM, QHeaderView.ResizeMode.Interactive, 130),
            (self.COL_BECOMES, QHeaderView.ResizeMode.Interactive, 130),
            (self.COL_SIZE, QHeaderView.ResizeMode.Interactive, 84),
            (self.COL_SAVED, QHeaderView.ResizeMode.Interactive, 76),
            (self.COL_STATUS, QHeaderView.ResizeMode.Interactive, 92),
        ):
            header.setSectionResizeMode(column, mode)
            if width:
                self.setColumnWidth(column, width)
        for column in range(self.columnCount()):
            self.horizontalHeaderItem(column).setTextAlignment(
                (Qt.AlignmentFlag.AlignRight if column in self._NUMERIC
                 else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)

        self._mono = QFont(theme.MONO.split(",")[0].strip('"'))
        self._mono.setPointSizeF(max(8.0, self.font().pointSizeF() - 0.5))

        self.setColumnHidden(self.COL_GAME, True)
        self.setColumnHidden(self.COL_TYPE, True)

        # Output paths depend on the output folder and the Switch grouping, so
        # the table keeps a copy of the settings it last rendered against.
        self._settings = FormatSettings()

        # Adding a folder used to scan the whole table per file to spot
        # duplicates, which is quadratic: a 2,000 file card did two million
        # comparisons before the first row appeared. These two are the same
        # information the table holds, kept alongside it.
        self._queued: set[Path] = set()
        self._total_bytes = 0

    # ---------------------------------------------------------------- filling

    def add_paths(self, paths: list[Path], settings: FormatSettings) -> tuple[int, list[str]]:
        """Returns (rows added, reasons files were skipped)."""
        added = 0
        skipped: list[str] = []

        for path in paths:
            if self._already_queued(path):
                continue
            detected = detect_platform_format(path)
            if detected.skip:
                skipped.append(f"{path.name}: {detected.skip_reason}")
                continue
            fmt = detected.format
            if fmt is None:
                skipped.append(f"{path.name}: no format handles this file")
                continue

            options = self._with_switch_metadata(path, fmt, dict(detected.tool_options))
            mode = natural_mode(path, fmt)
            platform = detected.platform or ""
            output = output_for(path, fmt, mode, settings, options, platform)
            if mode is ConversionMode.COMPRESS and output == path \
                    and fmt is not CompressionFormat.NDS_TRIM:
                # The file is already the container this platform wants. NDS
                # trim is the exception: it rewrites the cart in place and that
                # is what it is for.
                skipped.append(f"{path.name}: already a {path.suffix.lstrip('.')}")
                continue
            self._append(QueueItem(
                path=path,
                format=fmt,
                mode=mode,
                output=output,
                tool_options=options,
                platform=platform,
                game_group=options.get("game_group", ""),
                content_type=options.get("content_type", ""),
            ))
            added += 1

        if added:
            self._reveal_switch_columns()
            self.queue_changed.emit()
        return added, skipped

    def add_from_list(
        self,
        items: list[tuple[Path, CompressionFormat, dict]],
        settings: FormatSettings,
    ) -> int:
        added = 0
        for path, fmt, options in items:
            if self._already_queued(path):
                continue
            options = self._with_switch_metadata(path, fmt, dict(options))
            mode = natural_mode(path, fmt)
            platform = detect_platform_format(path).platform or ""
            self._append(QueueItem(
                path=path,
                format=fmt,
                mode=mode,
                platform=platform,
                output=output_for(path, fmt, mode, settings, options, platform),
                tool_options=options,
                game_group=options.get("game_group", ""),
                content_type=options.get("content_type", ""),
            ))
            added += 1
        if added:
            self._reveal_switch_columns()
            self.queue_changed.emit()
        return added

    @staticmethod
    def _with_switch_metadata(path: Path, fmt: CompressionFormat, options: dict) -> dict:
        if fmt != CompressionFormat.NSZ and not is_switch_rom(path):
            return options
        options.setdefault("game_group", normalize_game_name(path))
        options.setdefault("content_type", detect_content_type(path).value)
        return options

    def _already_queued(self, path: Path) -> bool:
        return path in self._queued

    def _reindex(self) -> None:
        """Rebuild the lookups after rows are removed. Rare, so a scan is fine."""
        self._queued = {self.item(row, self.COL_FILE).data(_ROLE_PATH)
                        for row in range(self.rowCount())}
        self._total_bytes = sum(
            int(value) for row in range(self.rowCount())
            if isinstance(value := self.item(row, self.COL_SIZE).data(_ROLE_SORT), (int, float))
            and value > 0
        )

    def _reveal_switch_columns(self) -> None:
        has_groups = any(self.item(row, self.COL_GAME).text() for row in range(self.rowCount()))
        self.setColumnHidden(self.COL_GAME, not has_groups)
        self.setColumnHidden(self.COL_TYPE, not has_groups)

    def _append(self, item: QueueItem) -> None:
        row = self.rowCount()
        self.insertRow(row)

        name = QTableWidgetItem(item.path.name)
        name.setData(_ROLE_PATH, item.path)
        name.setData(_ROLE_OPTIONS, item.tool_options or {})
        self.setItem(row, self.COL_FILE, name)

        game = QTableWidgetItem(item.game_group)
        game.setToolTip(item.game_group)
        self.setItem(row, self.COL_GAME, game)
        self.setItem(row, self.COL_TYPE, QTableWidgetItem(item.content_type))

        platform = QTableWidgetItem()
        platform.setData(_ROLE_PLATFORM, item.platform)
        self.setItem(row, self.COL_PLATFORM, platform)

        becomes = QTableWidgetItem()
        becomes.setData(_ROLE_PATH, item.output)
        becomes.setData(_ROLE_FORMAT, item.format.value if item.format else "")
        becomes.setData(_ROLE_MODE, item.mode.value)
        self.setItem(row, self.COL_BECOMES, becomes)

        try:
            size = item.path.stat().st_size
        except OSError:
            size = 0
        self._queued.add(item.path)
        self._total_bytes += max(0, size)
        self.setItem(row, self.COL_SIZE, self._numeric(human_size(size), size))
        self.setItem(row, self.COL_SAVED, self._numeric("", -1))
        self.setItem(row, self.COL_STATUS, QTableWidgetItem(item.status))

        self._refresh_row(row)
        self.update_status(row, item.status)

    def _numeric(self, text: str, sort_value: float) -> QTableWidgetItem:
        cell = QTableWidgetItem(text)
        cell.setFont(self._mono)
        cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        cell.setData(_ROLE_SORT, sort_value)
        return cell

    # ------------------------------------------------------------ row reading

    def row_format(self, row: int) -> CompressionFormat | None:
        raw = self.item(row, self.COL_BECOMES).data(_ROLE_FORMAT)
        try:
            return CompressionFormat(raw)
        except ValueError:
            return None

    def row_mode(self, row: int) -> ConversionMode:
        return ConversionMode(self.item(row, self.COL_BECOMES).data(_ROLE_MODE))

    def row_platform(self, row: int) -> str:
        return self.item(row, self.COL_PLATFORM).data(_ROLE_PLATFORM) or ""

    def row_item(self, row: int) -> QueueItem:
        name = self.item(row, self.COL_FILE)
        becomes = self.item(row, self.COL_BECOMES)
        return QueueItem(
            path=name.data(_ROLE_PATH),
            format=self.row_format(row),
            mode=self.row_mode(row),
            platform=self.row_platform(row),
            output=becomes.data(_ROLE_PATH),
            tool_options=name.data(_ROLE_OPTIONS) or {},
            game_group=self.item(row, self.COL_GAME).text(),
            content_type=self.item(row, self.COL_TYPE).text(),
        )

    def queue_items(self) -> list[tuple[int, QueueItem]]:
        return [(row, self.row_item(row)) for row in range(self.rowCount())]

    def formats_in_queue(self) -> list[CompressionFormat]:
        seen: list[CompressionFormat] = []
        for row in range(self.rowCount()):
            fmt = self.row_format(row)
            if fmt is not None and fmt not in seen:
                seen.append(fmt)
        return seen

    def total_input_bytes(self) -> int:
        """Kept as a running total: this is read on every job completion, and
        summing the column each time made a long batch slower as it went."""
        return self._total_bytes

    # ----------------------------------------------------------- row changing

    def _refresh_row(self, row: int) -> None:
        """Recompute the Becomes cell and the output path from the row's state."""
        fmt = self.row_format(row)
        mode = self.row_mode(row)
        name = self.item(row, self.COL_FILE)
        path: Path = name.data(_ROLE_PATH)
        options = name.data(_ROLE_OPTIONS) or {}

        info = format_info(fmt) if fmt else None
        becomes = self.item(row, self.COL_BECOMES)
        platform = self.row_platform(row)
        output = (output_for(path, fmt, mode, self._settings, options, platform)
                  if fmt else path)

        cell = self.item(row, self.COL_PLATFORM)
        preset = PRESETS.get(platform)
        cell.setText(preset.label if preset else (platform or "unknown"))
        cell.setToolTip(
            "Which ES-DE folder this file belongs to. It decides the settings, "
            "and where the result goes when a card is set as the destination.")

        label = info.label if info else "?"
        if mode == ConversionMode.DECOMPRESS and fmt is not None:
            # The verb belongs to the format: a .7z is unzipped, a .chd is
            # decompressed. "(open)" covered both and said neither.
            label = f"{label} ({self._verb(fmt, mode).lower()})"
        elif fmt in _NAMED_BY_OUTPUT:
            # These three write more than one container, and which one depends
            # on the row's options: a .cia becomes .zcia, the arcade preset
            # writes .zip, maxcso can write .zso. Showing the format's family
            # name told a user "ZCCI" while the file on disk said something
            # else, so the cell shows what will actually be written.
            label = output.suffix.lstrip(".").upper()
        becomes.setText(label)
        becomes.setData(_ROLE_PATH, output)
        becomes.setToolTip(f"Writes:\n{output}")
        name.setToolTip(f"{path}\n\nWrites:\n{output}")

    def apply_settings(self, settings: FormatSettings) -> None:
        """Output paths depend on the output folder and grouping, so they are
        recomputed whenever those change."""
        self._settings = settings
        for row in range(self.rowCount()):
            self._refresh_row(row)

    # Options a row keeps whatever format it is converted to. Everything else
    # in a row's options belongs to the converter that was chosen when the row
    # was made, and must not survive a change of format: `level` means 5 to
    # DolphinTool and 9 to 7-Zip, so an RVZ row switched to 7z was silently
    # archiving at level 5.
    _FORMAT_NEUTRAL: ClassVar[tuple[str, ...]] = ("game_group", "content_type")

    def _reset_options(self, row: int, fmt: CompressionFormat, extra: dict | None = None) -> None:
        name = self.item(row, self.COL_FILE)
        previous = name.data(_ROLE_OPTIONS) or {}
        options = {k: previous[k] for k in self._FORMAT_NEUTRAL if k in previous}
        options.update(self._settings.for_format(fmt))
        if extra:
            options.update(extra)
        name.setData(_ROLE_OPTIONS, options)

    def set_format(self, rows: list[int], fmt: CompressionFormat) -> None:
        for row in rows:
            becomes = self.item(row, self.COL_BECOMES)
            becomes.setData(_ROLE_FORMAT, fmt.value)
            if not self._supports_reverse(fmt):
                becomes.setData(_ROLE_MODE, ConversionMode.COMPRESS.value)
            self._reset_options(row, fmt)
            self._refresh_row(row)
            self.update_status(row, "Waiting")
        self.queue_changed.emit()

    def set_mode(self, rows: list[int], mode: ConversionMode) -> None:
        for row in rows:
            self.item(row, self.COL_BECOMES).setData(_ROLE_MODE, mode.value)
            self._refresh_row(row)
            self.update_status(row, "Waiting")
        self.queue_changed.emit()

    def apply_format_options(self, fmt: CompressionFormat, options: dict) -> int:
        """Push a format's settings onto every queued row using it.

        Called when the user changes that format's page in Settings, so the
        change is visible on rows that are already in the queue instead of only
        applying to files added later.
        """
        changed = 0
        for row in range(self.rowCount()):
            if self.row_format(row) != fmt:
                continue
            name = self.item(row, self.COL_FILE)
            merged = dict(name.data(_ROLE_OPTIONS) or {})
            merged.update(options)
            name.setData(_ROLE_OPTIONS, merged)
            self._refresh_row(row)
            changed += 1
        return changed

    @staticmethod
    def _supports_reverse(fmt: CompressionFormat) -> bool:
        return any(m.mode == ConversionMode.DECOMPRESS for m in FORMAT_MODES.get(fmt, ()))

    @staticmethod
    def _verb(fmt: CompressionFormat, mode: ConversionMode) -> str:
        """What this format calls this direction. See `core.modes`."""
        for info in FORMAT_MODES.get(fmt, ()):
            if info.mode == mode:
                return info.description
        return "Convert"

    # --------------------------------------------------------------- results

    def update_status(self, row: int, status: str, message: str = "") -> None:
        cell = self.item(row, self.COL_STATUS)
        cell.setText(status)
        cell.setForeground(QBrush(theme.color(self._STATUS_COLOURS.get(status, "text"))))
        if message:
            cell.setToolTip(message)
            self.item(row, self.COL_FILE).setToolTip(message)

    def record_result(self, row: int, input_size: int, output_size: int) -> None:
        cell = self.item(row, self.COL_SAVED)
        if input_size <= 0 or output_size <= 0:
            cell.setText("-")
            return
        saved = input_size - output_size
        percent = saved * 100 / input_size
        cell.setText(f"{percent:.0f}%" if saved > 0 else f"+{-percent:.0f}%")
        cell.setData(_ROLE_SORT, percent)
        cell.setToolTip(
            f"{human_size(input_size)} -> {human_size(output_size)}"
            f"   ({'saved' if saved > 0 else 'grew by'} {human_size(abs(saved))})")
        cell.setForeground(QBrush(theme.color("ok" if saved > 0 else "warn")))

    def refresh_colours(self) -> None:
        """Item foregrounds are concrete colours, not stylesheet rules, so they
        have to be re-applied when the theme changes."""
        for row in range(self.rowCount()):
            status = self.item(row, self.COL_STATUS)
            status.setForeground(QBrush(theme.color(
                self._STATUS_COLOURS.get(status.text(), "text"))))
            saved = self.item(row, self.COL_SAVED)
            text = saved.text()
            if text and text != "-":
                saved.setForeground(QBrush(theme.color("warn" if text.startswith("+") else "ok")))

    # -------------------------------------------------------------- removing

    def selected_rows(self) -> list[int]:
        return sorted({index.row() for index in self.selectedIndexes()})

    def remove_selected(self) -> None:
        rows = sorted(self.selected_rows(), reverse=True)
        for row in rows:
            self.removeRow(row)
        if rows:
            self._reindex()
            self._reveal_switch_columns()
            self.queue_changed.emit()

    def clear_queue(self) -> None:
        self.setRowCount(0)
        self._queued.clear()
        self._total_bytes = 0
        self.queue_changed.emit()

    # ---------------------------------------------------------- context menu

    def _target_rows(self, row: int) -> list[int]:
        """The rows an action applies to: the selection if this row is in it."""
        rows = self.selected_rows()
        return rows if row in rows and len(rows) > 1 else [row]

    def _accepted_formats(self, row: int):
        path: Path = self.item(row, self.COL_FILE).data(_ROLE_PATH)
        extension = path.suffix.lower()
        return [info for info in FORMAT_CATALOG if extension in info.extensions]

    def set_platform(self, rows: list[int], platform: str) -> None:
        """Set a row's platform, and with it the settings its files get.

        Someone converting a fresh download has a file sitting in Downloads
        rather than in a card's `ps2` folder, so nothing can be worked out from
        where it is. Naming the platform is what tells the app which emulator
        will read the result, and which folder of a card to write it into.
        """
        for row in rows:
            self.item(row, self.COL_PLATFORM).setData(_ROLE_PLATFORM, platform)
            preset = PRESETS.get(platform)
            if preset is not None and preset.format in {
                    i.format for i in self._accepted_formats(row)}:
                self.item(row, self.COL_BECOMES).setData(_ROLE_FORMAT, preset.format.value)
                self._reset_options(row, preset.format, preset.options)
            self._refresh_row(row)
            self.update_status(row, "Waiting")
        self.queue_changed.emit()

    def _add_platform_actions(self, menu: QMenu, row: int, rows: list[int]) -> bool:
        """Every platform whose format this file's extension accepts."""
        current = self.row_platform(row)
        accepted = {info.format for info in self._accepted_formats(row)}
        offered = [p for p in PRESETS if p.format in accepted]
        for preset in offered:
            action = QAction(preset.label, self, checkable=True)
            action.setChecked(preset.platform == current)
            if preset.note:
                action.setToolTip(preset.note)
            action.triggered.connect(
                lambda _c, name=preset.platform, r=rows: self.set_platform(r, name))
            menu.addAction(action)
        return bool(offered)

    def _add_format_actions(self, menu: QMenu, row: int, rows: list[int]) -> bool:
        """Fill a menu with the formats this row's file can be converted to."""
        current = self.row_format(row)
        offered = self._accepted_formats(row)
        for info in offered:
            action = QAction(f"{info.label}    {info.platform}", self, checkable=True)
            action.setChecked(info.format == current)
            action.setToolTip(info.reason)
            action.triggered.connect(lambda _c, f=info.format, r=rows: self.set_format(r, f))
            menu.addAction(action)

        if current is not None and self._supports_reverse(current):
            menu.addSeparator()
            verb = self._verb(current, ConversionMode.DECOMPRESS)
            reverse = QAction(f"{verb} instead of convert", self, checkable=True)
            reverse.setChecked(self.row_mode(row) == ConversionMode.DECOMPRESS)
            reverse.setToolTip("Turn an already-compressed file back into the original.")
            reverse.triggered.connect(
                lambda checked, r=rows: self.set_mode(
                    r, ConversionMode.DECOMPRESS if checked else ConversionMode.COMPRESS))
            menu.addAction(reverse)
        return bool(offered)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column not in self._CLICKABLE or self.row_format(row) is None:
            return
        rows = self._target_rows(row)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        filled = (self._add_platform_actions(menu, row, rows)
                  if column == self.COL_PLATFORM
                  else self._add_format_actions(menu, row, rows))
        if not filled:
            return
        # Open it under the cell, the way a combo box drops down.
        cell = self.visualItemRect(self.item(row, column))
        menu.exec(self.viewport().mapToGlobal(cell.bottomLeft()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.pos())
        clickable = (index.isValid() and index.column() in self._CLICKABLE
                     and self.row_format(index.row()) is not None)
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def _show_menu(self, position: QPoint) -> None:
        row = self.rowAt(position.y())
        if row < 0:
            return
        rows = self._target_rows(row)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        convert_to = menu.addMenu("Convert to")
        if not self._add_format_actions(convert_to, row, rows):
            convert_to.setEnabled(False)

        menu.addSeparator()
        current = self.row_format(row)
        if current is not None:
            info = format_info(current)
            settings_action = QAction(f"{info.label} settings...", self)
            settings_action.triggered.connect(
                lambda _c, f=current: self.settings_requested.emit(f))
            menu.addAction(settings_action)

        remove = QAction(
            f"Remove {len(rows)} from queue" if len(rows) > 1 else "Remove from queue", self)
        remove.triggered.connect(self.remove_selected)
        menu.addAction(remove)

        menu.exec(self.viewport().mapToGlobal(position))


def output_for(
    path: Path,
    fmt: CompressionFormat | None,
    mode: ConversionMode,
    settings: FormatSettings,
    options: dict | None = None,
    platform: str = "",
) -> Path:
    """Where a row's result will be written, after the card layout, the output
    folder and the Switch grouping rules are applied.

    An ES-DE card wins over a plain output folder when the row knows which
    platform it is, because that is the whole point of naming the card: the
    file should land in the folder the emulator reads, not in one pile the user
    then has to sort.
    """
    if fmt is None:
        return path
    suggested = suggest_output_path(path, fmt, mode, options)
    game_group = (options or {}).get("game_group", "")

    base = _destination(settings, platform, path)
    if settings.switch_game_subdirs and game_group:
        return (base or path.parent) / game_group / suggested.name
    if base:
        return base / suggested.name
    return suggested


@lru_cache(maxsize=8)
def _roms_root(configured: str) -> Path:
    """Cached: `resolve_roms_root` stats the disk to work out whether it was
    given the ROMs folder or the folder above it, and this is asked once per
    row. A two thousand file card did that two thousand times, and the answer
    cannot change while the queue is being filled."""
    return esde.resolve_roms_root(Path(configured))


def _destination(settings: FormatSettings, platform: str, path: Path) -> Path | None:
    """The folder a result goes in, or None to leave it beside its input."""
    if settings.esde_root and platform:
        folders = ESDE_PLATFORM_FOLDERS.get(platform)
        if folders:
            return _roms_root(settings.esde_root) / folders[0]
    if settings.output_dir:
        return Path(settings.output_dir)
    return None
