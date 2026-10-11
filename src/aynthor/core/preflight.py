"""Find what would make a batch fail, before Start runs anything.

Why
    Pressing Start with chdman missing turned every row red, one after
    another, with the reason in a log that was closed. A missing `prod.keys`
    was found only when the first Switch row failed, and a file whose console
    was not recognised was quietly written next to its original instead of
    into the ROMs folder. All three are knowable before anything runs, so the window
    asks about them up front and offers a fix or a way to leave those files out.

    Which program a row needs follows the runner exactly: a Move, or a file
    that is already the container its platform wants, is only copied, and
    opening a 3DS file falls back to the built-in decoder. Warning about a
    program those rows never call would teach people to ignore the warning.

Used by
    `ui.main_window` (Start, and the Start button's tooltip),
    `ui.preflight_dialog`.

Reference
    What each converter runs: `core.converters`.
    Program keys: `core.tools.manifest`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from aynthor.core.esde import ESDE_PLATFORM_FOLDERS
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.settings import FormatSettings
from aynthor.core.system import find_prod_keys

# Program keys from the manifest, per format. A tuple is "any one of these".
_PROGRAM: dict[CompressionFormat, tuple[str, ...]] = {
    CompressionFormat.CHD: ("chdman",),
    CompressionFormat.RVZ: ("DolphinTool",),
    CompressionFormat.CSO: ("maxcso",),
    CompressionFormat.NDS_TRIM: ("ndstrim",),
    CompressionFormat.NSZ: ("nsz",),
    CompressionFormat.SEVEN_ZIP: ("7z",),
    CompressionFormat.WUA: ("rom-converto",),
    CompressionFormat.DEC_3DS: ("3ds-decryptor",),
    CompressionFormat.Z3DS: ("rom-converto", "z3ds_compress"),
}


class ProblemKind(str, Enum):
    MISSING_TOOLS = "missing_tools"
    NO_SWITCH_KEYS = "no_switch_keys"
    UNKNOWN_PLATFORM = "unknown_platform"


@dataclass(frozen=True)
class Problem:
    kind: ProblemKind
    rows: tuple[int, ...]
    tools: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        """Whether those rows would fail. An unknown console still converts;
        it just does not land in the ROMs folder."""
        return self.kind is not ProblemKind.UNKNOWN_PLATFORM


def needed_programs(item: QueueItem) -> list[tuple[str, ...]]:
    """What this row needs installed. Each entry is met by any one of its keys."""
    if item.format is None or (item.tool_options or {}).get("on_disk"):
        return []
    needs: list[tuple[str, ...]] = []
    if item.member and item.path.suffix.lower() == ".7z":
        needs.append(_PROGRAM[CompressionFormat.SEVEN_ZIP])
    if _only_copies(item):
        return needs
    if item.format is CompressionFormat.Z3DS and item.mode is ConversionMode.DECOMPRESS:
        return needs
    program = _PROGRAM.get(item.format)
    if program and program not in needs:
        needs.append(program)
    return needs


def missing_programs(
    queue: list[tuple[int, QueueItem]],
    is_available: Callable[[str], bool],
) -> dict[str, list[int]]:
    """Program key to the rows that cannot run without it, in queue order."""
    missing: dict[str, list[int]] = {}
    for row, item in queue:
        for choices in needed_programs(item):
            if not any(is_available(key) for key in choices):
                missing.setdefault(choices[0], []).append(row)
    return missing


def check_queue(
    queue: list[tuple[int, QueueItem]],
    settings: FormatSettings,
    *,
    is_available: Callable[[str], bool],
    find_keys: Callable[[], Path | None] = find_prod_keys,
) -> list[Problem]:
    """Every problem in the queue, blocking ones first."""
    problems: list[Problem] = []

    missing = missing_programs(queue, is_available)
    if missing:
        rows = sorted({row for found in missing.values() for row in found})
        problems.append(Problem(ProblemKind.MISSING_TOOLS, tuple(rows), tuple(missing)))

    keyless = [row for row, item in queue if _needs_keys(item) and not _has_keys(
        item, settings, find_keys)]
    if keyless:
        problems.append(Problem(ProblemKind.NO_SWITCH_KEYS, tuple(keyless)))

    if settings.esde_root:
        unknown = [row for row, item in queue
                   if _converts(item) and not ESDE_PLATFORM_FOLDERS.get(item.platform)]
        if unknown:
            problems.append(Problem(ProblemKind.UNKNOWN_PLATFORM, tuple(unknown)))
    return problems


def _converts(item: QueueItem) -> bool:
    return item.format is not None and not (item.tool_options or {}).get("on_disk")


def _only_copies(item: QueueItem) -> bool:
    if item.mode is ConversionMode.MOVE:
        return True
    if item.format is CompressionFormat.NDS_TRIM or item.mode is ConversionMode.DECOMPRESS:
        return False
    source = Path(item.member) if item.member else item.path
    return source.suffix.lower() == item.output.suffix.lower()


def _needs_keys(item: QueueItem) -> bool:
    return (_converts(item) and item.format is CompressionFormat.NSZ
            and item.mode is not ConversionMode.MOVE)


def _has_keys(
    item: QueueItem, settings: FormatSettings, find_keys: Callable[[], Path | None],
) -> bool:
    chosen = (item.tool_options or {}).get("keys_path") or settings.keys_path
    if chosen:
        return Path(chosen).is_file()
    return find_keys() is not None
