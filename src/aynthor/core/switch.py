"""Tell a Switch base game, update and DLC apart, and group them.

Why
    A Switch title arrives as several files that must stay together: the base
    game, an update, and any number of DLC. Compressing them is fine, but a
    user who ends up with an update and no base has a game that will not
    install, so the queue shows what each file is and warns when a set is
    incomplete.

    Two signals are used, in order of reliability. A title id in the filename
    is definitive: the Switch encodes content type in its last three hex
    digits (000 base, 800 update, anything else DLC). Failing that, the
    filename markers scene groups and dumpers actually use are matched. A file
    with neither is assumed to be a base game, because that is what an
    untagged dump almost always is.

Used by
    `core.romlist` (collecting a game's whole set), `ui.queue_view` (the Game
    and Type columns), `ui.main_window` (the incomplete-set warnings).

Reference
    Title id ranges: https://switchbrew.org/wiki/Title_list
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

SWITCH_EXTENSIONS = frozenset({".nsp", ".xci", ".nsz", ".xcz"})

_TITLE_ID = re.compile(r"0100[0-9A-Fa-f]{12}", re.I)

_UPDATE_MARKERS = (
    re.compile(r"\[UPD(?:ATE)?\]", re.I),
    re.compile(r"\(update\)", re.I),
    re.compile(r"\bupdate\b", re.I),
    re.compile(r"\[patch\]", re.I),
    re.compile(r"\bpatch\b", re.I),
    re.compile(r"\bv\d+(?:\.\d+){1,3}\b", re.I),
)

_DLC_MARKERS = (
    re.compile(r"\[DLC\]", re.I),
    re.compile(r"\[AOC\]", re.I),
    re.compile(r"\bDLC\b", re.I),
    re.compile(r"\bAOC\b", re.I),
    re.compile(r"\bexpansion\b", re.I),
    re.compile(r"\bseason\s*pass\b", re.I),
)

# A bare "v0" or "v65536" is the NSP's version field, not a marker of what the
# file is: detection must not treat it as an update (every base game carries
# v0), but grouping must remove it, or a base game and its update normalise to
# two different names and never group together.
_VERSION_TOKEN = re.compile(r"\bv\d+\b", re.I)

_STRIP_MARKERS = (
    re.compile(r"\[base\]", re.I),
    re.compile(r"\(base\)", re.I),
    re.compile(r"\bbase\s+game\b", re.I),
    _VERSION_TOKEN,
    *_UPDATE_MARKERS,
    *_DLC_MARKERS,
)


class ContentType(str, Enum):
    BASE = "Base"
    UPDATE = "Update"
    DLC = "DLC"
    UNKNOWN = "?"


_CONTENT_ORDER = {
    ContentType.BASE: 0,
    ContentType.UPDATE: 1,
    ContentType.DLC: 2,
    ContentType.UNKNOWN: 3,
}


def is_switch_rom(path: Path) -> bool:
    return path.suffix.lower() in SWITCH_EXTENSIONS


def detect_content_type(path: Path) -> ContentType:
    name = path.stem
    for marker in _UPDATE_MARKERS:
        if marker.search(name):
            return ContentType.UPDATE
    for marker in _DLC_MARKERS:
        if marker.search(name):
            return ContentType.DLC

    tid = _TITLE_ID.search(name)
    if tid:
        tid_val = tid.group().upper()
        if tid_val.endswith("800"):
            return ContentType.UPDATE
        if tid_val.endswith("000"):
            return ContentType.BASE
        return ContentType.DLC

    return ContentType.BASE


def normalize_game_name(path: Path) -> str:
    name = path.stem
    name = _TITLE_ID.sub("", name)
    for marker in _STRIP_MARKERS:
        name = marker.sub("", name)
    name = re.sub(r"\bpack\s*\d+\b", "", name, flags=re.I)
    name = re.sub(r"\bdlc\s*\d*\b", "", name, flags=re.I)
    name = re.sub(r"[\[\](){}]+", " ", name)
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .-_")
    return name or path.stem


def sort_switch_files(files: list[Path]) -> list[Path]:
    return sorted(
        files,
        key=lambda p: (_CONTENT_ORDER.get(detect_content_type(p), 9), p.name.lower()),
    )


def group_switch_files(files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for path in files:
        if not is_switch_rom(path):
            continue
        key = normalize_game_name(path)
        groups.setdefault(key, []).append(path)
    for key in groups:
        groups[key] = sort_switch_files(groups[key])
    return groups


def content_warnings(types: list[ContentType | str]) -> list[str]:
    labels = {t.value if isinstance(t, ContentType) else str(t) for t in types}
    warnings: list[str] = []
    if "Update" in labels and "Base" not in labels:
        warnings.append("Update without Base")
    if "DLC" in labels and "Base" not in labels:
        warnings.append("DLC without Base")
    return warnings


def summarize_group(types: list[ContentType]) -> str:
    counts: dict[str, int] = {}
    for ct in types:
        counts[ct.value] = counts.get(ct.value, 0) + 1
    parts = []
    for label in ("Base", "Update", "DLC", "?"):
        n = counts.get(label, 0)
        if n:
            parts.append(f"{n} {label}" if n > 1 else label)
    return " + ".join(parts)
