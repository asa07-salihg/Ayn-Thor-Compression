"""Settings: general options, and one page per format.

Why
    The main window has no settings on it. Options are consulted when a default
    is wrong and ignored the rest of the time, so keeping nine panels
    permanently on screen cost a third of the width to show something nobody
    was reading. They live here instead, reachable from the header and from a
    row's own context menu, which opens straight at that row's format.

    Closing with Save applies a format's page to the rows already queued, but
    only for pages that were actually touched. Applying all nine would wipe the
    per-platform values auto-detection had worked out, which is how a PS2 row
    would silently lose its NetherSX2-compatible codec.

Used by
    `ui.main_window`.

Reference
    The panels themselves: `ui.option_panels`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.formats import FORMAT_CATALOG, format_info
from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PresetTable
from aynthor.core.settings import FormatSettings
from aynthor.ui.option_panels import FormatPanels, GeneralPanel
from aynthor.ui.presets_page import PresetsPage

_ROLE_FORMAT = Qt.ItemDataRole.UserRole


class SettingsDialog(QDialog):
    def __init__(self, settings: FormatSettings, presets: PresetTable,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(880, 620)
        self.settings = settings
        self.presets = presets
        self.touched: set[CompressionFormat] = set()
        self.presets_touched = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)

        self.categories = QListWidget()
        self.categories.setFixedWidth(190)
        body.addWidget(self.categories)

        self.pages = QStackedWidget()
        body.addWidget(self._page_frame(), stretch=1)
        root.addLayout(body, stretch=1)

        self.general = GeneralPanel()
        self.general.load(settings)
        self._add_page("General", None, self.general)

        self.presets_page = PresetsPage(presets)
        self.presets_page.changed.connect(self._on_presets_changed)
        self._add_page("Platform presets", None, self.presets_page)

        self.formats = FormatPanels()
        self.formats.load(settings.options)
        self.formats.format_changed.connect(self.touched.add)
        for info in FORMAT_CATALOG:
            self._add_page(info.label, info.format, self.formats.panel(info.format))

        self.categories.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.categories.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer = QFrame()
        footer.setProperty("role", "bar")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.addStretch()
        footer_layout.addWidget(buttons)
        root.addWidget(footer)

    def _on_presets_changed(self) -> None:
        self.presets_touched = True

    def _page_frame(self) -> QWidget:
        frame = QFrame()
        frame.setProperty("role", "card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.pages)
        layout.addWidget(scroll)
        return frame

    def _add_page(self, title: str, fmt: CompressionFormat | None, panel: QWidget) -> None:
        item = QListWidgetItem(title)
        if fmt is not None:
            info = format_info(fmt)
            item.setToolTip(f"{info.platform}\n\n{info.reason}")
            item.setData(_ROLE_FORMAT, fmt.value)
        self.categories.addItem(item)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel(title if fmt is None else format_info(fmt).label)
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        if fmt is not None:
            info = format_info(fmt)
            subtitle = QLabel(f"{info.platform}. {info.reason}")
            subtitle.setWordWrap(True)
            subtitle.setProperty("role", "second")
            layout.addWidget(subtitle)

        layout.addWidget(panel)
        layout.addStretch()
        self.pages.addWidget(page)

    def show_format(self, fmt: CompressionFormat) -> None:
        for row in range(self.categories.count()):
            if self.categories.item(row).data(_ROLE_FORMAT) == fmt.value:
                self.categories.setCurrentRow(row)
                return

    def result_settings(self) -> FormatSettings:
        """The settings as edited. Call after `exec()` returned Accepted."""
        self.general.apply_to(self.settings)
        self.settings.options = self.formats.all_options()
        self.settings.keys_path = self.formats.keys_path() or self.settings.keys_path
        return self.settings

    def changed_formats(self) -> set[CompressionFormat]:
        return set(self.touched)
