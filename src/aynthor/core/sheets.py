"""Cue sheets and GDI files, and the track files they point at.

A `.cue` or `.gdi` is a few hundred bytes. The disc is in the `.bin` or `.raw`
files it lists, so anything that copies, sends, sizes or deletes the sheet has
to do the same to those, or a moved game arrives without its data.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

SHEET_EXTS = frozenset({".cue", ".gdi"})

# A sheet bigger than this is not a sheet; do not read a mislabeled ISO.
_MAX_SHEET = 1024 * 1024

_CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)
# track  lba  type  sector-size  file  offset
_GDI_TRACK = re.compile(r'^\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))\s+-?\d+\s*$')


def is_sheet(path: Path) -> bool:
    return path.suffix.lower() in SHEET_EXTS


def tracks(sheet: Path) -> list[Path]:
    """The files `sheet` lists, in order, each once.

    Only files in the sheet's own folder or below it count. A sheet that
    points at `..\\other\\track.bin` or `C:\\rips\\track.bin` is not going to
    work once it is copied anywhere else, and nothing here should reach
    outside the folder the user dropped.
    """
    if not is_sheet(sheet):
        return []
    try:
        if sheet.stat().st_size > _MAX_SHEET:
            return []
        raw = sheet.read_bytes()
    except OSError:
        return []
    text = raw.decode("utf-8-sig") if _is_utf8(raw) else raw.decode("latin-1")
    pattern = _GDI_TRACK if sheet.suffix.lower() == ".gdi" else _CUE_FILE

    found: list[Path] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        relative = _inside(match.group(1) or match.group(2))
        if relative is None:
            continue
        path = sheet.parent.joinpath(*relative.parts)
        folded = str(relative).casefold()
        if folded not in seen:
            seen.add(folded)
            found.append(path)
    return found


def relative_tracks(sheet: Path) -> list[PurePosixPath]:
    """`tracks`, as paths relative to the sheet's folder."""
    return [PurePosixPath(*t.relative_to(sheet.parent).parts) for t in tracks(sheet)]


def missing_track(sheet: Path) -> str:
    """Why the disc cannot be copied as it is, or "" when every track is there."""
    for track in tracks(sheet):
        if not track.is_file():
            return (f"{sheet.name} lists {track.relative_to(sheet.parent).as_posix()}, "
                    "which isn't in the same folder.")
    return ""


def disc_size(path: Path) -> int:
    """The bytes a row really stands for: the sheet and every track it lists
    that is there."""
    total = 0
    for part in (path, *tracks(path)):
        try:
            total += part.stat().st_size
        except OSError:
            continue
    return total


def _inside(name: str) -> PurePosixPath | None:
    """`name` as a relative path that stays in the sheet's folder, whichever
    slash the tool that wrote the sheet used."""
    name = name.strip()
    if not name:
        return None
    windows = PureWindowsPath(name)
    if windows.drive or windows.root or name.startswith("/"):
        return None
    parts = [p for p in windows.parts if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return PurePosixPath(*parts)


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
