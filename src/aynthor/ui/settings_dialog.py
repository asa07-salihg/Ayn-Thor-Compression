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
from PySide6.QtGui import QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
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
        self.settings = settings
        self.presets = presets
        self.touched: set[CompressionFormat] = set()
        self.presets_touched = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)

        self.categories = QListWidget()
        self.categories.setFixedWidth(190)
        body_layout.addWidget(self.categories)

        self.pages = QStackedWidget()
        # Stacked pages must not force the dialog taller than the screen;
        # each tall page scrolls inside itself instead.
        self.pages.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card = QFrame()
        card.setProperty("role", "card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self.pages)
        body_layout.addWidget(card, stretch=1)
        root.addWidget(body, stretch=1)

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
        self.footer = QFrame()
        self.footer.setProperty("role", "bar")
        self.footer.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(12, 10, 12, 10)
        footer_layout.addStretch()
        footer_layout.addWidget(buttons)
        root.addWidget(self.footer, stretch=0)

        self._fit_to_screen()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_to_screen()

    def _fit_to_screen(self) -> None:
        """Keep the dialog inside the available desktop area."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(880, 620)
            return
        avail = screen.availableGeometry()
        max_w = max(640, avail.width() - 24)
        max_h = max(420, avail.height() - 24)
        self.setMaximumSize(max_w, max_h)
        self.resize(min(880, max_w), min(620, max_h))
        frame = self.frameGeometry()
        if avail.contains(frame):
            return
        frame.moveCenter(avail.center())
        x = min(max(frame.x(), avail.x()), avail.x() + avail.width() - frame.width())
        y = min(max(frame.y(), avail.y()), avail.y() + avail.height() - frame.height())
        self.move(x, y)

    def _on_presets_changed(self) -> None:
        self.presets_touched = True

    def _add_page(
        self,
        title: str,
        fmt: CompressionFormat | None,
        panel: QWidget,
        *,
        scroll: bool = True,
    ) -> None:
        item = QListWidgetItem(title)
        if fmt is not None:
            info = format_info(fmt)
            item.setToolTip(f"{info.platform}\n\n{info.reason}")
            item.setData(_ROLE_FORMAT, fmt.value)
        self.categories.addItem(item)

        page = QWidget()
        page.setMinimumHeight(0)
        page.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
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

        if scroll:
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            holder_layout.setSpacing(10)
            holder_layout.addWidget(panel)
            holder_layout.addStretch()
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setMinimumHeight(0)
            area.setWidget(holder)
            layout.addWidget(area, stretch=1)
        else:
            layout.addWidget(panel, stretch=1)

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
