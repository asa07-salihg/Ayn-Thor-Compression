"""One options panel per format, plus the general options below them.

Why
    Every tool has different flags and they are not interchangeable: chdman
    takes hunk sizes, DolphinTool takes block sizes and a codec, nsz takes a
    compression mode. Rather than one settings page full of controls that are
    greyed out most of the time, each format gets its own panel and only the
    panel for the selected format is shown.

    Values are offered as dropdowns rather than free-typed numbers because
    these flags have small sets of sensible values, and a typo in a hunk size
    fails several minutes into a run rather than immediately.

    Panels disable their compression controls in Open mode instead of hiding
    them, so the layout does not jump when the mode changes.

Used by
    `ui.main_window`.

Reference
    What each flag does, and why the defaults are what they are:
    each tool's own documentation, linked from `core.tools.manifest`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import ClassVar

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from aynthor.core.formats import FORMAT_CATALOG
from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.settings import FormatSettings


def _connect_change(widget: QWidget, slot) -> None:
    if isinstance(widget, QComboBox):
        widget.currentIndexChanged.connect(lambda *_: slot())
    elif isinstance(widget, QCheckBox):
        widget.toggled.connect(lambda *_: slot())
    elif isinstance(widget, QLineEdit):
        widget.textChanged.connect(lambda *_: slot())


def _kb_label(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes // (1024 * 1024)} MB ({num_bytes})"
    return f"{num_bytes // 1024} KB ({num_bytes})"


class BaseFormatPanel(QWidget):
    changed = Signal()

    def __init__(self, fmt: CompressionFormat) -> None:
        super().__init__()
        self.format = fmt
        self._compress_only: list[QWidget] = []

        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 2, 0, 2)
        self.form.setSpacing(8)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        info = next(i for i in FORMAT_CATALOG if i.format == fmt)
        hint = QLabel(info.notes)
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        self.form.addRow(hint)

        # There is no Mode control here. Direction belongs to the row, not to
        # the format, and is set from the queue's context menu; a panel that
        # also had a mode meant two places could disagree.
        self._build_options()
        self._make_combos_shrinkable()
        self._on_mode_changed()

    def _make_combos_shrinkable(self) -> None:
        for combo in self.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _build_options(self) -> None:
        """Subclasses add extra rows here."""

    def _track(self, widget: QWidget, compress_only: bool = True) -> QWidget:
        _connect_change(widget, self.changed.emit)
        if compress_only:
            self._compress_only.append(widget)
        return widget

    def add_row(self, label: str, widget: QWidget, compress_only: bool = True) -> QWidget:
        self._track(widget, compress_only)
        self.form.addRow(label, widget)
        return widget

    def add_int_combo(
        self,
        label: str,
        values: Iterable[int],
        default: int,
        *,
        auto: bool = False,
        auto_label: str = "Auto",
        auto_value: int = 0,
        fmt: Callable[[int], str] = str,
        compress_only: bool = True,
    ) -> QComboBox:
        combo = QComboBox()
        if auto:
            combo.addItem(auto_label, auto_value)
        for value in values:
            combo.addItem(fmt(value), value)
        idx = combo.findData(default)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        self.add_row(label, combo, compress_only)
        return combo

    def add_checkboxes(self, label: str, options: list[tuple[str, str]]) -> dict[str, QCheckBox]:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(2)
        boxes: dict[str, QCheckBox] = {}
        for i, (key, text) in enumerate(options):
            cb = QCheckBox(text)
            self._track(cb)
            boxes[key] = cb
            grid.addWidget(cb, i // 3, i % 3)
        self.form.addRow(label, container)
        return boxes

    @staticmethod
    def current_mode() -> ConversionMode:
        # Panels describe compression settings; a row that is being opened
        # simply ignores the ones that do not apply.
        return ConversionMode.COMPRESS

    def _on_mode_changed(self) -> None:
        self.changed.emit()

    # Option key -> attribute holding the widget that carries it. Declaring
    # the pairs lets one loader restore every panel, rather than nine
    # hand-written ones that drift out of step with their `options()`.
    BINDINGS: ClassVar[dict[str, str]] = {}

    def load(self, options: dict) -> None:
        for key, attribute in self.BINDINGS.items():
            if key not in options:
                continue
            widget = getattr(self, attribute, None)
            self._restore(widget, options[key])
        self.changed.emit()

    @staticmethod
    def _restore(widget, value) -> None:
        if isinstance(widget, dict):  # a group of checkboxes
            selected = set(value or ())
            for name, box in widget.items():
                box.blockSignals(True)
                box.setChecked(name in selected)
                box.blockSignals(False)
            return
        if widget is None:
            return
        widget.blockSignals(True)
        if isinstance(widget, QComboBox):
            index = widget.findData(value)
            if index < 0:
                index = widget.findText(str(value))
            if index >= 0:
                widget.setCurrentIndex(index)
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        widget.blockSignals(False)

    def options(self) -> dict:
        return {}


# Shared value lists
_LEVELS_1_22 = list(range(1, 23))
_LEVELS_0_9 = list(range(0, 10))
_THREAD_VALUES = [1, 2, 3, 4, 6, 8, 12, 16, 24, 32]
_HUNK_VALUES = [512, 1024, 2048, 4096, 8192, 16384, 19584, 32768]
_RVZ_BLOCKS = [32768, 65536, 131072, 262144, 524288, 1048576, 2097152]
_CSO_BLOCKS = [2048, 4096, 8192, 16384, 32768, 65536]
_NSZ_BS_EXP = list(range(14, 25))
_MULTI_VALUES = [1, 2, 3, 4, 6, 8, 12, 16]


class ChdPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "chd_type": "chd_type", "codecs": "codec_boxes",
        "no_compression": "no_compress", "hunk_size": "hunk_combo",
        "num_processors": "np_combo", "force": "force_box",
    }

    def _build_options(self) -> None:
        self.chd_type = QComboBox()
        self.chd_type.addItem("Auto", "auto")
        self.chd_type.addItem("CD (PS1/DC)", "createcd")
        self.chd_type.addItem("DVD (PS2/PSP)", "createdvd")
        self.chd_type.addItem("Hard Disk", "createhd")
        self.chd_type.addItem("Raw", "createraw")
        self.add_row("CHD type:", self.chd_type)

        self.codec_boxes = self.add_checkboxes(
            "Codec:",
            [("zlib", "zlib"), ("zstd", "zstd"), ("lzma", "lzma"),
             ("flac", "flac"), ("huff", "huff")],
        )
        self.codec_boxes["zlib"].setChecked(True)

        self.no_compress = QCheckBox("No compression")
        self.no_compress.setToolTip("chdman -c none. Repackages without compressing.")
        self.add_row("", self.no_compress)

        self.hunk_combo = self.add_int_combo(
            "Hunk:", _HUNK_VALUES, 0, auto=True, fmt=str,
        )

        self.np_combo = self.add_int_combo(
            "CPU:", _THREAD_VALUES, 0, auto=True,
        )

        self.force_box = QCheckBox("Overwrite existing")
        self.force_box.setToolTip("chdman -f.")
        self.add_row("", self.force_box, compress_only=False)

    def options(self) -> dict:
        codecs = [k for k, cb in self.codec_boxes.items() if cb.isChecked()]
        return {
            "chd_type": self.chd_type.currentData(),
            "codecs": codecs[:4],
            "no_compression": self.no_compress.isChecked(),
            "hunk_size": self.hunk_combo.currentData(),
            "num_processors": self.np_combo.currentData(),
            "force": self.force_box.isChecked(),
        }


class RvzPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "out_fmt": "out_fmt", "codec": "codec", "level": "level",
        "block_size": "block", "scrub": "scrub",
    }

    def _build_options(self) -> None:
        self.out_fmt = QComboBox()
        for fmt in ("rvz", "wia", "gcz", "iso"):
            self.out_fmt.addItem(fmt.upper(), fmt)
        self.out_fmt.currentIndexChanged.connect(self._update_codec_state)
        self.add_row("Output format:", self.out_fmt)

        self.codec = QComboBox()
        for c in ("zstd", "bzip2", "lzma", "lzma2", "none"):
            self.codec.addItem(c, c)
        self.codec.currentIndexChanged.connect(self._update_codec_state)
        self.add_row("Codec:", self.codec)

        self.level = self.add_int_combo("zstd level:", _LEVELS_1_22, 5)
        self.block = self.add_int_combo("Block size:", _RVZ_BLOCKS, 131072, fmt=_kb_label)

        self.scrub = QCheckBox("Scrub junk data")
        self.scrub.setToolTip(
            "DolphinTool -s. Zeroes the padding Nintendo discs are full of.\n"
            "Compresses better, but the image no longer matches a Redump hash.")
        self.add_row("", self.scrub)

    def _update_codec_state(self) -> None:
        fmt = self.out_fmt.currentData()
        is_compress = self.current_mode() == ConversionMode.COMPRESS
        codec_formats = fmt in {"rvz", "wia"}
        self.codec.setEnabled(codec_formats and is_compress)
        level_on = codec_formats and self.codec.currentData() != "none"
        self.level.setEnabled(level_on and is_compress)
        self.block.setEnabled(fmt in {"rvz", "wia", "gcz"} and is_compress)

    def _on_mode_changed(self) -> None:
        super()._on_mode_changed()
        if hasattr(self, "out_fmt"):
            self._update_codec_state()

    def options(self) -> dict:
        return {
            "out_fmt": self.out_fmt.currentData(),
            "codec": self.codec.currentData(),
            "level": self.level.currentData(),
            "block_size": self.block.currentData(),
            "scrub": self.scrub.isChecked(),
        }


class CsoPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "cso_format": "cso_format", "methods": "method_boxes", "fast": "fast",
        "block_size": "block", "threads": "threads",
    }

    def _build_options(self) -> None:
        self.cso_format = QComboBox()
        for f in ("cso1", "cso2", "zso", "dax"):
            self.cso_format.addItem(f, f)
        self.add_row("Format:", self.cso_format)

        self.method_boxes = self.add_checkboxes(
            "Methods:",
            [
                ("zlib", "zlib"),
                ("zopfli", "zopfli"),
                ("7zdeflate", "7z"),
                ("lz4", "lz4"),
                ("lz4brute", "lz4-brute"),
                ("libdeflate", "libdeflate"),
            ],
        )
        self.method_boxes["zlib"].setChecked(True)
        self.method_boxes["7zdeflate"].setChecked(True)

        self.fast = QCheckBox("Fast mode")
        self.fast.setToolTip("maxcso --fast. Skips the multi-method contest.")
        self.add_row("", self.fast)

        self.block = self.add_int_combo("Block size:", _CSO_BLOCKS, 0, auto=True, fmt=_kb_label)
        self.threads = self.add_int_combo("Threads:", _THREAD_VALUES, 0, auto=True,
                                          compress_only=False)

    def options(self) -> dict:
        methods = [k for k, cb in self.method_boxes.items() if cb.isChecked()]
        return {
            "cso_format": self.cso_format.currentData(),
            "methods": methods,
            "fast": self.fast.isChecked(),
            "block_size": self.block.currentData(),
            "threads": self.threads.currentData(),
        }


_Z3DS_COMPRESS_NOTE = (
    "Compress: CCI/CIA -> ZCCI/ZCIA. ROMs must be decrypted first.\n"
    "Level needs rom-converto; z3ds_compress (fallback) always uses its own default."
)
_Z3DS_DECOMPRESS_NOTE = (
    "Open: ZCCI/ZCIA/ZCXI -> the original CCI/CIA/CXI, byte for byte.\n"
    "Runs inside the app, no external tool or download needed."
)


class Z3dsPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "level": "level", "allow_encrypted": "allow_encrypted",
    }

    def _build_options(self) -> None:
        self.mode_note = QLabel(_Z3DS_COMPRESS_NOTE)
        self.mode_note.setObjectName("hintLabel")
        self.mode_note.setWordWrap(True)
        self.form.addRow(self.mode_note)

        self.level = self.add_int_combo(
            "zstd level:", _LEVELS_1_22, 0, auto=True, auto_label="Default",
        )
        self.allow_encrypted = QCheckBox("Allow encrypted")
        self.allow_encrypted.setToolTip(
            "Compress a still-encrypted ROM anyway. Encrypted data does not\n"
            "compress, so the result will be about the size of the original.")
        self.add_row("", self.allow_encrypted)

    def _on_mode_changed(self) -> None:
        super()._on_mode_changed()
        note = getattr(self, "mode_note", None)
        if note is not None:
            note.setText(
                _Z3DS_DECOMPRESS_NOTE
                if self.current_mode() == ConversionMode.DECOMPRESS
                else _Z3DS_COMPRESS_NOTE,
            )

    def options(self) -> dict:
        return {
            "level": self.level.currentData(),
            "allow_encrypted": self.allow_encrypted.isChecked(),
        }


class NdsTrimPanel(BaseFormatPanel):
    def _build_options(self) -> None:
        # ndstrim takes no flags, so there is nothing to put here. Say so,
        # rather than leaving a page that looks like it failed to load.
        note = QLabel(
            "Nothing to configure. ndstrim reads the real end of the cart from "
            "its header and cuts there, keeping the file's name and extension."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        self.form.addRow(note)

    def options(self) -> dict:
        return {}


class NszPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "level": "level", "comp_mode": "comp_mode", "long": "long_mode",
        "bs_exp": "bs_exp", "threads": "threads", "multi": "multi",
        "keys_path": "keys_edit",
    }

    def _build_options(self) -> None:
        note = QLabel(
            "Base, update and DLC are separate files, each is compressed to its own NSZ. "
            "Queue shows Type (Base/Update/DLC) per file."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        self.form.addRow(note)

        self.level = self.add_int_combo("zstd level:", _LEVELS_1_22, 18)

        self.comp_mode = QComboBox()
        self.comp_mode.addItem("Auto", "auto")
        self.comp_mode.addItem("Block", "block")
        self.comp_mode.addItem("Solid", "solid")
        self.comp_mode.currentIndexChanged.connect(self._update_bs_state)
        self.add_row("Type:", self.comp_mode)

        self.long_mode = QCheckBox("Long distance mode")
        self.long_mode.setToolTip("nsz -L. Better ratio, much more memory.")
        self.add_row("", self.long_mode)

        self.bs_exp = self.add_int_combo(
            "Block size (2^x):", _NSZ_BS_EXP, 20, fmt=lambda x: f"2^{x}",
        )

        self.threads = self.add_int_combo("Threads:", _THREAD_VALUES, 0, auto=True,
                                          compress_only=False)
        self.multi = self.add_int_combo("Parallel tasks:", _MULTI_VALUES, 4, compress_only=False)

        self.keys_edit = QLineEdit()
        self.keys_edit.setPlaceholderText("Path to prod.keys")
        self.keys_edit.setReadOnly(True)
        keys_btn = QPushButton("...")
        keys_btn.setObjectName("browseBtn")
        keys_btn.setFixedWidth(36)
        keys_btn.clicked.connect(self._pick_keys)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.keys_edit)
        row_layout.addWidget(keys_btn)
        self._track(self.keys_edit, compress_only=False)
        self.form.addRow("prod.keys:", row)

    def _update_bs_state(self) -> None:
        self.bs_exp.setEnabled(
            self.comp_mode.currentData() == "block"
            and self.current_mode() == ConversionMode.COMPRESS
        )

    def _on_mode_changed(self) -> None:
        super()._on_mode_changed()
        if hasattr(self, "comp_mode"):
            self._update_bs_state()

    def _pick_keys(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select prod.keys", "", "Keys (*.keys);;All files (*)")
        if path:
            self.keys_edit.setText(path)

    def set_keys_path(self, path: str) -> None:
        self.keys_edit.setText(path)

    def options(self) -> dict:
        return {
            "level": self.level.currentData(),
            "comp_mode": self.comp_mode.currentData(),
            "long": self.long_mode.isChecked(),
            "bs_exp": self.bs_exp.currentData(),
            "threads": self.threads.currentData(),
            "multi": self.multi.currentData(),
            "keys_path": self.keys_edit.text().strip(),
        }


SEVEN_ZIP_METHODS = {
    "7z": ["LZMA2", "LZMA", "PPMd", "BZip2", "Deflate"],
    "zip": ["Deflate", "LZMA", "BZip2", "PPMd"],
}


class SevenZipPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "archive_type": "archive_type", "method": "method", "level": "level",
        "solid": "solid", "threads": "threads",
    }

    def _build_options(self) -> None:
        self.archive_type = QComboBox()
        self.archive_type.addItem("7z", "7z")
        self.archive_type.addItem("ZIP", "zip")
        self.archive_type.currentIndexChanged.connect(self._update_methods)
        self.add_row("Archive type:", self.archive_type)

        self.method = QComboBox()
        self.add_row("Method:", self.method)
        self._update_methods()

        self.level = self.add_int_combo("Level:", _LEVELS_0_9, 9)

        self.solid = QCheckBox("Solid archive")
        self.solid.setToolTip("7z only. Helps when several ROMs share an archive.")
        self.solid.setChecked(True)
        self.add_row("", self.solid)

        self.threads = self.add_int_combo("Threads:", _THREAD_VALUES, 0, auto=True,
                                          compress_only=False)

    def _update_methods(self) -> None:
        current = self.method.currentText() if self.method.count() else ""
        self.method.blockSignals(True)
        self.method.clear()
        self.method.addItems(SEVEN_ZIP_METHODS[self.archive_type.currentData()])
        idx = self.method.findText(current)
        if idx >= 0:
            self.method.setCurrentIndex(idx)
        self.method.blockSignals(False)
        self.changed.emit()

    def options(self) -> dict:
        return {
            "archive_type": self.archive_type.currentData(),
            "method": self.method.currentText(),
            "level": self.level.currentData(),
            "solid": self.solid.isChecked(),
            "threads": self.threads.currentData(),
        }


class WuaPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {
        "level": "level", "key_path": "key_edit",
    }

    def _build_options(self) -> None:
        note = QLabel(
            "For Cemu. .wud/.wux disc image -> .wua. "
            "Needs a disc key (sibling <name>.key or game.key, or pick below)."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        self.form.addRow(note)

        self.level = self.add_int_combo(
            "Zstd level:", list(range(1, 23)), 0,
            auto=True, auto_label="Cemu (6)", auto_value=0,
        )

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("Disc key (optional)")
        self.key_edit.setReadOnly(True)
        key_btn = QPushButton("...")
        key_btn.setObjectName("browseBtn")
        key_btn.setFixedWidth(36)
        key_btn.clicked.connect(self._pick_key)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self.key_edit)
        row_layout.addWidget(key_btn)
        self._track(self.key_edit)
        self.form.addRow("Disc key:", row)

    def _pick_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select disc key", "", "Key (*.key);;All (*.*)")
        if path:
            self.key_edit.setText(path)

    def options(self) -> dict:
        return {
            "level": self.level.currentData(),
            "key_path": self.key_edit.text().strip(),
        }


class Dec3dsPanel(BaseFormatPanel):
    BINDINGS: ClassVar[dict[str, str]] = {"to_cci": "to_cci"}

    def _build_options(self) -> None:
        note = QLabel(
            "Decrypts .cia / .3ds so emulators and ZCCI compression can read them. "
            ".3ds carts become decrypted .cci; CIAs stay .cia. "
            "Update/DLC/demo CIAs are supported; DSiWare (TWL) is not."
        )
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        self.form.addRow(note)

        self.to_cci = QCheckBox("Game CIAs to CCI")
        self.to_cci.setToolTip(
            "After decrypting, convert full-game CIAs into CCI (best for ZCCI compression).\n"
            "Updates, DLC and demos are never converted, they stay as decrypted CIA."
        )
        self.add_row("", self.to_cci)

    def options(self) -> dict:
        return {"to_cci": self.to_cci.isChecked()}


PANEL_TYPES: dict[CompressionFormat, type[BaseFormatPanel]] = {
    CompressionFormat.CHD: ChdPanel,
    CompressionFormat.RVZ: RvzPanel,
    CompressionFormat.CSO: CsoPanel,
    CompressionFormat.Z3DS: Z3dsPanel,
    CompressionFormat.NDS_TRIM: NdsTrimPanel,
    CompressionFormat.NSZ: NszPanel,
    CompressionFormat.SEVEN_ZIP: SevenZipPanel,
    CompressionFormat.WUA: WuaPanel,
    CompressionFormat.DEC_3DS: Dec3dsPanel,
}


class FormatPanels(QObject):
    """Owns the nine option panels. Deliberately not a widget.

    This used to be a QStackedWidget, and that was a bug: a stack hides every
    page but the current one, and hiding is an explicit flag that travels with
    the widget. The settings dialog takes each panel out and puts it on its own
    page, so all nine arrived already hidden and every format page rendered as
    a heading with nothing under it.

    There is no second stack to be had here anyway. The dialog switches pages
    itself; this only needs to build the panels, hand them out, and say which
    format was edited so the dialog can push exactly those onto queued rows.
    """

    format_changed = Signal(object)  # CompressionFormat

    def __init__(self) -> None:
        super().__init__()
        self._panels: dict[CompressionFormat, BaseFormatPanel] = {}
        for fmt, panel_type in PANEL_TYPES.items():
            panel = panel_type(fmt)
            panel.changed.connect(lambda f=fmt: self.format_changed.emit(f))
            self._panels[fmt] = panel

    def panel(self, fmt: CompressionFormat) -> BaseFormatPanel:
        return self._panels[fmt]

    def options(self, fmt: CompressionFormat) -> dict:
        return self._panels[fmt].options()

    def all_options(self) -> dict[CompressionFormat, dict]:
        return {fmt: panel.options() for fmt, panel in self._panels.items()}

    def load(self, stored: dict[CompressionFormat, dict]) -> None:
        for fmt, options in stored.items():
            panel = self._panels.get(fmt)
            if panel is not None and options:
                panel.load(options)

    def set_keys_path(self, path: str) -> None:
        nsz = self._panels[CompressionFormat.NSZ]
        if isinstance(nsz, NszPanel):
            nsz.set_keys_path(path)

    def keys_path(self) -> str:
        nsz = self._panels[CompressionFormat.NSZ]
        return nsz.keys_edit.text().strip() if isinstance(nsz, NszPanel) else ""


class GeneralPanel(QWidget):
    """The settings that are not about any one format."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro = QLabel(
            "Applies to everything in the queue. Per-format settings are in the "
            "list on the left.")
        intro.setWordWrap(True)
        intro.setProperty("role", "second")
        layout.addRow(intro)

        out_row = QWidget()
        out_layout = QHBoxLayout(out_row)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(6)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Same folder as the source")
        self.output_edit.setReadOnly(True)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._pick_output)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: self.output_edit.setText(""))
        out_layout.addWidget(self.output_edit, stretch=1)
        out_layout.addWidget(browse)
        out_layout.addWidget(clear)
        layout.addRow("Output folder:", out_row)

        self.conflict_combo = QComboBox()
        self.conflict_combo.addItem("Skip it", "skip")
        self.conflict_combo.addItem("Overwrite it", "overwrite")
        self.conflict_combo.addItem("Write alongside it", "rename")
        self.conflict_combo.setToolTip(
            "Skip by default, so re-running over a finished folder does nothing\n"
            "rather than redoing hours of work.")
        layout.addRow("If the output exists:", self.conflict_combo)

        self.switch_subdirs = QCheckBox("Give each Switch game its own folder")
        self.switch_subdirs.setToolTip(
            "Keeps a title's base game, update and DLC together, which is how\n"
            "an installer expects to find them.")
        layout.addRow("", self.switch_subdirs)

        self.delete_source = QCheckBox("Delete the source after converting")
        self.delete_source.setToolTip(
            "Off every time the app starts, on purpose. It asks before a batch\n"
            "runs, and never deletes unless the output exists and is not empty.")
        layout.addRow("", self.delete_source)

        for widget, signal in (
            (self.output_edit, "textChanged"),
            (self.conflict_combo, "currentIndexChanged"),
            (self.switch_subdirs, "toggled"),
            (self.delete_source, "toggled"),
        ):
            getattr(widget, signal).connect(lambda *_: self.changed.emit())

    def _pick_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose an output folder")
        if path:
            self.output_edit.setText(path)

    def load(self, settings: FormatSettings) -> None:
        widgets = (self.output_edit, self.conflict_combo,
                   self.switch_subdirs, self.delete_source)
        for widget in widgets:
            widget.blockSignals(True)
        self.output_edit.setText(settings.output_dir)
        index = self.conflict_combo.findData(settings.on_conflict)
        if index >= 0:
            self.conflict_combo.setCurrentIndex(index)
        self.switch_subdirs.setChecked(settings.switch_game_subdirs)
        self.delete_source.setChecked(settings.delete_source)
        for widget in widgets:
            widget.blockSignals(False)

    def apply_to(self, settings: FormatSettings) -> None:
        settings.output_dir = self.output_edit.text().strip()
        settings.on_conflict = self.conflict_combo.currentData()
        settings.switch_game_subdirs = self.switch_subdirs.isChecked()
        settings.delete_source = self.delete_source.isChecked()
