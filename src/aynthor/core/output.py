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

# Path separators, the drive colon, and the rest of what Windows refuses in a
# file name. Any of them means the text was never a single folder name.
_FORBIDDEN_IN_NAME = frozenset('/\\:*?"<>|\0')

# CON, PRN and friends are devices, not files: opening one hangs or writes to
# hardware. Windows refuses them with any extension, so the stem is checked.
_RESERVED_ON_WINDOWS = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

_MAX_NAME = 120


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
    folder = safe_folder_name(game_group)
    if settings.switch_game_subdirs and folder:
        return (base or path.parent) / folder / suggested.name
    if base:
        return base / suggested.name
    return suggested


def safe_folder_name(name: str) -> str:
    """One folder name, or "" when the text cannot be one.

    Why
        The Switch grouping folder is the game name, and for an imported list
        that name is a line out of a text file somebody handed the user. Left
        alone it decides where the converter writes: `../../../Startup` walks
        out of the output folder, and on Windows `C:/Windows/Temp` replaces it
        outright, because joining an absolute path discards everything to its
        left. The converter then writes there with overwrite already on.

        So the text is reduced to a single component. Separators and the drive
        colon are replaced rather than stripped, because stripping `..` out of
        `....//` leaves `..` again; the characters Windows forbids in a name go
        with them, and a name that is only dots is refused outright.
    """
    cleaned = "".join("_" if ch in _FORBIDDEN_IN_NAME else ch for ch in name).strip()
    # A trailing dot or space is legal to create and impossible to open on
    # Windows, and NTFS streams hide behind a colon, which is already replaced.
    cleaned = cleaned.rstrip(". ")
    if not cleaned or cleaned in {".", ".."} or set(cleaned) <= {"."}:
        return ""
    if cleaned.upper().split(".")[0] in _RESERVED_ON_WINDOWS:
        return f"_{cleaned}"
    return cleaned[:_MAX_NAME]


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
