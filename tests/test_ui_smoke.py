"""Build every window and check that it actually rendered something.

Why this exists
    A settings page shipped blank. Every option panel was constructed, wired up
    and correct; they were also invisible, because the container they were
    built in was a QStackedWidget and a stack hides every page but the current
    one. Hiding is a flag that travels with the widget, so once the dialog
    moved each panel onto its own page, all nine arrived hidden.

    Nothing in a unit test would have caught that. The widgets existed, their
    values were right, and no exception was raised. Only rendering catches it.

    So these run against a real Qt application on the offscreen platform, and
    assert what a screenshot would have shown: that each page has something on
    it, and that the controls a format's panel declares are visible.

    The rest of the suite stays free of Qt on purpose; this file is the one
    exception and skips cleanly when PySide6 is not installed.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6", reason="UI smoke tests need PySide6")

# Must be set before the first QApplication, and this module creates one.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PresetTable
from aynthor.core.settings import FormatSettings

CONTROLS = (QComboBox, QCheckBox, QLineEdit, QSpinBox)


@pytest.fixture(scope="module")
def app(tmp_path_factory) -> QApplication:
    """A Qt application whose saved settings go to a scratch directory.

    Without this the window writes to the real registry or config file on the
    machine running the tests, and a test that sets an output folder leaks it
    into every later test and every later run.
    """
    from PySide6.QtCore import QSettings

    from aynthor.ui.state import APPLICATION, ORGANISATION
    from aynthor.ui.theme import Mode, apply_theme

    scratch = tmp_path_factory.mktemp("settings")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    for fmt in (QSettings.Format.IniFormat, QSettings.Format.NativeFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(scratch))
    # Belt and braces: whatever the path resolved to, start it empty.
    QSettings(ORGANISATION, APPLICATION).clear()

    instance = QApplication.instance() or QApplication([])
    apply_theme(instance, Mode.DARK)
    return instance


@pytest.fixture()
def settings() -> FormatSettings:
    return FormatSettings()


@pytest.fixture()
def presets() -> PresetTable:
    return PresetTable()


def visible_controls(page: QWidget) -> list[QWidget]:
    return [w for kind in CONTROLS for w in page.findChildren(kind) if w.isVisibleTo(page)]


def visible_labels(page: QWidget) -> list[QLabel]:
    return [w for w in page.findChildren(QLabel) if w.isVisibleTo(page) and w.text()]


# --------------------------------------------------------------- settings

def open_settings(app, settings, presets, parent=None):
    from aynthor.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(settings, presets, parent)
    dialog.show()
    app.processEvents()
    return dialog


def test_every_settings_page_renders_something(app, settings, presets):
    """The bug this file was written for: pages that exist but show nothing."""
    dialog = open_settings(app, settings, presets)
    blank = []
    for row in range(dialog.categories.count()):
        dialog.categories.setCurrentRow(row)
        app.processEvents()
        page = dialog.pages.currentWidget()
        if not visible_controls(page) and len(visible_labels(page)) < 2:
            blank.append(dialog.categories.item(row).text())
    dialog.close()
    assert blank == []


def test_format_pages_show_their_controls(app, settings, presets):
    """A panel that declares options must have them on screen, not merely built."""
    from aynthor.core.formats import FORMAT_CATALOG

    dialog = open_settings(app, settings, presets)
    missing = []
    for info in FORMAT_CATALOG:
        panel = dialog.formats.panel(info.format)
        declared = [w for kind in CONTROLS for w in panel.findChildren(kind)]
        if not declared:
            continue  # NDS trim has no flags; it shows an explanation instead
        dialog.show_format(info.format)
        app.processEvents()
        if not visible_controls(dialog.pages.currentWidget()):
            missing.append(info.label)
    dialog.close()
    assert missing == []


def test_a_format_page_with_no_options_explains_itself(app, settings, presets):
    dialog = open_settings(app, settings, presets)
    dialog.show_format(CompressionFormat.NDS_TRIM)
    app.processEvents()
    text = " ".join(label.text() for label in visible_labels(dialog.pages.currentWidget()))
    dialog.close()
    assert "Nothing to configure" in text


def test_the_row_menu_opens_the_matching_settings_page(app, settings, presets):
    dialog = open_settings(app, settings, presets)
    dialog.show_format(CompressionFormat.NSZ)
    app.processEvents()
    heading = visible_labels(dialog.pages.currentWidget())[0].text()
    dialog.close()
    assert heading == "NSZ"


def test_saving_reports_only_the_pages_that_were_edited(app, settings, presets):
    dialog = open_settings(app, settings, presets)
    assert dialog.changed_formats() == set()
    dialog.formats.panel(CompressionFormat.CHD).force_box.setChecked(True)
    app.processEvents()
    assert dialog.changed_formats() == {CompressionFormat.CHD}
    assert dialog.result_settings().options[CompressionFormat.CHD]["force"] is True
    dialog.close()


# ------------------------------------------------------------ presets page

def test_presets_page_lists_every_platform(app, settings, presets):
    dialog = open_settings(app, settings, presets)
    assert dialog.presets_page.table.rowCount() == len(presets)
    dialog.close()


def test_selecting_a_platform_loads_its_real_values(app, settings, presets):
    """PS2 must show zlib ticked and hunk 2048, not an empty panel."""
    dialog = open_settings(app, settings, presets)
    page = dialog.presets_page
    row = next(r for r in range(page.table.rowCount())
               if page.table.item(r, page.COL_PLATFORM).data(Qt.ItemDataRole.UserRole) == "ps2")
    page.table.setCurrentCell(row, 0)
    app.processEvents()
    panel = page.panels.currentWidget()
    assert panel.codec_boxes["zlib"].isChecked()
    assert panel.options()["hunk_size"] == 2048
    dialog.close()


def test_editing_a_preset_updates_the_summary_column(app, settings, presets):
    dialog = open_settings(app, settings, presets)
    page = dialog.presets_page
    row = next(r for r in range(page.table.rowCount())
               if page.table.item(r, page.COL_PLATFORM).data(Qt.ItemDataRole.UserRole) == "snes")
    page.table.setCurrentCell(row, 0)
    app.processEvents()
    page.panels.currentWidget().level.setCurrentIndex(0)
    app.processEvents()
    assert dialog.presets_touched is True
    assert "*" in page.table.item(row, page.COL_PLATFORM).text()
    dialog.close()


# ------------------------------------------------------------- main window

def test_the_window_builds_and_starts_empty(app):
    from aynthor.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()
    assert window.queue.rowCount() == 0
    assert window.queue_card.isVisibleTo(window) is False
    assert window.start_button.isEnabled() is False
    window.close()


def test_the_title_bar_carries_the_version(app):
    """A bug report needs it, and nobody opens About to find it."""
    from aynthor import __version__
    from aynthor.ui.main_window import MainWindow

    window = MainWindow()
    assert __version__ in window.windowTitle()
    window.close()


def test_adding_files_fills_the_queue_and_the_summary(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    for name in ("Chrono Cross (Disc 1).cue", "Metroid Prime.iso", "Super Mario World.sfc"):
        (tmp_path / name).write_bytes(b"\0" * 2048)

    window = MainWindow()
    window.show()
    window._add([tmp_path])
    app.processEvents()

    assert window.queue.rowCount() == 3
    assert window.queue_card.isVisibleTo(window) is True
    assert window.start_button.isEnabled() is True
    assert "3 files" in window.summary_label.text()
    window.close()


def test_the_becomes_cell_offers_the_formats_that_accept_the_file(app, tmp_path):
    from PySide6.QtWidgets import QMenu

    from aynthor.ui.main_window import MainWindow

    (tmp_path / "game.cia").write_bytes(b"\0" * 2048)
    window = MainWindow()
    window.show()
    window._add([tmp_path])
    app.processEvents()

    menu = QMenu()
    window.queue._add_format_actions(menu, 0, [0])
    labels = [a.text() for a in menu.actions() if a.text()]
    window.close()
    # A .cia can be compressed to ZCCI or decrypted; both must be offered.
    assert any(label.startswith("ZCCI") for label in labels)
    assert any(label.startswith("Decrypt 3DS") for label in labels)


def test_an_already_compressed_file_arrives_as_an_expand(app, tmp_path):
    """It used to arrive as "compress to CHD", whose output was its own input."""
    from aynthor.core.models import ConversionMode
    from aynthor.ui.main_window import MainWindow

    (tmp_path / "Chrono Cross.chd").write_bytes(b"\0" * 2048)
    (tmp_path / "Metroid Prime.iso").write_bytes(b"\0" * 2048)

    window = MainWindow()
    window.show()
    window._add([tmp_path])
    app.processEvents()

    by_name = {
        window.queue.item(row, window.queue.COL_FILE).text(): row
        for row in range(window.queue.rowCount())
    }
    chd = by_name["Chrono Cross.chd"]
    iso = by_name["Metroid Prime.iso"]

    assert window.queue.row_mode(chd) is ConversionMode.DECOMPRESS
    assert window.queue.row_mode(iso) is ConversionMode.COMPRESS
    # And the row says which way round it is, in this format's own verb.
    assert window.queue.item(chd, window.queue.COL_BECOMES).text() == "CHD (decompress)"
    # The output is a different file from the input, which is what was broken.
    assert window.queue.row_item(chd).output != (tmp_path / "Chrono Cross.chd")
    window.close()


def test_the_becomes_cell_names_the_container_it_will_write(app, tmp_path):
    """It said ZCCI over a file that would be written as .zcia, and 7z / ZIP
    over an arcade romset that would be written as .zip."""
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    for relative in ("3ds/Game.cia", "3ds/Cart.3ds", "fbneo/sf2.zip", "snes/Mario.sfc"):
        path = roms / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * 2048)

    window = MainWindow()
    window.show()
    window._add([roms])
    app.processEvents()

    shown = {
        window.queue.item(row, window.queue.COL_FILE).text():
            window.queue.item(row, window.queue.COL_BECOMES).text()
        for row in range(window.queue.rowCount())
    }
    window.close()

    assert shown["Game.cia"] == "ZCIA"
    assert shown["Cart.3ds"] == "ZCCI"
    assert shown["Mario.sfc"] == "7Z"
    # An arcade romset that is already a zip has nothing to do, and is skipped
    # with a reason rather than queued to overwrite itself.
    assert "sf2.zip" not in shown


def test_the_platform_cell_can_be_changed_and_moves_the_output(app, tmp_path):
    """A fresh download sits in Downloads, not in a card's ps2 folder, so
    nothing can be worked out from where it is. Naming the platform is what
    tells the app which emulator will read the result."""
    from aynthor.core.settings import FormatSettings
    from aynthor.ui.main_window import MainWindow

    card = tmp_path / "ROMs"
    (card / "gc").mkdir(parents=True)
    (tmp_path / "Downloads").mkdir()
    (tmp_path / "Downloads" / "Some Game.iso").write_bytes(b"\0" * 2048)

    window = MainWindow()
    window.show()
    window.settings = FormatSettings(esde_root=str(card))
    window.queue.apply_settings(window.settings)
    window._add([tmp_path / "Downloads"])
    app.processEvents()

    window.queue.set_platform([0], "gc")
    app.processEvents()

    assert window.queue.row_platform(0) == "gc"
    assert window.queue.item(0, window.queue.COL_PLATFORM).text() == "GameCube"
    assert window.queue.row_item(0).output.parent == card / "gc"
    window.close()


def test_switching_format_does_not_carry_the_old_format_settings(app, tmp_path):
    """A GameCube row is RVZ at level 5. Switched to 7z it was archiving at 5,
    because `level` exists in both and the row kept the old value."""
    from aynthor.core.models import CompressionFormat
    from aynthor.ui.main_window import MainWindow
    from aynthor.ui.queue_view import _ROLE_OPTIONS

    roms = tmp_path / "ROMs" / "gc"
    roms.mkdir(parents=True)
    (roms / "Metroid Prime.iso").write_bytes(b"\0" * 2048)

    window = MainWindow()
    window.show()
    window._add([tmp_path / "ROMs"])
    app.processEvents()

    before = window.queue.item(0, window.queue.COL_FILE).data(_ROLE_OPTIONS)
    assert before["level"] == 5

    window.queue.set_format([0], CompressionFormat.SEVEN_ZIP)
    app.processEvents()
    after = window.queue.item(0, window.queue.COL_FILE).data(_ROLE_OPTIONS)
    window.close()

    assert after.get("level") != 5
    assert "codec" not in after   # the RVZ keys are gone too


def test_switching_theme_repaints_instead_of_leaving_half_the_window_behind(app):
    from aynthor.ui.main_window import MainWindow
    from aynthor.ui.theme import Mode, apply_theme, is_dark

    window = MainWindow()
    window.show()
    apply_theme(app, Mode.LIGHT)
    window.queue.refresh_colours()
    app.processEvents()
    assert is_dark() is False
    assert window.queue.palette().color(window.queue.backgroundRole()).lightness() > 200

    apply_theme(app, Mode.DARK)
    app.processEvents()
    assert is_dark() is True
    assert window.queue.palette().color(window.queue.backgroundRole()).lightness() < 80
    window.close()


# ----------------------------------------------------------------- dialogs

def test_the_tools_window_lists_every_installable_tool(app):
    from aynthor.core.tools.manifest import INSTALLABLE
    from aynthor.ui.tools_dialog import ToolsDialog

    dialog = ToolsDialog()
    dialog.show()
    app.processEvents()
    assert dialog.table.rowCount() == len(INSTALLABLE)
    dialog.close()


def test_the_about_box_names_every_tool_it_credits(app):
    from aynthor import __version__
    from aynthor.ui.about_dialog import AboutDialog

    dialog = AboutDialog()
    dialog.show()
    app.processEvents()
    text = " ".join(label.text() for label in dialog.findChildren(QLabel))
    dialog.close()
    assert __version__ in text
    assert "chdman" in text and "nsz" in text


def test_the_update_dialog_refuses_a_release_with_no_checksum(app):
    from aynthor.core.updates import Release
    from aynthor.ui.update_check import UpdateDialog

    release = Release(version="9.9.9", tag="v9.9.9", page_url="https://example.invalid",
                      notes="", asset_url="https://example.invalid/a.exe",
                      asset_size=1, checksum_url=None)
    dialog = UpdateDialog(release)
    dialog.show()
    app.processEvents()
    enabled = dialog.install.isEnabled()
    message = dialog.status.text()
    dialog.close()
    assert enabled is False
    assert "verifiable" in message
