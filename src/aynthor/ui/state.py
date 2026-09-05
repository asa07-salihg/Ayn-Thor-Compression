"""Remember what the user set, between runs.

Why
    A batch tool is used the same way every time: the same output folder, the
    same options, the same window on the same monitor. Making someone re-pick
    all of it at every launch is the difference between a utility and a demo.
    QSettings writes to the registry on Windows, so there is no file for the
    app to manage.

    Two things are deliberately not stored:

    * The queue. Those files may have been moved, renamed or already converted
      by the time the app opens again, and restoring a list of paths that no
      longer resolve is worse than restoring nothing.
    * `delete_source`. It destroys the user's ROMs, so it is re-armed on
      purpose each session.

Used by
    `ui.main_window` (on show and on close), `app.run` (the theme).

Reference
    https://doc.qt.io/qt-6/qsettings.html
"""

from __future__ import annotations

import json

from PySide6.QtCore import QByteArray, QSettings

from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PresetTable
from aynthor.core.settings import FormatSettings
from aynthor.ui.theme import Mode

ORGANISATION = "AynThorCompression"
APPLICATION = "AynThorCompression"


def _store() -> QSettings:
    return QSettings(ORGANISATION, APPLICATION)


def load_mode() -> Mode:
    raw = str(_store().value("ui/theme", Mode.SYSTEM.value))
    try:
        return Mode(raw)
    except ValueError:
        return Mode.SYSTEM


def save_mode(mode: Mode) -> None:
    _store().setValue("ui/theme", mode.value)


def restore_geometry() -> QByteArray | None:
    value = _store().value("window/geometry")
    return value if isinstance(value, QByteArray) else None


def save(settings: FormatSettings, geometry: QByteArray) -> None:
    store = _store()
    store.setValue("window/geometry", geometry)
    store.setValue("job/output_dir", settings.output_dir)
    store.setValue("job/esde_root", settings.esde_root)
    store.setValue("job/on_conflict", settings.on_conflict)
    store.setValue("job/switch_subdirs", settings.switch_game_subdirs)
    store.setValue("job/keys_path", settings.keys_path)
    # Per-format options are a dict of dicts; JSON keeps that intact across the
    # registry, which stores everything as strings.
    store.setValue("job/options", json.dumps(
        {fmt.value: options for fmt, options in settings.options.items()}))


def load_into(settings: FormatSettings) -> None:
    """Fill a FormatSettings from what was saved. Anything unreadable is skipped."""
    store = _store()
    settings.output_dir = str(store.value("job/output_dir", ""))
    settings.esde_root = str(store.value("job/esde_root", ""))
    settings.on_conflict = str(store.value("job/on_conflict", "skip"))
    settings.keys_path = str(store.value("job/keys_path", ""))

    raw_flag = store.value("job/switch_subdirs", False)
    settings.switch_game_subdirs = (
        raw_flag if isinstance(raw_flag, bool) else str(raw_flag).lower() == "true")

    settings.options = _load_options(store)


def save_presets(presets: PresetTable) -> None:
    """Store only what the user changed, so a later default improvement still
    reaches anyone who never edited that platform."""
    _store().setValue("presets/overrides", json.dumps(presets.overrides()))


def load_presets_into(presets: PresetTable) -> None:
    raw = _store().value("presets/overrides", "")
    if not raw:
        return
    try:
        stored = json.loads(str(raw))
    except (TypeError, ValueError):
        return
    if isinstance(stored, dict):
        presets.apply_overrides(stored)


def _load_options(store: QSettings) -> dict[CompressionFormat, dict]:
    raw = store.value("job/options", "")
    if not raw:
        return {}
    try:
        stored = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}

    options: dict[CompressionFormat, dict] = {}
    for key, value in stored.items():
        try:
            fmt = CompressionFormat(key)
        except ValueError:
            continue  # a format that no longer exists
        if isinstance(value, dict):
            options[fmt] = value
    return options
