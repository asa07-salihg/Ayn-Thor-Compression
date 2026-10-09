"""Tell a Switch base game, update and DLC apart, and group them.

Why
    Base and update are easy (title id, or the words update/dlc/pack). The
    only grouping rule that matters after that: once a base title is known,
    every file whose name starts with that title belongs in the same tree.

    Dump names use underscores (`pack_dlc`). Those become spaces first so
    markers and headers can be read.

Used by
    `core.romlist`, `ui.queue_view`, `ui.main_window`.

Reference
    Title id ranges: https://switchbrew.org/wiki/Title_list
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import Enum
from pathlib import Path

SWITCH_EXTENSIONS = frozenset({".nsp", ".xci", ".nsz", ".xcz"})

_TITLE_ID = re.compile(r"0100[0-9A-Fa-f]{12}", re.I)

# The bits of a title id that say which part of a title this is, rather than
# which title. See `title_family`.
_FAMILY_MASK = ~0x1FFF

# `[DLC]`, `(update)`, `[v1.2.0]`: what a dumper wrote about the file, as
# opposed to the title itself. Read before the title id; the title is read
# only when there is no id at all.
_BRACKETED_TAG = re.compile(r"[\[({]([^\[\](){}]*)[\])}]")

_UPDATE_WORD = re.compile(
    r"\b(update|upd|patch)\b|\bv\d+(?:\.\d+){1,3}\b|\b\d+\.\d+(?:\.\d+){1,2}\b",
    re.I,
)
_DLC_WORD = re.compile(
    r"\b(dlc|aoc|pack|expansion|freebie|costume|season\s+pass)\b|"
    r"\bset\s*(?:\d+|[a-z])\b",
    re.I,
)

# Strip only a short pack tail at the end (one brand word + set/pack, or dlc).
_TRAILING_JUNK = re.compile(
    r"\s+(?:"
    r"\S+\s+cover\s+set\s*(?:\d+|[a-z])|"
    r"\S+\s+set\s*(?:\d+|[a-z])|"
    r"\S+\s+pack|"
    r"(?:dlc|aoc|update|upd|patch|expansion|costume|freebie|"
    r"season\s+pass|base\s+game|base)"
    r")\b.*$",
    re.I,
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


def title_family(path: Path) -> str:
    """The id a base game, its update and its DLC all share.

    A title id is 16 hex digits and the low 13 bits are the content type:
    a base ends `…000`, its update is base + 0x800, and its DLC ids run from
    base + 0x1001 upwards. Masking those bits off is what puts the three in
    one family.

    This used to keep the first 13 characters, which is right for an update
    (only the last three digits move) and wrong for DLC, whose fourth digit
    from the end moves too. Real DLC therefore never joined its base:
    `01007EF00011E000` and `01007EF00011F001` are Tears of the Kingdom and
    its DLC, and the old prefix made them two different games.
    """
    found = _TITLE_ID.search(path.stem)
    if not found:
        return ""
    return f"{int(found.group(), 16) & _FAMILY_MASK:016X}"


def _id_says_base(stem: str) -> bool:
    """The name carries a title id and that id is a base game's."""
    found = _TITLE_ID.search(stem)
    if found is None:
        return False
    return found.group().upper().endswith("000")


def _readable(name: str) -> str:
    """`pack_dlc` / `v-ys_x` → words. Underscore is a word char; spaces are not."""
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"[\[\](){}]+", " ", name)
    return re.sub(r"\s+", " ", name).strip(" .-_")


def detect_content_type(path: Path) -> ContentType:
    """Base, update or DLC, read from the dump name.

    A marker a dumper put in brackets is read first, because `[DLC]` is a
    statement about the file and beats everything. After that the title id
    decides, and only a file with no id falls back to reading the bare title.

    That order matters because these words are also ordinary English. The
    Jackbox Party Pack 8 is a base game whose name contains "pack", and
    matching the whole title first typed it as DLC, merged it with Party
    Pack 9 under a truncated name, and warned about DLC with no base.
    """
    stem = path.stem
    tagged = " ".join(_readable(tag) for tag in _BRACKETED_TAG.findall(stem))
    if _UPDATE_WORD.search(tagged):
        return ContentType.UPDATE
    if _DLC_WORD.search(tagged):
        return ContentType.DLC

    tid = _TITLE_ID.search(stem)
    if tid:
        tid_val = tid.group().upper()
        if tid_val.endswith("800"):
            return ContentType.UPDATE
        if tid_val.endswith("000"):
            return ContentType.BASE
        return ContentType.DLC

    name = _readable(stem)
    if _UPDATE_WORD.search(name):
        return ContentType.UPDATE
    # A cartridge is the base game. "Party Pack" is the title, and reading
    # "pack" as DLC put the cart in its own folder beside the NSP update.
    if path.suffix.lower() in {".xci", ".xcz"}:
        return ContentType.BASE
    if _DLC_WORD.search(name):
        return ContentType.DLC
    return ContentType.BASE


def normalize_game_name(path: Path) -> str:
    name = _readable(path.stem)
    name = _TITLE_ID.sub("", name)
    name = re.sub(r"^v\d*\s+", "", name, flags=re.I)
    name = re.sub(r"\bv\d+\b", "", name, flags=re.I)
    name = re.sub(r"\b\d+\.\d+(?:\.\d+)*\b", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .-_")
    if not _id_says_base(path.stem):
        # Only a file that might be an add-on gets its tail trimmed. When the
        # title id ends `000` the file is the base game and every word in its
        # name is part of the title: "The Jackbox Party Pack 8" was being cut
        # down to "The Jackbox", which is not a game and grouped Pack 8 and
        # Pack 9 into one folder.
        name = _TRAILING_JUNK.sub("", name).strip(" .-_")
    name = _drop_repeated_tail(name)
    return name or _readable(path.stem) or path.stem


def _drop_repeated_tail(name: str) -> str:
    """Collapse a title that dumps repeat in the name.

    `… Cold Steel III Cold Steel III` (adjacent block) and
    `ys x nordics ys x …` (opening title echoed later).
    """
    words = name.split()
    n = len(words)
    if n < 3:
        return name
    for size in range(n // 2, 0, -1):
        for start in range(0, n - 2 * size + 1):
            if words[start:start + size] == words[start + size:start + 2 * size]:
                return " ".join(words[: start + size] + words[start + 2 * size :])
    for size in range(min(n // 2, 8), 0, -1):
        prefix = words[:size]
        for start in range(size, n - size + 1):
            if words[start:start + size] == prefix:
                return " ".join(words[:start])
        for shorter in range(1, size):
            echo = words[:shorter]
            for start in range(size, n - shorter + 1):
                if words[start:start + shorter] == echo:
                    return " ".join(words[:start])
    return name


def titles_share_game(left: str, right: str) -> bool:
    """Same game when one title is the header (prefix) of the other.

    That is the whole rule: base `Ys X Nordics` owns every
    `Ys X Nordics … whatever pack dlc` name.
    """
    a, b = left.strip(), right.strip()
    if not a or not b:
        return False
    al, bl = a.casefold(), b.casefold()
    return al == bl or al.startswith(bl + " ") or bl.startswith(al + " ")


def canonical_title(*names: str) -> str:
    """Shortest title among names that share a header."""
    cleaned = [n.strip() for n in names if n and n.strip()]
    if not cleaned:
        return ""
    return min(cleaned, key=len)


def common_word_prefix(left: str, right: str) -> str:
    a = left.casefold().split()
    b = right.casefold().split()
    out: list[str] = []
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        out.append(x)
    return " ".join(out)


def sort_switch_files(files: list[Path]) -> list[Path]:
    return sorted(
        files,
        key=lambda p: (_CONTENT_ORDER.get(detect_content_type(p), 9), p.name.lower()),
    )


def group_switch_files(files: list[Path]) -> dict[str, list[Path]]:
    """Cluster by title id, else by header: shortest title wins as the key."""
    by_id: dict[str, list[Path]] = {}
    no_id: list[Path] = []
    for path in files:
        if not is_switch_rom(path):
            continue
        family = title_family(path)
        if family:
            by_id.setdefault(family, []).append(path)
        else:
            no_id.append(path)

    groups: dict[str, list[Path]] = {}
    for members in by_id.values():
        label = min((normalize_game_name(p) for p in members), key=len)
        groups.setdefault(label, []).extend(members)

    # Sort shortest title first so a base header absorbs longer DLC names.
    pending = sorted(no_id, key=lambda p: len(normalize_game_name(p)))
    for path in pending:
        label = normalize_game_name(path)
        parent = next(
            (existing for existing in groups if titles_share_game(label, existing)),
            None,
        )
        if parent is None:
            groups[label] = [path]
            continue
        key = canonical_title(parent, label) or parent
        if key != parent:
            groups.setdefault(key, []).extend(groups.pop(parent))
            parent = key
        groups.setdefault(parent, []).append(path)

    for key in groups:
        groups[key] = sort_switch_files(groups[key])
    return groups


def content_warnings(types: Sequence[ContentType | str]) -> list[str]:
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
