"""Assign a queue row to a game folder, and find folders on a card.

Why
    ES-DE launches a folder named `Game.chd` by running the file inside that
    is also called `Game.chd`. The queue is a tree of those folders, and a
    file the app could not group is fixed by dropping it onto one: that sets
    the output to `Game.chd/<file>`, and if the file is the primary ROM the
    name becomes the folder's name exactly.

    Add folder also has to show the directories themselves. A freshly copied
    ES-DE `ROMs/` tree is full of `psx/`, `snes` and friends that hold only
    `systeminfo.txt`. Those are still the folders the user wants to see and
    drop dumps into, even though none of them is named like a ROM.

    When the card already holds a base game folder, a later DLC or disc is
    matched by title header (one name is a prefix of the other) — not by
    keywords like "dlc" or "update".

Used by
    `ui.queue_view` (tree grouping and drag-and-drop), `ui.main_window`
    (folders found by Add folder).

Reference
    ES-DE "Directories interpreted as files":
    https://gitlab.com/es-de/emulationstation-de/-/blob/master/USERGUIDE.md
"""

from __future__ import annotations

from pathlib import Path

from aynthor.core.esde import is_platform_folder, platform_from_path
from aynthor.core.formats import known_extensions
from aynthor.core.models import QueueItem
from aynthor.core.output import (
    aligned_folder,
    file_name_in_folder,
    is_game_folder,
    output_for,
    safe_folder_name,
    strip_disc_tag,
    system_folder_of,
)
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import titles_share_game

# Directories Add folder should not turn into queue nodes. Hidden names,
# VCS metadata, and Windows' own volume folder are never ROMs.
_SKIP_DIR_NAMES = frozenset({
    "__pycache__", ".git", "node_modules", "System Volume Information",
})


def discover_game_folders(root: Path) -> list[Path]:
    """Every directory named like a ROM, including empty ones.

    Add folder used to skip these because it only looked for files. An empty
    `Game.chd/` is still a drop target: that is how a title's folder exists
    before the dump is dropped into it.
    """
    return [p for p in discover_folders(root) if is_game_folder(p)]


def discover_folders(root: Path) -> list[Path]:
    """Directories to show in the queue after Add folder, including empty ones.

    Every subdirectory is a drop target: platform folders (`psx`, `snes`)
    with no ROMs yet, game folders (`Game.chd`), and any other folder the
    user picked. The selected folder itself is included when it is a game
    folder, a platform folder (`psx`), or a directory with no subfolders.
    A `ROMs/` tree is not wrapped in an extra node: adding it lists `psx`,
    `snes` and the rest directly.
    """
    if not root.is_dir():
        return []
    found: list[Path] = []
    try:
        child_dirs = [p for p in root.iterdir() if p.is_dir() and _keep_dir(p)]
    except OSError:
        child_dirs = []
    # The folder the user picked is a drop target unless it is a ROMs tree
    # whose children (psx, snes, ...) are the folders they want to see.
    if is_game_folder(root) or is_platform_folder(root) or not child_dirs:
        found.append(root)
    for path in root.rglob("*"):
        if path.is_dir() and _keep_dir(path):
            found.append(path)
    return _unique_paths(found)


def folder_kind(path: Path) -> str:
    """`game`, `platform`, or `dir` — how the tree treats a dropped-on folder."""
    if is_game_folder(path):
        return "game"
    if is_platform_folder(path):
        return "platform"
    return "dir"


def best_disk_game_folder(title: str, folders: list[Path]) -> Path | None:
    """The shortest game-folder stem that shares a header with `title`.

    Matching is prefix-only: `Ys X Nordics` owns `Ys X Nordics … anything`.
    Disc tags are stripped from the title first so disc 2 still finds disc 1's
    folder. Keywords like dlc/update are not consulted.
    """
    needle = (strip_disc_tag(title) or title).strip()
    if not needle:
        return None
    best: Path | None = None
    best_len = 10**9
    for folder in folders:
        if not is_game_folder(folder):
            continue
        stem = folder.stem
        if not titles_share_game(needle, stem):
            continue
        if len(stem) < best_len:
            best = folder
            best_len = len(stem)
    return best


def on_disk_members(folder: Path) -> list[Path]:
    """ROM files already sitting in a game folder on the card."""
    if not folder.is_dir():
        return []
    roms = known_extensions()
    found: list[Path] = []
    try:
        children = list(folder.iterdir())
    except OSError:
        return []
    for path in children:
        if path.is_file() and path.suffix.lower() in roms:
            found.append(path)
    return sorted(found, key=lambda p: p.name.lower())


def rename_game_folder(folder: Path, new_stem: str) -> Path:
    """Rename a game folder on disk and the primary ROM inside it.

    ES-DE launches `Title.nsp/Title.nsp`. Renaming only the folder leaves
    `New.nsp/Old.nsp`, which will not start.
    """
    stem = safe_folder_name(new_stem) or new_stem.strip()
    if not stem:
        raise ValueError("empty folder name")
    target = folder.with_name(f"{stem}{folder.suffix}")
    if target == folder:
        return folder
    if target.exists():
        raise FileExistsError(f"already exists: {target.name}")
    primary_name = folder.name
    folder.rename(target)
    primary = target / primary_name
    desired = target / target.name
    if primary.is_file() and primary != desired:
        if desired.exists():
            raise FileExistsError(f"already exists: {desired.name}")
        primary.rename(desired)
    return target


def _keep_dir(path: Path) -> bool:
    name = path.name
    return not (name.startswith(".") or name in _SKIP_DIR_NAMES)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def group_folder_name(item: QueueItem, settings: FormatSettings) -> str:
    """The tree folder this row belongs under, or "" if it is unassigned."""
    options = item.tool_options or {}
    if forced := str(options.get("game_folder", "")):
        content = str(options.get("content_type", "")).lower()
        if options.get("disk_anchor") or content in ("update", "dlc"):
            return forced
        return aligned_folder(forced, item.output.name) if item.output.suffix else forced
    if is_game_folder(item.output.parent):
        return item.output.parent.name
    if is_game_folder(item.path.parent):
        if item.format is not None:
            content = str(options.get("content_type", "")).lower()
            if content in ("update", "dlc"):
                return item.path.parent.name
            return aligned_folder(item.path.parent.name, item.output.name)
        return item.path.parent.name
    if item.game_group:
        suffix = item.output.suffix or Path(item.source_name).suffix
        return f"{safe_folder_name(item.game_group)}{suffix}"
    return ""


def assign_to_folder(
    item: QueueItem,
    folder: str,
    settings: FormatSettings,
    *,
    platform: str = "",
) -> QueueItem:
    """Put this row in `folder`. The primary ROM is renamed to match it."""
    options = dict(item.tool_options or {})
    platform = platform or item.platform
    options["game_group"] = safe_folder_name(Path(folder).stem)
    options["game_folder"] = folder
    item.tool_options = options
    item.game_group = options["game_group"]
    if platform:
        item.platform = platform
    if item.format is None:
        name = file_name_in_folder(folder, item.source_name, options)
        item.output = system_folder_of(item.path) / folder / name
        return item
    item.output = output_for(
        item.path, item.format, item.mode, settings, options, item.platform, item.member)
    return item


def unassign(item: QueueItem, settings: FormatSettings) -> QueueItem:
    """Take the row out of a game folder; it becomes a top-level file again."""
    options = dict(item.tool_options or {})
    options.pop("game_folder", None)
    item.tool_options = options
    if item.format is None:
        item.output = item.path
        return item
    item.output = output_for(
        item.path, item.format, item.mode, settings, options, item.platform, item.member)
    return item


def folder_platform(folder: Path) -> str:
    return platform_from_path(folder)
