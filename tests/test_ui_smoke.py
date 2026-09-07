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
from pathlib import Path

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


@pytest.fixture(autouse=True)
def _clear_saved_settings(app):
    """MainWindow.closeEvent persists settings; one test must not leak into the next."""
    from PySide6.QtCore import QSettings

    from aynthor.ui.state import APPLICATION, ORGANISATION

    QSettings(ORGANISATION, APPLICATION).clear()
    yield
    QSettings(ORGANISATION, APPLICATION).clear()


@pytest.fixture()
def settings() -> FormatSettings:
    return FormatSettings()


def test_human_size_uses_binary_units_without_rounding_gb_to_zero():
    from aynthor.ui.queue_view import human_size

    assert human_size(6416917776) == "6.0 GB"
    assert human_size(1023) == "1023 B"
    assert human_size(1536) == "2 KB"
    assert human_size(0) == "-"


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

def test_settings_footer_does_not_cover_preset_controls(app, settings, presets):
    """Save/Cancel used to paint over the CHD codec row on Platform presets."""
    from PySide6.QtWidgets import QCheckBox

    dialog = open_settings(app, settings, presets)
    dialog.resize(880, 620)
    dialog.categories.setCurrentRow(1)
    app.processEvents()
    page = dialog.presets_page
    row = next(
        r for r in range(page.table.rowCount())
        if page.table.item(r, page.COL_PLATFORM).data(Qt.ItemDataRole.UserRole)
        == "neogeocd"
    )
    page.table.setCurrentCell(row, 0)
    app.processEvents()

    footer = dialog.footer.geometry()
    overlaps = []
    for box in page.panels.currentWidget().findChildren(QCheckBox):
        if not box.isVisible() or box.visibleRegion().isEmpty():
            continue
        top = box.mapTo(dialog, box.rect().topLeft()).y()
        bottom = box.mapTo(dialog, box.rect().bottomLeft()).y()
        if bottom > footer.top() and top < footer.bottom():
            overlaps.append(box.text() or "checkbox")
    dialog.close()
    assert overlaps == []


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

def _named_folder(node, name: str):
    """Find a folder node named `name` at or under `node`."""
    if node is None:
        return None
    if node.text(0) == name:
        return node
    for i in range(node.childCount()):
        found = _named_folder(node.child(i), name)
        if found is not None:
            return found
    return None


def _show_empty_folders(window) -> None:
    window.settings.show_empty_folders = True
    window.queue.apply_settings(window.settings)


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
    names = {
        window.queue.item(row, window.queue.COL_FILE).text().rsplit("/", 1)[-1]
        for row in range(window.queue.rowCount())
    }
    assert names == {
        "Chrono Cross (Disc 1).cue", "Metroid Prime.iso", "Super Mario World.sfc",
    }
    window.close()


def test_a_zip_holding_an_iso_is_queued_as_the_iso(app, tmp_path):
    """Selecting Game.zip used to queue 'compress to 7z', nesting the ISO."""
    import zipfile

    from aynthor.core.models import CompressionFormat
    from aynthor.ui.main_window import MainWindow

    archive = tmp_path / "ROMs" / "ps2" / "Persona 4.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("Persona 4.iso", b"\0" * 16)

    window = MainWindow()
    window.show()
    window._add([archive])
    app.processEvents()

    assert window.queue.rowCount() == 1
    row = window.queue.row_item(0)
    assert row.member == "Persona 4.iso"
    assert row.format is CompressionFormat.CHD
    assert row.platform == "ps2"
    assert window.queue.item(0, window.queue.COL_FILE).text() == (
        "Persona 4.zip [Persona 4.iso]")
    window.close()


def test_switch_dlc_joins_the_base_game_tree(app, tmp_path):
    """DLC packs named 'Elixir Set 1' used to become their own game folders."""
    from aynthor.ui.main_window import MainWindow

    folder = tmp_path / "switch"
    folder.mkdir()
    for name in (
        "Ys VIII Lacrimosa of DANA [01007F200B0C0000][v0].nsp",
        "Ys VIII Lacrimosa of DANA [01007F200B0C0800][v327680].nsp",
        "Ys VIII Lacrimosa of DANA Elixir Set 1 [01007F200B0C0001][v0].nsp",
        "Ys VIII Lacrimosa of DANA Free Set 1 [01007F200B0C0002][v0].nsp",
        "Ys VIII Lacrimosa of DANA Tempest Set 1 [01007F200B0C0003][v0].nsp",
    ):
        (folder / name).write_bytes(b"\0" * 16)

    window = MainWindow()
    window.show()
    window._add([folder])
    app.processEvents()

    assert window.queue.rowCount() == 5
    games = [node for node in window.queue._all_folders()
             if window.queue._is_game_node(node)]
    assert len(games) == 1, [g.text(window.queue.COL_FILE) for g in games]
    assert "Ys VIII Lacrimosa of DANA" in games[0].text(window.queue.COL_FILE)
    types = {window.queue.item(row, window.queue.COL_TYPE).text()
             for row in range(window.queue.rowCount())}
    assert types == {"Base", "Update", "DLC"}
    window.close()


def test_xci_base_keeps_nsp_update_and_dlc_in_same_folder(app, tmp_path):
    """Base.xci/Base.xci must own same-game .nsp Update/DLC — not invent Base.nsp/."""
    from aynthor.core.models import ConversionMode
    from aynthor.ui.main_window import MainWindow

    folder = tmp_path / "switch"
    folder.mkdir()
    for name in (
        "Ys X Nordics [0100BAC01E57E000][v0].xci",
        "Ys X Nordics [0100BAC01E57E800][v196608].nsp",
        "Ys X Nordics Extra Pack [0100BAC01E57E001][v0].nsp",
    ):
        (folder / name).write_bytes(b"\0" * 16)

    window = MainWindow()
    window.show()
    window.settings.game_folders = True
    window._add([folder])
    app.processEvents()
    window.queue.set_mode(list(range(window.queue.rowCount())), ConversionMode.MOVE)
    app.processEvents()

    assert window.queue.rowCount() == 3
    games = [node for node in window.queue._all_folders()
             if window.queue._is_game_node(node)]
    assert len(games) == 1, [g.text(window.queue.COL_FILE) for g in games]
    assert games[0].text(window.queue.COL_FILE).endswith(".xci")
    parents = {window.queue.row_item(row).output.parent.name
               for row in range(window.queue.rowCount())}
    assert parents == {"Ys X Nordics.xci"}, parents
    window.close()


def test_cover_set_dlc_joins_base_without_title_ids(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    folder = tmp_path / "switch"
    folder.mkdir()
    for name in (
        "The Legend of Heroes Trails of Cold Steel III.nsp",
        "The Legend of Heroes Trails of Cold Steel III Update.nsp",
        "The Legend of Heroes Trails of Cold Steel III Trails of Cold Steel III "
        "ARCUS Cover Set A.nsp",
        "The Legend of Heroes Trails of Cold Steel III Trails of Cold Steel III "
        "ARCUS Cover Set B.nsp",
    ):
        (folder / name).write_bytes(b"\0" * 16)

    window = MainWindow()
    window.show()
    window._add([folder])
    app.processEvents()

    assert window.queue.rowCount() == 4
    games = [node for node in window.queue._all_folders()
             if window.queue._is_game_node(node)]
    assert len(games) == 1, [g.text(window.queue.COL_FILE) for g in games]
    assert games[0].text(window.queue.COL_FILE).startswith(
        "The Legend of Heroes Trails of Cold Steel III")
    window.close()


def test_scene_named_dlc_packs_share_one_tree(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    folder = tmp_path / "switch"
    folder.mkdir()
    for name in (
        "Ys X Nordics.nsp",
        "v ys x nordics ys x advanced pack dlc.nsz",
        "v ys x nordics ys x attachment pack dlc.nsz",
        "v ys x nordics ys x costume pack dlc.nsz",
        "v ys x nordics ys x freebie set a dlc.nsz",
    ):
        (folder / name).write_bytes(b"\0" * 16)

    window = MainWindow()
    window.show()
    window._add([folder])
    app.processEvents()

    assert window.queue.rowCount() == 5
    games = [node for node in window.queue._all_folders()
             if window.queue._is_game_node(node)]
    assert len(games) == 1, [g.text(window.queue.COL_FILE) for g in games]
    assert "nordics" in games[0].text(window.queue.COL_FILE).casefold()
    window.close()


def test_a_member_job_restores_the_archive_path_after_unpacking(app, tmp_path, monkeypatch):
    import zipfile

    from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode
    from aynthor.ui.job_runner import JobRunner

    archive = tmp_path / "game.zip"
    with zipfile.ZipFile(archive, "w") as opened:
        opened.writestr("game.iso", b"disc")
    output = tmp_path / "out" / "game.chd"
    seen: dict[str, object] = {}

    class Fake:
        on_progress = None

        def convert(self, job):
            seen["input"] = job.input_path
            seen["bytes"] = job.input_path.read_bytes()
            job.output_path.write_bytes(b"chd")
            return True, "ok"

    monkeypatch.setattr("aynthor.ui.job_runner.get_converter", lambda _fmt: Fake())
    job = ConversionJob(
        input_path=archive, output_path=output,
        format=CompressionFormat.CHD,
        options={"mode": ConversionMode.COMPRESS.value},
        member="game.iso",
    )
    ok, _message = JobRunner([])._execute(0, job)
    assert ok is True
    assert job.input_path == archive
    assert seen["bytes"] == b"disc"
    assert Path(seen["input"]).name == "game.iso"
    assert output.is_file()


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
        window.queue.item(row, window.queue.COL_FILE).text().rsplit("/", 1)[-1]: row
        for row in range(window.queue.rowCount())
    }
    chd = by_name["Chrono Cross.chd"]
    iso = by_name["Metroid Prime.iso"]

    assert window.queue.row_mode(chd) is ConversionMode.DECOMPRESS
    assert window.queue.row_mode(iso) is ConversionMode.COMPRESS
    # And the row says which way round it is, in this format's own verb.
    assert window.queue.item(chd, window.queue.COL_BECOMES).text() == "Decompress"
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
        window.queue.item(row, window.queue.COL_FILE).text().rsplit("/", 1)[-1]:
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


def test_an_empty_game_folder_appears_as_a_drop_target(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    empty = tmp_path / "psx" / "Final Fantasy VIII.chd"
    empty.mkdir(parents=True)
    window = MainWindow()
    window.show()
    _show_empty_folders(window)
    window._add([tmp_path / "psx"])
    app.processEvents()

    assert window.queue.rowCount() == 0
    top = window.queue.topLevelItem(0)
    folder = _named_folder(top, "Final Fantasy VIII.chd")
    assert folder is not None
    assert "Empty" in folder.text(window.queue.COL_STATUS)
    window.settings.show_empty_folders = False
    window.close()


def test_dropping_a_file_onto_a_folder_renames_the_primary(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    empty = tmp_path / "psx" / "Final Fantasy VIII.chd"
    empty.mkdir(parents=True)
    dump = tmp_path / "Downloads" / "dump.cue"
    dump.parent.mkdir()
    dump.write_bytes(b"cue")

    window = MainWindow()
    window.show()
    _show_empty_folders(window)
    window._add([tmp_path / "psx"])
    window._add([dump])
    app.processEvents()

    folder = _named_folder(window.queue.topLevelItem(0), "Final Fantasy VIII.chd")
    assert folder is not None
    file_node = window.queue.files()[0]
    window.queue.place_under(file_node, folder)
    app.processEvents()

    item = window.queue.row_item(0)
    assert item.output.parent.name == "Final Fantasy VIII.chd"
    assert item.output.name == "Final Fantasy VIII.chd"
    assert file_node.parent() is folder
    window.settings.show_empty_folders = False
    window.close()


def test_adding_a_roms_tree_shows_empty_platform_folders(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    for name in ("psx", "snes", "n64"):
        folder = roms / name
        folder.mkdir(parents=True)
        (folder / "systeminfo.txt").write_text(name)

    window = MainWindow()
    window.show()
    _show_empty_folders(window)
    window._add([roms])
    app.processEvents()

    assert window.queue.rowCount() == 0
    names = {
        window.queue.topLevelItem(i).text(window.queue.COL_FILE)
        for i in range(window.queue.topLevelItemCount())
    }
    assert names == {"psx", "snes", "n64"}
    window.settings.show_empty_folders = False
    window.close()


def test_empty_folders_sink_below_folders_that_have_files(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    (roms / "snes").mkdir(parents=True)
    (roms / "n64").mkdir()
    psx = roms / "psx"
    psx.mkdir()
    (psx / "Chrono Cross.cue").write_bytes(b"\0" * 2048)
    (roms / "snes" / "systeminfo.txt").write_text("snes")
    (roms / "n64" / "systeminfo.txt").write_text("n64")

    window = MainWindow()
    window.show()
    _show_empty_folders(window)
    window._add([roms])
    app.processEvents()

    names = [
        window.queue.topLevelItem(i).text(window.queue.COL_FILE)
        for i in range(window.queue.topLevelItemCount())
    ]
    window.settings.show_empty_folders = False
    window.close()
    assert names[0] == "psx"
    assert names[1:] == ["n64", "snes"]


def test_empty_folders_stay_hidden_until_the_setting_is_on(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    (roms / "psx").mkdir(parents=True)
    (roms / "snes").mkdir()
    (roms / "psx" / "systeminfo.txt").write_text("psx")

    window = MainWindow()
    window.show()
    window.settings.show_empty_folders = False
    window.queue.apply_settings(window.settings)
    window._add([roms])
    app.processEvents()

    assert window.queue.topLevelItemCount() == 0
    assert window.queue_card.isVisibleTo(window) is False
    window.close()


def test_the_platform_menu_offers_every_esde_folder(app, tmp_path):
    from PySide6.QtWidgets import QMenu

    from aynthor.ui.main_window import MainWindow

    (tmp_path / "game.iso").write_bytes(b"\0" * 2048)
    window = MainWindow()
    window.show()
    window._add([tmp_path / "game.iso"])
    app.processEvents()

    menu = QMenu()
    window.queue._add_platform_actions(menu, 0, [0])
    labels = []
    for action in menu.actions():
        submenu = action.menu()
        if submenu is None:
            continue
        labels.extend(a.text() for a in submenu.actions() if a.text())
    window.close()
    assert "PlayStation 2" in labels
    assert "Nintendo 64" in labels
    assert "SNES" in labels
    assert "Steam" in labels


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


def test_a_stale_output_does_not_authorise_deleting_the_source(app, tmp_path):
    """With the conflict policy on overwrite a row is not skipped when its
    output already exists, so a leftover from an earlier run satisfied every
    other guard on its own. A converter exiting zero without writing anything
    would then have deleted the source against somebody else's file."""
    from aynthor.core.models import CompressionFormat, ConversionJob
    from aynthor.ui.job_runner import JobRunner

    source = tmp_path / "game.iso"
    source.write_bytes(b"\0" * 2048)
    stale = tmp_path / "game.chd"
    stale.write_bytes(b"\0" * 2048)

    job = ConversionJob(
        input_path=source, output_path=stale,
        format=CompressionFormat.CHD, options={}, input_size=2048,
    )
    runner = JobRunner([])

    # Pretend the run started after the output was last written.
    assert runner._delete_source(job, started_at=stale.stat().st_mtime + 60) is False
    assert source.is_file(), "the source must survive"

    # And a genuine output, written during the run, still allows it.
    assert runner._delete_source(job, started_at=stale.stat().st_mtime - 60) is True
    assert not source.exists()


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


def test_adding_a_file_offers_join_to_an_existing_disk_folder(app, tmp_path):
    """Card already has the base; later content asks and joins that folder."""
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    base_dir = roms / "switch" / "Ys X Nordics.nsp"
    base_dir.mkdir(parents=True)
    (base_dir / "Ys X Nordics.nsp").write_bytes(b"base")
    dlc = tmp_path / "Ys X Nordics Extra Content.nsp"
    dlc.write_bytes(b"dlc" * 20)

    window = MainWindow()
    window.show()
    window.settings.esde_root = str(roms)
    window.settings.game_folders = True
    window.queue.apply_settings(window.settings)
    window.queue._confirm_disk_join = lambda folder, label: True
    window._add([dlc])
    app.processEvents()

    folders = [
        window.queue.topLevelItem(i)
        for i in range(window.queue.topLevelItemCount())
    ]
    game = next(
        (f for f in folders if "Ys X Nordics" in f.text(window.queue.COL_FILE)),
        None,
    )
    assert game is not None
    assert game.text(window.queue.COL_FILE) == "Ys X Nordics.nsp"
    statuses = {
        game.child(i).text(window.queue.COL_STATUS)
        for i in range(game.childCount())
    }
    assert "Already on card" in statuses
    window.close()


def test_merging_one_game_tree_into_another_keeps_the_target_name(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    a = tmp_path / "Alpha Game.nsp"
    b = tmp_path / "Beta Game.nsp"
    a.write_bytes(b"a" * 20)
    b.write_bytes(b"b" * 20)

    window = MainWindow()
    window.show()
    window.settings.game_folders = True
    window.queue.apply_settings(window.settings)
    window.queue._confirm_disk_join = lambda *_: False
    window._add([a, b])
    app.processEvents()

    games = [
        window.queue.topLevelItem(i)
        for i in range(window.queue.topLevelItemCount())
        if window.queue._is_game_node(window.queue.topLevelItem(i))
    ]
    assert len(games) >= 2
    target, source = games[0], games[1]
    target_name = target.text(window.queue.COL_FILE)
    window.queue.merge_game_folders(source, target)
    app.processEvents()

    assert target.text(window.queue.COL_FILE) == target_name
    assert target.childCount() >= 2
    assert window.queue.indexOfTopLevelItem(source) < 0
    window.close()


def test_renaming_a_game_folder_renames_disk_too(app, tmp_path):
    from aynthor.ui.main_window import MainWindow

    roms = tmp_path / "ROMs"
    folder = roms / "switch" / "Old Title.nsp"
    folder.mkdir(parents=True)
    (folder / "Old Title.nsp").write_bytes(b"base")
    extra = tmp_path / "Old Title Pack.nsp"
    extra.write_bytes(b"x" * 20)

    window = MainWindow()
    window.show()
    window.settings.esde_root = str(roms)
    window.settings.game_folders = True
    window.queue.apply_settings(window.settings)
    window.queue._confirm_disk_join = lambda *_: True
    window._add([extra])
    app.processEvents()

    game = next(
        window.queue.topLevelItem(i)
        for i in range(window.queue.topLevelItemCount())
        if "Old Title" in window.queue.topLevelItem(i).text(window.queue.COL_FILE)
    )
    assert window.queue.rename_game_folder(game, "New Title")
    app.processEvents()
    assert game.text(window.queue.COL_FILE) == "New Title.nsp"
    assert (roms / "switch" / "New Title.nsp").is_dir()
    assert not (roms / "switch" / "Old Title.nsp").exists()
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


def test_move_realigns_game_folder_extension_from_nsz_to_nsp(app, tmp_path):
    """Becomes Move writes .nsp; the tree folder must not stay labelled .nsz."""
    import zipfile

    from aynthor.core.models import ConversionMode
    from aynthor.ui.main_window import MainWindow

    archive = tmp_path / "switch" / "Ys VIII.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Ys VIII Lacrimosa of DANA.nsp", b"\0" * 64)

    window = MainWindow()
    window.show()
    window.settings.game_folders = True
    window.queue.apply_settings(window.settings)
    window._add([archive])
    app.processEvents()

    games = [n for n in window.queue._all_folders() if window.queue._is_game_node(n)]
    assert len(games) == 1
    assert games[0].text(window.queue.COL_FILE).endswith(".nsz")

    rows = list(range(window.queue.rowCount()))
    window.queue.set_mode(rows, ConversionMode.MOVE)
    app.processEvents()

    assert games[0].text(window.queue.COL_FILE).endswith(".nsp")
    assert games[0].text(window.queue.COL_BECOMES) == "Move"
    assert window.queue.row_item(0).output.suffix.lower() == ".nsp"
    window.close()


def test_folder_becomes_targets_every_child_file(app, tmp_path):
    import zipfile

    from aynthor.core.models import ConversionMode
    from aynthor.ui.main_window import MainWindow

    archive = tmp_path / "switch" / "Game.zip"
    archive.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("Game.nsp", b"\0" * 32)
        zf.writestr("Game [DLC].nsp", b"\0" * 16)

    window = MainWindow()
    window.show()
    window.settings.game_folders = True
    window.queue.apply_settings(window.settings)
    window._add([archive])
    app.processEvents()

    game = next(n for n in window.queue._all_folders() if window.queue._is_game_node(n))
    rows = window.queue._rows_for_becomes_target(game)
    assert len(rows) == 2
    window.queue.set_mode(rows, ConversionMode.MOVE)
    app.processEvents()
    assert all(window.queue.row_mode(r) is ConversionMode.MOVE for r in rows)
    assert game.text(window.queue.COL_FILE).endswith(".nsp")
    window.close()
