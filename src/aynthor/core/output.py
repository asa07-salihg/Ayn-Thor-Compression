"""Where a converted file is written.

Why
    Three separate rules decide this and they have an order: an ES-DE ROMs
    folder wins for a row that knows its platform, then a plain output folder,
    then the input's own folder. Keeping them here rather than in the queue
    widget is the same rule the rest of `core` follows, and it is why they can
    be tested without Qt or a display server -- which is exactly what caught
    them being in the wrong module.

Used by
    `ui.queue_view`, for every row it renders.

Reference
    Output naming per format: `core.formats.suggest_output_path`.
    ES-DE folder names: `core.esde`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from aynthor.core import esde
from aynthor.core.esde import ESDE_PLATFORM_FOLDERS
from aynthor.core.formats import suggest_output_path
from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.settings import FormatSettings


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
