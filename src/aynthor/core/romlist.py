"""Parse an Ayn Thor list file and match its entries to files on disk.

Why
    The list is a plain text file of `game -> platform -> FORMAT` lines,
    written for a person to read. It names games, not filenames, and real dumps
    carry region tags, revision numbers and release-group suffixes that no
    exact match would survive. So matching is done on keywords: the first few
    significant words of the title, scored against each candidate filename,
    with at least two having to hit before a match is accepted. Two is the
    threshold that stopped "Mario Kart" from matching "Mario Party".

    Switch is handled separately because one list entry is several files. A
    game there is a base title plus its update and any DLC, and installing an
    update without its base does nothing, so the whole set is collected and
    returned together.

Used by
    `ui.main_window._import_list`.

Reference
    The list file format, with a worked example: examples/sample-list.txt.
    A sample list: examples/ayn-thor-max.list.txt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from aynthor.core.esde import search_dirs
from aynthor.core.models import CompressionFormat
from aynthor.core.presets import PRESETS, SKIP_PLATFORMS, PresetTable
from aynthor.core.switch import (
    SWITCH_EXTENSIONS,
    detect_content_type,
    normalize_game_name,
    sort_switch_files,
)

# Two line shapes are accepted, because real lists use both.
#
#   Chrono Cross -> psx -> CHD
#   | Chrono Cross | psx | CHD | done |
#
# The arrow form is what the list generator emits. The table form is what the
# list turns into the moment someone pastes it into a Markdown document to tick
# titles off, which is what most of these lists actually look like by the time
# they reach this app. Reading only the arrow form meant a table-shaped list
# imported nothing at all, with no error to explain why.
_ARROW_LINE = re.compile(r"^\s*(.+?)\s*->\s*(\S+)\s*->\s*(\S+)\s*$")

# Box drawing and headings from the generator's own preamble.
_IGNORED_PREFIXES = ("=", "#", ">", "\u2550", "\u2554", "\u2560", "\u255a", "\u2551")

# Table cells that are structure, not data. The Turkish words are here because
# these lists are commonly written in Turkish, where the header row reads
# "Oyun | Klasor | Format"; without them the header imported as a game called
# "Oyun".
_TABLE_HEADINGS = {
    "game", "title", "folder", "format", "system", "platform",
    "oyun", "klasor", "klas\u00f6r", "bi\u00e7im",
}


@dataclass
class ListEntry:
    game: str
    platform: str
    target_format: str
    line_no: int


def _parse_arrow_line(line: str) -> tuple[str, str, str] | None:
    match = _ARROW_LINE.match(line)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()


def _parse_table_row(line: str) -> tuple[str, str, str] | None:
    """Read `| Game | folder | FORMAT |`, ignoring any further columns."""
    if not line.startswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 3:
        return None
    game, platform, target = cells[0], cells[1], cells[2]
    if not game or not platform or not target:
        return None
    # The header row, and the |---|---| separator under it.
    if game.lower() in _TABLE_HEADINGS or set(game) <= set("- :"):
        return None
    # A platform is one token. A sentence in that column means this row is
    # prose that happens to be in a table, not a game entry.
    if len(platform.split()) != 1:
        return None
    return game, platform, target


def parse_list_file(path: Path) -> list[ListEntry]:
    """Read a list file. Unreadable lines are skipped rather than fatal.

    These files are written by hand and carry headings, notes and box drawing
    between the entries. Refusing the whole file over one stray line would make
    the feature unusable.
    """
    entries: list[ListEntry] = []
    text = path.read_text(encoding="utf-8", errors="replace")

    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(_IGNORED_PREFIXES):
            continue

        parsed = _parse_table_row(line) or _parse_arrow_line(line)
        if parsed is None:
            continue

        game, platform, target = parsed
        entries.append(ListEntry(game, platform.lower(), target.upper(), line_no))

    return entries


def summarize_list(entries: list[ListEntry]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in entries:
        counts[e.target_format] = counts.get(e.target_format, 0) + 1
    return counts


def _game_keywords(game_name: str) -> list[str]:
    """Significant words from a title, for scoring against real filenames.

    Digits are kept even though they are short: they are what separates
    "Persona 4" from "Persona 3" and "Halo 3" from "Halo". Dropping them left
    such titles with a single keyword, which then could never reach the
    two-keyword threshold and so never matched anything at all.
    """
    clean = re.sub(r"[^\w\s\-'.&+:!#]", "", game_name).strip()
    words = re.split(r"[\s:/]+", clean)
    return [w.lower() for w in words if len(w) > 2 or w.isdigit()][:4]


def _score_name(lowered_name: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in lowered_name)


class RomIndex:
    """The files under each platform's folders, listed once.

    Matching used to walk the whole platform folder again for every line of the
    list. A real list is over a thousand lines and a real card is tens of
    thousands of files, so importing one meant a thousand full directory walks
    over an SD card. Now each platform is walked at most once per import, and
    the lowercased filename each entry is scored against is computed once
    rather than once per line.
    """

    def __init__(self, roms_root: Path) -> None:
        self.roms_root = roms_root
        self._by_platform: dict[str, list[tuple[Path, str]]] = {}

    def files(self, platform: str) -> list[tuple[Path, str]]:
        """(path, lowercased stem) for everything under that platform."""
        cached = self._by_platform.get(platform)
        if cached is not None:
            return cached

        found: list[tuple[Path, str]] = []
        for directory in search_dirs(self.roms_root, platform):
            for candidate in directory.rglob("*"):
                if candidate.is_file():
                    found.append((candidate, candidate.stem.lower()))
        self._by_platform[platform] = found
        return found


def _find_best_match(index: RomIndex, platform: str, game_name: str) -> Path | None:
    keywords = _game_keywords(game_name)
    if not keywords:
        return None

    # Two keywords have to hit before a match is accepted, which is what stops
    # "Mario Kart" from matching "Super Mario World". A title that yields only
    # one keyword has to settle for one, or it could never match at all.
    required = 2 if len(keywords) >= 2 else 1

    best: Path | None = None
    best_score = 0
    for candidate, lowered in index.files(platform):
        score = _score_name(lowered, keywords)
        if score > best_score:
            best_score = score
            best = candidate
    return best if best_score >= required else None


def _find_switch_rom_set(index: RomIndex, game_name: str) -> list[Path]:
    """Every file belonging to one Switch title: base, update and any DLC."""
    best = _find_best_match(index, "switch", game_name)
    if best is None:
        return []

    # A title that lives in its own folder brings the whole folder with it.
    for directory in search_dirs(index.roms_root, "switch"):
        try:
            relative = best.parent.relative_to(directory)
        except ValueError:
            continue
        if relative.parts:
            siblings = [f for f in best.parent.iterdir()
                        if f.is_file() and f.suffix.lower() in SWITCH_EXTENSIONS]
            if siblings:
                return sort_switch_files(siblings)

    # Otherwise collect by normalised name across the whole switch tree.
    game_key = normalize_game_name(best)
    keywords = _game_keywords(game_name)
    matches: list[Path] = []
    for candidate, lowered in index.files("switch"):
        if candidate.suffix.lower() not in SWITCH_EXTENSIONS:
            continue
        if normalize_game_name(candidate) == game_key or _score_name(lowered, keywords) >= 2:
            matches.append(candidate)

    return sort_switch_files(matches) if matches else [best]


def find_rom_files(
    roms_root: Path,
    platform: str,
    game_name: str,
    index: RomIndex | None = None,
) -> list[Path]:
    """Files matching one list entry. Several for Switch, at most one otherwise."""
    table = index if index is not None else RomIndex(roms_root)
    if platform == "switch":
        return _find_switch_rom_set(table, game_name)
    match = _find_best_match(table, platform, game_name)
    return [match] if match else []


def find_rom_file(roms_root: Path, platform: str, game_name: str) -> Path | None:
    files = find_rom_files(roms_root, platform, game_name)
    return files[0] if files else None


@dataclass(frozen=True)
class QueuedEntry:
    """One list entry matched to one file on disk."""

    path: Path
    platform: str
    format: CompressionFormat
    options: dict


def entries_to_queue(
    entries: list[ListEntry],
    roms_root: Path,
    presets: PresetTable | None = None,
) -> list[QueuedEntry]:
    """Match every entry to real files and attach that platform's settings.

    One entry can produce several files: a Switch title is a base game plus its
    update and DLC, and they install as a set.
    """
    table = presets if presets is not None else PRESETS
    result: list[QueuedEntry] = []
    # One index for the whole import, so each platform folder is walked once
    # rather than once per line.
    index = RomIndex(roms_root)

    for entry in entries:
        if entry.platform in SKIP_PLATFORMS or entry.target_format in {"-", "Z64"}:
            continue
        preset = table.get(entry.platform)
        if preset is None:
            continue

        for found in find_rom_files(roms_root, entry.platform, entry.game, index):
            options = dict(preset.options)
            # The list knows the real title; the filename usually does not.
            options["game_group"] = entry.game
            if entry.platform == "switch":
                options["content_type"] = detect_content_type(found).value
            result.append(QueuedEntry(found, entry.platform, preset.format, options))
    return result
