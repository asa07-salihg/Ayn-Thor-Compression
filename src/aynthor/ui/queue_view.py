"""The queue tree: game folders, the files inside them, and what they saved.

Why
    The table is the app, but a flat list hid the layout the card actually
    uses. Each game is a folder named like its primary file, extra discs and
    DLC sit inside, and a dump the app could not group is fixed by dropping it
    onto that folder. Empty folders sink to the bottom of each level so the
    titles that are actually queued stay in view. Start only runs the file
    rows; folder rows are drop targets.

    There is no format selector anywhere else in the window, because the format
    belongs to the file rather than to the app.

Used by
    `ui.main_window`.

Reference
    ES-DE "Directories interpreted as files".
    Output naming: `core.output`.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QInputDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
)

from aynthor.core.esde import (
    ESDE_PLATFORM_FOLDERS,
    FOLDER_TO_PLATFORM,
    PLATFORM_LABELS,
    PLATFORM_MENU_GROUPS,
)
from aynthor.core.formats import FORMAT_CATALOG, format_info, natural_mode
from aynthor.core.groups import (
    assign_to_folder,
    best_disk_game_folder,
    folder_kind,
    folder_platform,
    group_folder_name,
    on_disk_members,
    unassign,
)
from aynthor.core.groups import (
    rename_game_folder as rename_disk_game_folder,
)
from aynthor.core.intake import queue_items_for
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.modes import (
    FORMAT_MODES,
    becomes_label,
    reverse_mode,
    reverse_verb,
    source_is_archive,
    supports_reverse,
)
from aynthor.core.output import (
    disc_part,
    is_game_folder,
    output_for,
    platform_destination,
    safe_folder_name,
    strip_disc_tag,
)
from aynthor.core.presets import PRESETS, detect_platform_format
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import (
    canonical_title,
    detect_content_type,
    is_switch_rom,
    normalize_game_name,
    title_family,
    titles_share_game,
)
from aynthor.ui import theme

_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_OPTIONS = Qt.ItemDataRole.UserRole + 1
_ROLE_SORT = Qt.ItemDataRole.UserRole + 2
_ROLE_FORMAT = Qt.ItemDataRole.UserRole + 3
_ROLE_MODE = Qt.ItemDataRole.UserRole + 4
_ROLE_PLATFORM = Qt.ItemDataRole.UserRole + 5
_ROLE_MEMBER = Qt.ItemDataRole.UserRole + 6
_ROLE_LABEL = Qt.ItemDataRole.UserRole + 7
_ROLE_KIND = Qt.ItemDataRole.UserRole + 8
_ROLE_ID = Qt.ItemDataRole.UserRole + 9
_ROLE_FOLDER_KIND = Qt.ItemDataRole.UserRole + 10
_ROLE_FOLDER_KEY = Qt.ItemDataRole.UserRole + 11
_ROLE_TITLE_FAMILY = Qt.ItemDataRole.UserRole + 12
_ROLE_DISK_ANCHOR = Qt.ItemDataRole.UserRole + 13

_KIND_FILE = "file"
_KIND_FOLDER = "folder"
_STATUS_ON_CARD = "Already on card"

_NAMED_BY_OUTPUT = frozenset({
    CompressionFormat.Z3DS,
    CompressionFormat.CSO,
    CompressionFormat.SEVEN_ZIP,
})


def human_size(num_bytes: float) -> str:
    if num_bytes <= 0:
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.{0 if unit in ('B', 'KB') else 1}f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def _folder_depth(path: Path, root: Path | None) -> int:
    if root is None:
        return len(path.parts)
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return len(path.parts)


def _platform_label(platform: str) -> str:
    if not platform:
        return ""
    preset = PRESETS.get(platform)
    if preset is not None:
        return preset.label
    return PLATFORM_LABELS.get(platform, platform)


class _BecomesDelegate(QStyledItemDelegate):
    """Draws the Becomes cell as something you can click."""

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


class _ColumnView:
    """One column of a tree item, with the QTableWidgetItem methods the tests use."""

    def __init__(self, node: QTreeWidgetItem, column: int) -> None:
        self._node = node
        self._column = column

    def text(self) -> str:
        return self._node.text(self._column)

    def data(self, role):
        return self._node.data(self._column, role)

    def setData(self, role, value) -> None:
        self._node.setData(self._column, role, value)

    def setText(self, text: str) -> None:
        self._node.setText(self._column, text)

    def setForeground(self, brush) -> None:
        self._node.setForeground(self._column, brush)

    def setToolTip(self, text: str) -> None:
        self._node.setToolTip(self._column, text)


class QueueTable(QTreeWidget):
    queue_changed = Signal()
    settings_requested = Signal(object)

    (COL_FILE, COL_GAME, COL_TYPE, COL_PLATFORM,
     COL_BECOMES, COL_SIZE, COL_SAVED, COL_STATUS) = range(8)
    _HEADERS = ("File", "Game", "Part", "Platform", "Becomes", "Size", "Saved", "Status")
    _NUMERIC = (COL_SIZE, COL_SAVED)
    _CLICKABLE = (COL_PLATFORM, COL_BECOMES)

    _STATUS_COLOURS: ClassVar[dict[str, str]] = {
        "Done": "ok", "Failed": "error", "Waiting": "textThird",
        "Already on card": "textThird",
    }
    _FORMAT_NEUTRAL: ClassVar[tuple[str, ...]] = (
        "game_group", "content_type", "game_folder")

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(len(self._HEADERS))
        self.setHeaderLabels(self._HEADERS)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setUniformRowHeights(True)
        self.setIndentation(22)
        self.setAnimated(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        for column in self._CLICKABLE:
            self.setItemDelegateForColumn(column, _BecomesDelegate(self))
        self.setMouseTracking(True)
        self.itemClicked.connect(self._on_item_clicked)

        header = self.header()
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
            self.headerItem().setTextAlignment(
                column,
                (Qt.AlignmentFlag.AlignRight if column in self._NUMERIC
                 else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)

        self._mono = QFont(theme.MONO.split(",")[0].strip('"'))
        self._mono.setPointSizeF(max(8.0, self.font().pointSizeF() - 0.5))

        self.setColumnHidden(self.COL_GAME, True)
        self.setColumnHidden(self.COL_TYPE, True)

        self._settings = FormatSettings()
        self._queued: set[tuple[Path, str]] = set()
        self._total_bytes = 0
        self._next_id = 1
        self._by_id: dict[int, QTreeWidgetItem] = {}
        self._join_decisions: dict[str, bool] = {}

    # ---------------------------------------------------------------- filling

    def add_paths(
        self,
        paths: list[Path],
        settings: FormatSettings,
        labels: dict[Path, str] | None = None,
    ) -> tuple[int, list[str]]:
        self._settings = settings
        self._join_decisions = {}
        added = 0
        skipped: list[str] = []
        labels = labels or {}

        for path in paths:
            items, reason = queue_items_for(path, settings, label=labels.get(path, ""))
            if reason:
                skipped.append(reason)
                continue
            for item in items:
                if self._already_queued(item.path, item.member):
                    continue
                self._apply_disk_join(item)
                self._append(item)
                added += 1

        if added:
            self._reveal_part_column()
            self._sort_tree()
            self.queue_changed.emit()
        return added, skipped

    def _confirm_disk_join(self, folder_name: str, file_label: str) -> bool:
        reply = QMessageBox.question(
            self,
            "Add to existing game?",
            f"Add “{file_label}” to the existing folder\n“{folder_name}”?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _apply_disk_join(self, item: QueueItem) -> None:
        """If the card already has this title, ask and lock output to that folder."""
        options = item.tool_options or {}
        if options.get("on_disk") or options.get("disk_anchor"):
            return
        if not item.platform:
            return
        dest = platform_destination(self._settings, item.platform, item.path)
        if dest is None or not dest.is_dir():
            return
        try:
            candidates = [
                path for path in dest.iterdir()
                if path.is_dir() and is_game_folder(path)
            ]
        except OSError:
            return
        title = (
            item.game_group
            or strip_disc_tag(item.source_name)
            or Path(item.source_name).stem
        )
        match = best_disk_game_folder(title, candidates)
        if match is None:
            return
        try:
            key = str(match.resolve())
        except OSError:
            key = str(match)
        if key in self._join_decisions:
            if not self._join_decisions[key]:
                return
        else:
            accepted = self._confirm_disk_join(match.name, item.display_name)
            self._join_decisions[key] = accepted
            if not accepted:
                return
        assign_to_folder(item, match.name, self._settings, platform=item.platform)
        options = dict(item.tool_options or {})
        options["disk_anchor"] = key
        options["game_folder"] = match.name
        item.tool_options = options
        if item.format is not None:
            item.output = output_for(
                item.path, item.format, item.mode, self._settings, options,
                item.platform, item.member)

    def _seed_on_disk_rows(
        self, disk: Path, platform: str, folder: QTreeWidgetItem,
    ) -> None:
        """Show files already on the card under the game tree; they are not converted."""
        for member in on_disk_members(disk):
            if self._already_queued(member, ""):
                continue
            try:
                anchor = str(disk.resolve())
            except OSError:
                anchor = str(disk)
            item = QueueItem(
                path=member,
                format=None,
                mode=ConversionMode.COMPRESS,
                output=member,
                platform=platform,
                game_group=disk.stem,
                status=_STATUS_ON_CARD,
                tool_options={
                    "game_folder": disk.name,
                    "disk_anchor": anchor,
                    "on_disk": True,
                },
            )
            node = QTreeWidgetItem()
            node.setData(self.COL_FILE, _ROLE_KIND, _KIND_FILE)
            item_id = self._next_id
            self._next_id += 1
            node.setData(self.COL_FILE, _ROLE_ID, item_id)
            node.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled)
            self._write(node, item)
            folder.addChild(node)
            self._by_id[item_id] = node
            self._queued.add((member, ""))
            try:
                size = member.stat().st_size
            except OSError:
                size = 0
            self._total_bytes += max(0, size)
            self._numeric(node, self.COL_SIZE, human_size(size), size)
            self._numeric(node, self.COL_SAVED, "", -1)
            self._refresh_item(node)
            self.update_status(item_id, _STATUS_ON_CARD)
        folder.setExpanded(True)
        self._refresh_folder_status(folder)

    def add_empty_folders(self, folders: list[Path], settings: FormatSettings) -> int:
        return self.add_folder_tree(None, folders, settings)

    def add_folder_tree(
        self,
        root: Path | None,
        folders: list[Path],
        _settings: FormatSettings,
    ) -> int:
        """Register directories as drop targets, nested as they are on disk."""
        self._settings = _settings
        added = 0
        ordered = sorted(folders, key=lambda path: _folder_depth(path, root))
        for path in ordered:
            parent_node = None
            key = path.name
            if root is not None:
                try:
                    relative = path.relative_to(root)
                except ValueError:
                    relative = Path(path.name)
                if path != root:
                    key = relative.as_posix()
                    parent_rel = relative.parent
                    if parent_rel == Path("."):
                        parent_node = self._folder_by_key(root.name)
                    else:
                        parent_node = self._folder_by_key(parent_rel.as_posix())
            if self._folder_by_key(key) is not None:
                continue
            if self._child_folder(parent_node, path.name) is not None:
                continue
            self._ensure_folder(
                path.name, folder_platform(path),
                parent=parent_node, key=key, kind=folder_kind(path),
            )
            added += 1
        if added:
            self._sort_tree()
            self.queue_changed.emit()
        return added

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
            self._reveal_part_column()
            self._sort_tree()
            self.queue_changed.emit()
        return added

    @staticmethod
    def _with_switch_metadata(path: Path, fmt: CompressionFormat, options: dict) -> dict:
        if fmt != CompressionFormat.NSZ and not is_switch_rom(path):
            return options
        options.setdefault("game_group", normalize_game_name(path))
        options.setdefault("content_type", detect_content_type(path).value)
        if family := title_family(path):
            options.setdefault("title_family", family)
        return options

    def _already_queued(self, path: Path, member: str = "") -> bool:
        return (path, member) in self._queued

    def files(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            node = stack.pop(0)
            if self._is_file(node):
                found.append(node)
            for i in range(node.childCount()):
                stack.append(node.child(i))
        return found

    def rowCount(self) -> int:
        """How many files will run. Empty folder nodes are not files."""
        return len(self.files())

    def item(self, row: int, column: int = 0) -> _ColumnView | None:
        files = self.files()
        if 0 <= row < len(files):
            return _ColumnView(files[row], column)
        return None

    def file_at(self, item_id: int) -> QTreeWidgetItem | None:
        return self._by_id.get(item_id)

    def _reindex(self) -> None:
        self._queued = set()
        self._by_id = {}
        self._total_bytes = 0
        for node in self.files():
            path = node.data(self.COL_FILE, _ROLE_PATH)
            member = node.data(self.COL_FILE, _ROLE_MEMBER) or ""
            item_id = node.data(self.COL_FILE, _ROLE_ID)
            if path is not None:
                self._queued.add((path, member))
            if item_id is not None:
                self._by_id[item_id] = node
            sort = node.data(self.COL_SIZE, _ROLE_SORT)
            if isinstance(sort, (int, float)) and sort > 0:
                self._total_bytes += int(sort)

    def _reveal_part_column(self) -> None:
        has_parts = any(node.text(self.COL_TYPE) for node in self.files())
        self.setColumnHidden(self.COL_TYPE, not has_parts)

    def _is_file(self, node: QTreeWidgetItem | None) -> bool:
        return bool(node) and node.data(self.COL_FILE, _ROLE_KIND) == _KIND_FILE

    def _is_folder(self, node: QTreeWidgetItem | None) -> bool:
        return bool(node) and node.data(self.COL_FILE, _ROLE_KIND) == _KIND_FOLDER

    def _is_game_node(self, node: QTreeWidgetItem | None) -> bool:
        if not self._is_folder(node):
            return False
        kind = node.data(self.COL_FILE, _ROLE_FOLDER_KIND)
        if kind:
            return kind == "game"
        return is_game_folder(Path(node.text(self.COL_FILE)))

    def _all_folders(self) -> list[QTreeWidgetItem]:
        found: list[QTreeWidgetItem] = []
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            node = stack.pop(0)
            if self._is_folder(node):
                found.append(node)
                for i in range(node.childCount()):
                    stack.append(node.child(i))
        return found

    def _folder_by_key(self, key: str) -> QTreeWidgetItem | None:
        for node in self._all_folders():
            if node.data(self.COL_FILE, _ROLE_FOLDER_KEY) == key:
                return node
        return None

    def _folder_named(self, name: str) -> QTreeWidgetItem | None:
        lowered = name.lower()
        for node in self._all_folders():
            if node.text(self.COL_FILE).lower() == lowered:
                return node
        return None

    def _game_folder_for_family(self, family: str) -> QTreeWidgetItem | None:
        """The game tree that already holds this Switch title id, if any."""
        if not family:
            return None
        for folder in self._all_folders():
            if not self._is_game_node(folder):
                continue
            if folder.data(self.COL_FILE, _ROLE_TITLE_FAMILY) == family:
                return folder
            for i in range(folder.childCount()):
                child = folder.child(i)
                options = child.data(self.COL_FILE, _ROLE_OPTIONS) or {}
                if str(options.get("title_family", "")) == family:
                    return folder
        return None

    def _game_folder_for_name_prefix(
        self, game_group: str, platform: str = "",
    ) -> tuple[QTreeWidgetItem | None, str]:
        """Join the tree whose base title is this name's header.

        Rule: if a folder (or a Base row inside it) is titled `Ys X Nordics`,
        every `Ys X Nordics … anything` file goes there. Prefer the shortest
        header so a base owns its DLC, not the other way around.
        """
        needle = game_group.strip()
        if not needle:
            return None, ""
        best: QTreeWidgetItem | None = None
        best_header = ""
        best_len = 10**9
        for folder in self._all_folders():
            if not self._is_game_node(folder):
                continue
            folder_platform = folder.data(self.COL_FILE, _ROLE_PLATFORM) or ""
            if platform and folder_platform and folder_platform != platform:
                continue
            headers = [Path(folder.text(self.COL_FILE)).stem]
            for i in range(folder.childCount()):
                child = folder.child(i)
                if not self._is_file(child):
                    continue
                part = (child.text(self.COL_TYPE) or "").strip().casefold()
                if part == "base":
                    group = child.text(self.COL_GAME).strip()
                    if group:
                        headers.append(group)
            for header in headers:
                if not header or not titles_share_game(needle, header):
                    continue
                short = canonical_title(needle, header) or header
                if len(short) < best_len:
                    best = folder
                    best_header = short
                    best_len = len(short)
        if best is None:
            return None, ""
        return best, best_header

    def _child_folder(
        self, parent: QTreeWidgetItem | None, name: str,
    ) -> QTreeWidgetItem | None:
        if parent is None:
            for i in range(self.topLevelItemCount()):
                node = self.topLevelItem(i)
                if self._is_folder(node) and node.text(self.COL_FILE) == name:
                    return node
            return None
        for i in range(parent.childCount()):
            node = parent.child(i)
            if self._is_folder(node) and node.text(self.COL_FILE) == name:
                return node
        return None

    def _find_folder(self, name: str) -> QTreeWidgetItem | None:
        return self._folder_named(name)

    def _platform_node_for(self, item: QueueItem) -> QTreeWidgetItem | None:
        """The imported platform folder this file belongs under, if any."""
        names: list[str] = []
        for part in item.path.parts:
            if part.lower() in FOLDER_TO_PLATFORM:
                names.append(part)
        for name in reversed(names):
            found = self._folder_named(name)
            if found is not None:
                return found
        if item.platform:
            found = self._folder_named(item.platform)
            if found is not None:
                return found
        return None

    def _ensure_folder(
        self,
        name: str,
        platform: str = "",
        parent: QTreeWidgetItem | None = None,
        key: str = "",
        kind: str = "game",
    ) -> QTreeWidgetItem:
        if parent is not None and not key:
            parent_key = parent.data(self.COL_FILE, _ROLE_FOLDER_KEY) or parent.text(
                self.COL_FILE)
            key = f"{parent_key}/{name}"
        key = key or name
        existing = self._folder_by_key(key) or self._child_folder(parent, name)
        if existing is not None:
            if platform and not existing.data(self.COL_FILE, _ROLE_PLATFORM):
                existing.setData(self.COL_FILE, _ROLE_PLATFORM, platform)
            return existing
        node = QTreeWidgetItem()
        node.setText(self.COL_FILE, name)
        node.setData(self.COL_FILE, _ROLE_KIND, _KIND_FOLDER)
        node.setData(self.COL_FILE, _ROLE_FOLDER_KIND, kind)
        node.setData(self.COL_FILE, _ROLE_FOLDER_KEY, key)
        node.setData(self.COL_FILE, _ROLE_PLATFORM, platform)
        flags = (
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled)
        if kind == "game":
            flags |= Qt.ItemFlag.ItemIsDragEnabled
        node.setFlags(flags)
        font = node.font(self.COL_FILE)
        font.setBold(True)
        node.setFont(self.COL_FILE, font)
        node.setText(self.COL_PLATFORM, _platform_label(platform))
        if kind == "game":
            node.setText(self.COL_STATUS, "Empty — drop files here")
            node.setToolTip(
                self.COL_FILE, "Drop a ROM here to put it in this game's folder.")
        elif kind == "platform":
            node.setText(self.COL_STATUS, "Empty — drop files here")
            node.setToolTip(
                self.COL_FILE,
                "This is the ES-DE folder for that system. Drop a ROM here to "
                "assign it.")
        else:
            node.setText(self.COL_STATUS, "Empty — drop files here")
            node.setToolTip(self.COL_FILE, "Drop a ROM here to put it in this folder.")
        if parent is None:
            self.addTopLevelItem(node)
        else:
            parent.addChild(node)
            parent.setExpanded(True)
        node.setExpanded(True)
        return node

    def _append(self, item: QueueItem) -> None:
        node = QTreeWidgetItem()
        node.setData(self.COL_FILE, _ROLE_KIND, _KIND_FILE)
        item_id = self._next_id
        self._next_id += 1
        node.setData(self.COL_FILE, _ROLE_ID, item_id)
        node.setFlags(
            Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled)
        self._write(node, item)

        group = group_folder_name(item, self._settings)
        family = str((item.tool_options or {}).get("title_family", ""))
        if family:
            matched = self._game_folder_for_family(family)
            if matched is not None:
                group = matched.text(self.COL_FILE)
        elif item.game_group:
            matched, shared = self._game_folder_for_name_prefix(
                item.game_group, item.platform)
            if matched is not None:
                group = matched.text(self.COL_FILE)
                if shared:
                    suffix = Path(group).suffix
                    wanted = f"{shared}{suffix}"
                    if wanted.casefold() != group.casefold():
                        old_key = matched.data(self.COL_FILE, _ROLE_FOLDER_KEY) or ""
                        matched.setText(self.COL_FILE, wanted)
                        if old_key:
                            parent_key, sep, _ = old_key.rpartition("/")
                            matched.setData(
                                self.COL_FILE, _ROLE_FOLDER_KEY,
                                f"{parent_key}/{wanted}" if sep else wanted,
                            )
                        group = wanted
        platform_node = self._platform_node_for(item)
        if group:
            folder = self._ensure_folder(
                group, item.platform, parent=platform_node, kind="game")
            if family:
                folder.setData(self.COL_FILE, _ROLE_TITLE_FAMILY, family)
            anchor = str((item.tool_options or {}).get("disk_anchor", "") or "")
            if anchor:
                folder.setData(self.COL_FILE, _ROLE_DISK_ANCHOR, anchor)
                self._seed_on_disk_rows(Path(anchor), item.platform, folder)
            folder.addChild(node)
            folder.setExpanded(True)
            assign_to_folder(item, folder.text(self.COL_FILE), self._settings,
                             platform=item.platform)
            if anchor:
                options = dict(item.tool_options or {})
                options["disk_anchor"] = anchor
                options["game_folder"] = folder.text(self.COL_FILE)
                item.tool_options = options
                if item.format is not None:
                    item.output = output_for(
                        item.path, item.format, item.mode, self._settings, options,
                        item.platform, item.member)
            self._write(node, item)
            self._align_folder(folder)
        elif platform_node is not None:
            platform_node.addChild(node)
            platform_node.setExpanded(True)
        else:
            self.addTopLevelItem(node)

        self._by_id[item_id] = node
        size = item.source_bytes if item.source_bytes > 0 else 0
        if size <= 0:
            try:
                size = item.path.stat().st_size
            except OSError:
                size = 0
        self._queued.add((item.path, item.member))
        self._total_bytes += max(0, size)
        self._numeric(node, self.COL_SIZE, human_size(size), size)
        self._numeric(node, self.COL_SAVED, "", -1)
        self._refresh_item(node)
        self.update_status(item_id, item.status)
        parent = node.parent()
        if parent is not None:
            self._refresh_folder_status(parent)

    def _write(self, node: QTreeWidgetItem, item: QueueItem) -> None:
        grouped = self._is_folder(node.parent())
        caption = item.source_name if grouped and not item.member else item.display_name
        if grouped and item.member:
            caption = item.display_name.rsplit("/", 1)[-1]
        node.setText(self.COL_FILE, caption)
        node.setData(self.COL_FILE, _ROLE_PATH, item.path)
        node.setData(self.COL_FILE, _ROLE_OPTIONS, item.tool_options or {})
        node.setData(self.COL_FILE, _ROLE_MEMBER, item.member)
        node.setData(self.COL_FILE, _ROLE_LABEL, item.label)
        node.setText(self.COL_GAME, item.game_group)
        part = item.content_type or disc_part(item.source_name)
        node.setText(self.COL_TYPE, part)
        node.setData(self.COL_PLATFORM, _ROLE_PLATFORM, item.platform)
        node.setData(self.COL_BECOMES, _ROLE_PATH, item.output)
        node.setData(self.COL_BECOMES, _ROLE_FORMAT, item.format.value if item.format else "")
        node.setData(self.COL_BECOMES, _ROLE_MODE, item.mode.value)

    def _read(self, node: QTreeWidgetItem) -> QueueItem:
        name = node
        sort = node.data(self.COL_SIZE, _ROLE_SORT)
        source_bytes = int(sort) if isinstance(sort, (int, float)) and sort > 0 else 0
        return QueueItem(
            path=name.data(self.COL_FILE, _ROLE_PATH),
            format=self._format_of(node),
            mode=ConversionMode(node.data(self.COL_BECOMES, _ROLE_MODE)
                                or ConversionMode.COMPRESS.value),
            platform=node.data(self.COL_PLATFORM, _ROLE_PLATFORM) or "",
            output=node.data(self.COL_BECOMES, _ROLE_PATH) or Path(),
            tool_options=name.data(self.COL_FILE, _ROLE_OPTIONS) or {},
            game_group=node.text(self.COL_GAME),
            content_type=node.text(self.COL_TYPE),
            member=name.data(self.COL_FILE, _ROLE_MEMBER) or "",
            source_bytes=source_bytes,
            label=name.data(self.COL_FILE, _ROLE_LABEL) or "",
        )

    def _numeric(self, node: QTreeWidgetItem, column: int, text: str, sort_value: float) -> None:
        node.setText(column, text)
        node.setFont(column, self._mono)
        node.setTextAlignment(column, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        node.setData(column, _ROLE_SORT, sort_value)

    def _format_of(self, node: QTreeWidgetItem) -> CompressionFormat | None:
        raw = node.data(self.COL_BECOMES, _ROLE_FORMAT)
        try:
            return CompressionFormat(raw)
        except ValueError:
            return None

    def _align_folder(self, folder: QTreeWidgetItem) -> None:
        """The folder's name is the primary file's name. Rename the node if
        conversion changed the extension (nsp folder, nsz output)."""
        if not self._is_game_node(folder):
            self._refresh_folder_status(folder)
            self._refresh_folder_becomes(folder)
            return
        # A folder locked to one already on the card keeps that name.
        if folder.data(self.COL_FILE, _ROLE_DISK_ANCHOR):
            self._refresh_folder_status(folder)
            self._refresh_folder_becomes(folder)
            return
        new_name = ""
        for i in range(folder.childCount()):
            child = folder.child(i)
            if not self._is_file(child):
                continue
            output = child.data(self.COL_BECOMES, _ROLE_PATH)
            if isinstance(output, Path) and is_game_folder(output.parent):
                options = child.data(self.COL_FILE, _ROLE_OPTIONS) or {}
                content = str(options.get("content_type", "")).lower()
                if content not in ("update", "dlc"):
                    new_name = output.parent.name
                    break
        if new_name and folder.text(self.COL_FILE) != new_name:
            old_key = folder.data(self.COL_FILE, _ROLE_FOLDER_KEY) or ""
            folder.setText(self.COL_FILE, new_name)
            if old_key:
                parent_key, sep, _ = old_key.rpartition("/")
                folder.setData(
                    self.COL_FILE, _ROLE_FOLDER_KEY,
                    f"{parent_key}/{new_name}" if sep else new_name,
                )
            for i in range(folder.childCount()):
                child = folder.child(i)
                if not self._is_file(child):
                    continue
                item = self._read(child)
                assign_to_folder(
                    item, new_name, self._settings, platform=item.platform)
                self._write(child, item)
                self._refresh_item(child)
        self._refresh_folder_status(folder)
        self._refresh_folder_becomes(folder)

    def _refresh_folder_becomes(self, folder: QTreeWidgetItem) -> None:
        """Show a shared Becomes label on the game row when every child agrees."""
        if not self._is_game_node(folder):
            return
        labels: list[str] = []
        for i in range(folder.childCount()):
            child = folder.child(i)
            if self._is_file(child):
                text = child.text(self.COL_BECOMES).strip()
                if text:
                    labels.append(text)
        if not labels:
            folder.setText(self.COL_BECOMES, "")
            return
        unique = sorted(set(labels))
        folder.setText(self.COL_BECOMES, unique[0] if len(unique) == 1 else "Mixed")

    def _rows_for_becomes_target(self, node: QTreeWidgetItem) -> list[int]:
        """File rows a Becomes/Platform click on `node` should change.

        A game folder click covers every convertible child. When several game
        folders are selected, every selected folder's children are included.
        """
        files = self.files()
        if self._is_file(node):
            try:
                row = files.index(node)
            except ValueError:
                return []
            return self._target_rows(row)

        folders = [n for n in self.selectedItems() if self._is_game_node(n)]
        if node not in folders or len(folders) <= 1:
            folders = [node] if self._is_game_node(node) else []
        rows: list[int] = []
        seen: set[int] = set()
        for folder in folders:
            for i in range(folder.childCount()):
                child = folder.child(i)
                if not self._is_file(child):
                    continue
                try:
                    row = files.index(child)
                except ValueError:
                    continue
                if row in seen:
                    continue
                seen.add(row)
                rows.append(row)
        return rows

    def _file_count(self, folder: QTreeWidgetItem) -> int:
        n = 0
        for i in range(folder.childCount()):
            child = folder.child(i)
            if self._is_file(child):
                n += 1
            elif self._is_folder(child):
                n += self._file_count(child)
        return n

    def _refresh_folder_status(self, folder: QTreeWidgetItem) -> None:
        n = self._file_count(folder)
        folder.setText(
            self.COL_STATUS,
            "Empty — drop files here" if n == 0 else f"{n} file{'s' if n != 1 else ''}")
        parent = folder.parent()
        if parent is not None and self._is_folder(parent):
            self._refresh_folder_status(parent)

    def _sort_tree(self) -> None:
        """Empty folders last at every level, so filled titles stay in view."""
        folders = self._all_folders()
        self._sort_siblings(None)
        for folder in folders:
            self._sort_siblings(folder)

    def _sort_siblings(self, parent: QTreeWidgetItem | None) -> None:
        if parent is None:
            nodes = [self.takeTopLevelItem(0) for _ in range(self.topLevelItemCount())]
        else:
            nodes = [parent.takeChild(0) for _ in range(parent.childCount())]
        nodes.sort(key=self._sibling_sort_key)
        for node in nodes:
            if parent is None:
                self.addTopLevelItem(node)
            else:
                parent.addChild(node)

    def _sibling_sort_key(self, node: QTreeWidgetItem) -> tuple[bool, str]:
        empty = self._is_folder(node) and self._file_count(node) == 0
        return (empty, node.text(self.COL_FILE).casefold())

    # ------------------------------------------------------------ row reading

    def row_format(self, row: int) -> CompressionFormat | None:
        files = self.files()
        return self._format_of(files[row]) if 0 <= row < len(files) else None

    def row_mode(self, row: int) -> ConversionMode:
        return ConversionMode(self.files()[row].data(self.COL_BECOMES, _ROLE_MODE))

    def row_platform(self, row: int) -> str:
        return self.files()[row].data(self.COL_PLATFORM, _ROLE_PLATFORM) or ""

    def row_item(self, row: int) -> QueueItem:
        return self._read(self.files()[row])

    def queue_items(self) -> list[tuple[int, QueueItem]]:
        items = []
        for node in self.files():
            item_id = node.data(self.COL_FILE, _ROLE_ID)
            items.append((item_id, self._read(node)))
        return items

    def formats_in_queue(self) -> list[CompressionFormat]:
        seen: list[CompressionFormat] = []
        for node in self.files():
            fmt = self._format_of(node)
            if fmt is not None and fmt not in seen:
                seen.append(fmt)
        return seen

    def total_input_bytes(self) -> int:
        return self._total_bytes

    def place_under(self, file_node: QTreeWidgetItem, folder: QTreeWidgetItem) -> None:
        """Put a file in a game folder. The tests and drop handler share this."""
        self._reparent(file_node, folder)
        self._sync_node(file_node)
        self._align_folder(folder)
        self._reveal_part_column()
        self.apply_empty_folder_setting()
        self.queue_changed.emit()

    # ----------------------------------------------------------- row changing

    def _refresh_item(self, node: QTreeWidgetItem) -> None:
        if not self._is_file(node):
            return
        item = self._read(node)
        fmt, mode = item.format, item.mode
        path, member, options = item.path, item.member, item.tool_options or {}
        platform = item.platform
        output = (output_for(path, fmt, mode, self._settings, options, platform, member)
                  if fmt else path)

        node.setText(self.COL_PLATFORM, _platform_label(platform) or "unknown")
        node.setToolTip(
            self.COL_PLATFORM,
            "Which ES-DE folder this file belongs to. It decides the settings, "
            "and where the result goes when a card is set as the destination.")

        info = format_info(fmt) if fmt else None
        archive = source_is_archive(path, member)
        intent = str(options.get("intent", ""))
        label = becomes_label(fmt, mode, from_archive=archive, intent=intent)
        if not label:
            label = info.label if info else "?"
            if mode == ConversionMode.DECOMPRESS and fmt is not None:
                label = f"{label} ({self._verb(fmt, mode).lower()})"
            elif fmt in _NAMED_BY_OUTPUT:
                label = output.suffix.lstrip(".").upper()
        node.setText(self.COL_BECOMES, label)
        node.setData(self.COL_BECOMES, _ROLE_PATH, output)
        node.setToolTip(self.COL_BECOMES, f"Writes:\n{output}")
        node.setToolTip(self.COL_FILE, f"{path}\n\nWrites:\n{output}")

        item.output = output
        grouped = self._is_folder(node.parent())
        caption = item.source_name if grouped and not item.member else item.display_name
        if grouped and item.member:
            caption = item.display_name.rsplit("/", 1)[-1]
        node.setText(self.COL_FILE, caption)

    def _refresh_row(self, row: int) -> None:
        self._refresh_item(self.files()[row])

    def apply_settings(self, settings: FormatSettings) -> None:
        self._settings = settings
        for node in self.files():
            self._refresh_item(node)
        self.apply_empty_folder_setting()

    def apply_empty_folder_setting(self) -> int:
        """Drop empty folder nodes when the setting is off. Returns how many
        were removed."""
        if self._settings.show_empty_folders:
            self._sort_tree()
            return 0
        removed = self._prune_empty_folders()
        if removed:
            self._sort_tree()
        return removed

    def _prune_empty_folders(self) -> int:
        folders = [f for f in self._all_folders() if self._file_count(f) == 0]
        folders.sort(key=self._depth, reverse=True)
        for folder in folders:
            self._remove_folder(folder)
        return len(folders)

    def _reset_options(self, node: QTreeWidgetItem, fmt: CompressionFormat,
                       extra: dict | None = None) -> None:
        previous = node.data(self.COL_FILE, _ROLE_OPTIONS) or {}
        options = {k: previous[k] for k in self._FORMAT_NEUTRAL if k in previous}
        options.update(self._settings.for_format(fmt))
        if extra:
            options.update(extra)
        node.setData(self.COL_FILE, _ROLE_OPTIONS, options)

    def set_format(self, rows: list[int], fmt: CompressionFormat) -> None:
        files = self.files()
        parents: set[int] = set()
        for row in rows:
            node = files[row]
            node.setData(self.COL_BECOMES, _ROLE_FORMAT, fmt.value)
            node.setData(self.COL_BECOMES, _ROLE_MODE, ConversionMode.COMPRESS.value)
            options = dict(node.data(self.COL_FILE, _ROLE_OPTIONS) or {})
            options.pop("intent", None)
            node.setData(self.COL_FILE, _ROLE_OPTIONS, options)
            self._reset_options(node, fmt)
            options = dict(node.data(self.COL_FILE, _ROLE_OPTIONS) or {})
            options.pop("intent", None)
            node.setData(self.COL_FILE, _ROLE_OPTIONS, options)
            self._refresh_item(node)
            self.update_status(node.data(self.COL_FILE, _ROLE_ID), "Waiting")
            parent = node.parent()
            if parent is not None:
                parents.add(id(parent))
        for folder in self._all_folders():
            if id(folder) in parents:
                self._align_folder(folder)
        self.queue_changed.emit()

    def set_mode(self, rows: list[int], mode: ConversionMode, *, intent: str = "") -> None:
        files = self.files()
        parents: set[int] = set()
        for row in rows:
            node = files[row]
            node.setData(self.COL_BECOMES, _ROLE_MODE, mode.value)
            options = dict(node.data(self.COL_FILE, _ROLE_OPTIONS) or {})
            if intent:
                options["intent"] = intent
            else:
                options.pop("intent", None)
            node.setData(self.COL_FILE, _ROLE_OPTIONS, options)
            self._refresh_item(node)
            self.update_status(node.data(self.COL_FILE, _ROLE_ID), "Waiting")
            parent = node.parent()
            if parent is not None:
                parents.add(id(parent))
        for folder in self._all_folders():
            if id(folder) in parents:
                self._align_folder(folder)
        self.queue_changed.emit()

    def apply_format_options(self, fmt: CompressionFormat, options: dict) -> int:
        changed = 0
        for node in self.files():
            if self._format_of(node) != fmt:
                continue
            merged = dict(node.data(self.COL_FILE, _ROLE_OPTIONS) or {})
            merged.update(options)
            node.setData(self.COL_FILE, _ROLE_OPTIONS, merged)
            self._refresh_item(node)
            changed += 1
        return changed

    def _supports_reverse(self, row: int) -> bool:
        node = self.files()[row]
        fmt = self._format_of(node)
        if fmt is None:
            return False
        path = node.data(self.COL_FILE, _ROLE_PATH)
        member = node.data(self.COL_FILE, _ROLE_MEMBER) or ""
        return supports_reverse(
            fmt, from_archive=source_is_archive(path, member))

    @staticmethod
    def _verb(fmt: CompressionFormat, mode: ConversionMode) -> str:
        for info in FORMAT_MODES.get(fmt, ()):
            if info.mode == mode:
                return info.description
        return "Convert"

    # --------------------------------------------------------------- results

    def update_status(self, row: int, status: str, message: str = "") -> None:
        node = self._by_id.get(row)
        if node is None:
            files = self.files()
            if 0 <= row < len(files):
                node = files[row]
        if node is None:
            return
        node.setText(self.COL_STATUS, status)
        node.setForeground(self.COL_STATUS, QBrush(theme.color(
            self._STATUS_COLOURS.get(status, "text"))))
        if message:
            node.setToolTip(self.COL_STATUS, message)
            node.setToolTip(self.COL_FILE, message)

    def record_result(self, row: int, input_size: int, output_size: int) -> None:
        node = self._by_id.get(row) or (self.files()[row] if row < len(self.files()) else None)
        if node is None:
            return
        if input_size <= 0 or output_size <= 0:
            node.setText(self.COL_SAVED, "-")
            return
        saved = input_size - output_size
        percent = saved * 100 / input_size
        node.setText(self.COL_SAVED, f"{percent:.0f}%" if saved > 0 else f"+{-percent:.0f}%")
        node.setData(self.COL_SAVED, _ROLE_SORT, percent)
        node.setToolTip(
            self.COL_SAVED,
            f"{human_size(input_size)} -> {human_size(output_size)}"
            f"   ({'saved' if saved > 0 else 'grew by'} {human_size(abs(saved))})")
        node.setForeground(self.COL_SAVED, QBrush(theme.color("ok" if saved > 0 else "warn")))

    def refresh_colours(self) -> None:
        for node in self.files():
            status = node.text(self.COL_STATUS)
            node.setForeground(self.COL_STATUS, QBrush(theme.color(
                self._STATUS_COLOURS.get(status, "text"))))
            text = node.text(self.COL_SAVED)
            if text and text != "-":
                node.setForeground(self.COL_SAVED, QBrush(
                    theme.color("warn" if text.startswith("+") else "ok")))

    # -------------------------------------------------------------- removing

    def selected_rows(self) -> list[int]:
        files = self.files()
        chosen = set(self.selectedItems())
        return [i for i, node in enumerate(files) if node in chosen]

    def remove_selected(self) -> None:
        selected = list(self.selectedItems())
        if not selected:
            return
        folders = [n for n in selected if self._is_folder(n)]
        files = [n for n in selected if self._is_file(n)]
        folders.sort(key=self._depth, reverse=True)
        removed: set[int] = set()
        for folder in folders:
            if id(folder) in removed:
                continue
            self._collect_ids(folder, removed)
            self._remove_folder(folder)
        remaining = {id(n) for n in self.files()}
        for node in files:
            if id(node) in remaining and id(node) not in removed:
                self._remove_file(node)
        self._reindex()
        self._reveal_part_column()
        self.apply_empty_folder_setting()
        self.queue_changed.emit()

    def _depth(self, node: QTreeWidgetItem) -> int:
        depth = 0
        parent = node.parent()
        while parent is not None:
            depth += 1
            parent = parent.parent()
        return depth

    def _collect_ids(self, folder: QTreeWidgetItem, into: set[int]) -> None:
        into.add(id(folder))
        for i in range(folder.childCount()):
            child = folder.child(i)
            into.add(id(child))
            if self._is_folder(child):
                self._collect_ids(child, into)

    def _remove_folder(self, folder: QTreeWidgetItem) -> None:
        for i in range(folder.childCount() - 1, -1, -1):
            child = folder.child(i)
            if self._is_folder(child):
                self._remove_folder(child)
            else:
                self._remove_file(child)
        parent = folder.parent()
        if parent is None:
            index = self.indexOfTopLevelItem(folder)
            if index >= 0:
                self.takeTopLevelItem(index)
        else:
            parent.removeChild(folder)
            self._refresh_folder_status(parent)

    def _remove_file(self, node: QTreeWidgetItem) -> None:
        parent = node.parent()
        if parent is None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(node))
        else:
            parent.removeChild(node)
            self._refresh_folder_status(parent)

    def clear_queue(self) -> None:
        self.clear()
        self._queued.clear()
        self._by_id.clear()
        self._total_bytes = 0
        self._next_id = 1
        self.queue_changed.emit()

    # ---------------------------------------------------------- drag and drop

    def dragMoveEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        if target is None or self._is_folder(target) or self._is_file(target):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        games = [n for n in self.selectedItems() if self._is_game_node(n)]
        files = [n for n in self.selectedItems() if self._is_file(n)]
        folder = self._drop_folder(target)
        if games and folder is not None and self._is_game_node(folder):
            for source in games:
                if source is folder:
                    continue
                self.merge_game_folders(source, folder)
            event.accept()
            self.apply_empty_folder_setting()
            self.queue_changed.emit()
            return
        if not files:
            event.ignore()
            return
        for node in list(files):
            self._reparent(node, folder)
            self._sync_node(node)
        if folder is not None:
            self._align_folder(folder)
            for node in files:
                actual = node.parent()
                if actual is not None and actual is not folder:
                    self._align_folder(actual)
        self._reveal_part_column()
        event.accept()
        self.apply_empty_folder_setting()
        self.queue_changed.emit()

    def merge_game_folders(
        self, source: QTreeWidgetItem, target: QTreeWidgetItem,
    ) -> None:
        """Move every file from `source` into `target`; keep target's name."""
        if not self._is_game_node(source) or not self._is_game_node(target):
            return
        if source is target:
            return
        src_plat = source.data(self.COL_FILE, _ROLE_PLATFORM) or ""
        dst_plat = target.data(self.COL_FILE, _ROLE_PLATFORM) or ""
        if src_plat and dst_plat and src_plat != dst_plat:
            return
        children = [source.child(i) for i in range(source.childCount())]
        for child in children:
            if not self._is_file(child):
                continue
            self._reparent(child, target)
            self._sync_node(child)
        self._remove_folder(source)
        self._align_folder(target)
        self._reveal_part_column()
        self.apply_empty_folder_setting()
        self.queue_changed.emit()

    def rename_game_folder(self, folder: QTreeWidgetItem, new_stem: str) -> bool:
        """Rename the queue game node and, when anchored, the folder on disk."""
        if not self._is_game_node(folder):
            return False
        stem = safe_folder_name(new_stem) or new_stem.strip()
        if not stem:
            return False
        old_name = folder.text(self.COL_FILE)
        new_name = f"{stem}{Path(old_name).suffix}"
        if new_name == old_name:
            return True
        anchor = folder.data(self.COL_FILE, _ROLE_DISK_ANCHOR) or ""
        if anchor:
            disk = Path(anchor)
            if disk.is_dir():
                try:
                    renamed = rename_disk_game_folder(disk, stem)
                except OSError as exc:
                    QMessageBox.warning(
                        self, "Could not rename",
                        f"The folder on disk could not be renamed.\n\n{exc}")
                    return False
                try:
                    folder.setData(
                        self.COL_FILE, _ROLE_DISK_ANCHOR, str(renamed.resolve()))
                except OSError:
                    folder.setData(self.COL_FILE, _ROLE_DISK_ANCHOR, str(renamed))
                anchor = folder.data(self.COL_FILE, _ROLE_DISK_ANCHOR) or ""
        old_key = folder.data(self.COL_FILE, _ROLE_FOLDER_KEY) or ""
        folder.setText(self.COL_FILE, new_name)
        if old_key:
            parent_key, sep, _ = old_key.rpartition("/")
            folder.setData(
                self.COL_FILE, _ROLE_FOLDER_KEY,
                f"{parent_key}/{new_name}" if sep else new_name,
            )
        for i in range(folder.childCount()):
            child = folder.child(i)
            if not self._is_file(child):
                continue
            item = self._read(child)
            if anchor:
                disk = Path(anchor)
                # Primary ROM was renamed with the folder; DLC/update keep names.
                if item.path.name == old_name:
                    item.path = disk / new_name
                elif item.path.parent.name == old_name or (
                        item.tool_options or {}).get("on_disk"):
                    item.path = disk / item.path.name
                if item.format is None:
                    item.output = item.path
            assign_to_folder(
                item, new_name, self._settings, platform=item.platform)
            if anchor:
                options = dict(item.tool_options or {})
                options["disk_anchor"] = anchor
                options["game_folder"] = new_name
                item.tool_options = options
                if item.format is not None:
                    item.output = output_for(
                        item.path, item.format, item.mode, self._settings, options,
                        item.platform, item.member)
            self._write(child, item)
            self._refresh_item(child)
        self._align_folder(folder)
        self._reindex()
        self.queue_changed.emit()
        return True

    def _prompt_rename_folder(self, folder: QTreeWidgetItem) -> None:
        current = Path(folder.text(self.COL_FILE)).stem
        text, ok = QInputDialog.getText(
            self, "Rename game folder",
            "Name (extension stays the same):", text=current)
        if ok and text.strip():
            self.rename_game_folder(folder, text.strip())

    def _drop_folder(self, target: QTreeWidgetItem | None) -> QTreeWidgetItem | None:
        if target is None:
            return None
        if self._is_folder(target):
            return target
        parent = target.parent()
        return parent if self._is_folder(parent) else None

    def _reparent(self, node: QTreeWidgetItem, folder: QTreeWidgetItem | None) -> None:
        parent = node.parent()
        if parent is None:
            self.takeTopLevelItem(self.indexOfTopLevelItem(node))
        else:
            parent.removeChild(node)
            self._refresh_folder_status(parent)
        if folder is None:
            self.addTopLevelItem(node)
        else:
            folder.addChild(node)
            folder.setExpanded(True)
            self._refresh_folder_status(folder)

    def _sync_node(self, node: QTreeWidgetItem) -> None:
        item = self._read(node)
        parent = node.parent()
        if self._is_game_node(parent):
            platform = parent.data(self.COL_FILE, _ROLE_PLATFORM) or item.platform
            assign_to_folder(item, parent.text(self.COL_FILE), self._settings,
                             platform=platform)
        elif self._is_folder(parent):
            platform = parent.data(self.COL_FILE, _ROLE_PLATFORM) or item.platform
            if platform:
                item.platform = platform
            if self._settings.game_folders and item.format is not None:
                options = dict(item.tool_options or {})
                options.pop("game_folder", None)
                item.tool_options = options
                item.output = output_for(
                    item.path, item.format, item.mode, self._settings, options,
                    platform, item.member)
                group = group_folder_name(item, self._settings)
                if group:
                    game = self._ensure_folder(
                        group, platform, parent=parent, kind="game")
                    self._reparent(node, game)
                    assign_to_folder(
                        item, game.text(self.COL_FILE), self._settings,
                        platform=platform)
                else:
                    unassign(item, self._settings)
                    item.platform = platform
            else:
                unassign(item, self._settings)
                item.platform = platform
        else:
            unassign(item, self._settings)
        self._write(node, item)
        self._refresh_item(node)

    # ---------------------------------------------------------- context menu

    def _target_rows(self, row: int) -> list[int]:
        rows = self.selected_rows()
        return rows if row in rows and len(rows) > 1 else [row]

    def _accepted_formats(self, row: int):
        node = self.files()[row]
        path: Path = node.data(self.COL_FILE, _ROLE_PATH)
        member = node.data(self.COL_FILE, _ROLE_MEMBER) or ""
        extension = (Path(member).suffix if member else path.suffix).lower()
        return [info for info in FORMAT_CATALOG if extension in info.extensions]

    def set_platform(self, rows: list[int], platform: str) -> None:
        files = self.files()
        parents: set[int] = set()
        for row in rows:
            node = files[row]
            node.setData(self.COL_PLATFORM, _ROLE_PLATFORM, platform)
            preset = PRESETS.get(platform)
            if preset is not None and preset.format in {
                    i.format for i in self._accepted_formats(row)}:
                node.setData(self.COL_BECOMES, _ROLE_FORMAT, preset.format.value)
                node.setData(self.COL_BECOMES, _ROLE_MODE, ConversionMode.COMPRESS.value)
                self._reset_options(node, preset.format, preset.options)
                options = dict(node.data(self.COL_FILE, _ROLE_OPTIONS) or {})
                options.pop("intent", None)
                node.setData(self.COL_FILE, _ROLE_OPTIONS, options)
            self._refresh_item(node)
            self.update_status(node.data(self.COL_FILE, _ROLE_ID), "Waiting")
            parent = node.parent()
            if parent is not None:
                parents.add(id(parent))
        for folder in self._all_folders():
            if id(folder) in parents:
                self._align_folder(folder)
        self.queue_changed.emit()

    def _add_platform_actions(self, menu: QMenu, row: int, rows: list[int]) -> bool:
        move = QAction("Move only", self, checkable=True)
        move.setChecked(self.row_mode(row) == ConversionMode.MOVE
                        and not (self.row_item(row).tool_options or {}).get("intent"))
        move.setToolTip("Copy the file into its game folder with no conversion.")
        move.triggered.connect(
            lambda _c=False, r=rows: self.set_mode(r, ConversionMode.MOVE))
        menu.addAction(move)
        menu.addSeparator()

        current = self.row_platform(row)
        accepted = {info.format for info in self._accepted_formats(row)}
        suggested = [p for p in PRESETS if p.format in accepted]
        for preset in suggested:
            action = QAction(preset.label, self, checkable=True)
            action.setChecked(preset.platform == current
                              and self.row_mode(row) != ConversionMode.MOVE)
            if preset.note:
                action.setToolTip(preset.note)
            action.triggered.connect(
                lambda _c, name=preset.platform, r=rows: self.set_platform(r, name))
            menu.addAction(action)
        if suggested:
            menu.addSeparator()
        for group_name, platforms in PLATFORM_MENU_GROUPS:
            submenu = menu.addMenu(group_name)
            for platform in platforms:
                action = QAction(_platform_label(platform), self, checkable=True)
                action.setChecked(platform == current
                                  and self.row_mode(row) != ConversionMode.MOVE)
                folders = ESDE_PLATFORM_FOLDERS.get(platform, (platform,))
                extra = f"ES-DE folder: {', '.join(folders)}"
                preset = PRESETS.get(platform)
                action.setToolTip(
                    f"{preset.note}\n{extra}" if preset and preset.note else extra)
                action.triggered.connect(
                    lambda _c, name=platform, r=rows: self.set_platform(r, name))
                submenu.addAction(action)
        return True

    def _add_format_actions(self, menu: QMenu, row: int, rows: list[int]) -> bool:
        current = self.row_format(row)
        node = self.files()[row]
        path = node.data(self.COL_FILE, _ROLE_PATH)
        member = node.data(self.COL_FILE, _ROLE_MEMBER) or ""
        archive = source_is_archive(path, member)
        intent = str((node.data(self.COL_FILE, _ROLE_OPTIONS) or {}).get("intent", ""))
        mode = self.row_mode(row)

        move = QAction("Move only", self, checkable=True)
        move.setChecked(mode == ConversionMode.MOVE and intent != "unzip")
        move.setToolTip("Copy the file into its game folder with no conversion.")
        move.triggered.connect(
            lambda _c=False, r=rows: self.set_mode(r, ConversionMode.MOVE))
        menu.addAction(move)
        menu.addSeparator()

        offered = self._accepted_formats(row)
        for info in offered:
            action = QAction(f"{info.label}    {info.platform}", self, checkable=True)
            action.setChecked(
                info.format == current and mode == ConversionMode.COMPRESS)
            action.setToolTip(info.reason)
            action.triggered.connect(lambda _c, f=info.format, r=rows: self.set_format(r, f))
            menu.addAction(action)

        if current is not None and self._supports_reverse(row):
            menu.addSeparator()
            verb = reverse_verb(current, from_archive=archive)
            target = reverse_mode(current, from_archive=archive)
            reverse = QAction(f"{verb} instead of convert", self, checkable=True)
            if target is ConversionMode.MOVE:
                reverse.setChecked(mode == ConversionMode.MOVE and intent == "unzip")
            else:
                reverse.setChecked(mode == ConversionMode.DECOMPRESS)
            reverse.setToolTip(
                "Extract the archive member without compressing."
                if archive else
                "Turn an already-compressed file back into the original.")
            reverse.triggered.connect(
                lambda checked, r=rows, t=target, a=archive: self.set_mode(
                    r, t if checked else ConversionMode.COMPRESS,
                    intent="unzip" if (checked and a and t is ConversionMode.MOVE) else "",
                ))
            menu.addAction(reverse)
        return bool(offered) or True

    def _on_item_clicked(self, node: QTreeWidgetItem, column: int) -> None:
        if column not in self._CLICKABLE:
            return
        rows = self._rows_for_becomes_target(node)
        if not rows:
            return
        if column != self.COL_PLATFORM:
            rows = [r for r in rows if self.row_format(r) is not None]
            if not rows:
                return
        row = rows[0]
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        filled = (self._add_platform_actions(menu, row, rows)
                  if column == self.COL_PLATFORM
                  else self._add_format_actions(menu, row, rows))
        if not filled:
            return
        rect = self.visualRect(self.indexFromItem(node, column))
        menu.exec(self.viewport().mapToGlobal(rect.bottomLeft()))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self.indexAt(event.pos())
        node = self.itemFromIndex(index) if index.isValid() else None
        clickable = False
        if node is not None and index.column() in self._CLICKABLE:
            if self._is_file(node):
                clickable = (index.column() == self.COL_PLATFORM
                             or self._format_of(node) is not None)
            elif self._is_game_node(node):
                clickable = bool(self._rows_for_becomes_target(node))
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def _show_menu(self, position: QPoint) -> None:
        node = self.itemAt(position)
        if node is None:
            menu = QMenu(self)
            expand = QAction("Expand all", self)
            expand.triggered.connect(self.expandAll)
            collapse = QAction("Collapse all", self)
            collapse.triggered.connect(self.collapseAll)
            menu.addAction(expand)
            menu.addAction(collapse)
            menu.exec(self.viewport().mapToGlobal(position))
            return
        if self._is_folder(node):
            menu = QMenu(self)
            if self._is_game_node(node):
                rename = QAction("Rename…", self)
                rename.triggered.connect(
                    lambda _c=False, n=node: self._prompt_rename_folder(n))
                menu.addAction(rename)
                menu.addSeparator()
            expand = QAction("Expand all", self)
            expand.triggered.connect(self.expandAll)
            collapse = QAction("Collapse all", self)
            collapse.triggered.connect(self.collapseAll)
            menu.addAction(expand)
            menu.addAction(collapse)
            menu.addSeparator()
            remove = QAction("Remove folder from queue", self)
            remove.triggered.connect(self.remove_selected)
            menu.addAction(remove)
            menu.exec(self.viewport().mapToGlobal(position))
            return
        files = self.files()
        try:
            row = files.index(node)
        except ValueError:
            return
        rows = self._target_rows(row)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        platform_menu = menu.addMenu("Platform")
        self._add_platform_actions(platform_menu, row, rows)

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
