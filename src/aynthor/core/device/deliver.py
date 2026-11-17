"""Sending a finished game to the device, and deciding whether to at all.

A game bound for a device is converted into a staging folder on this PC that
mirrors the device's layout (`Staging/AYN Thor/disk/psx/Game.chd`), then sent
to the same place under the device's ROMs folder. Three decisions are made at
the moment a job starts rather than when the file was added:

* whether the file is already on the device, and what the conflict setting
  says to do about it. Checking first means a game that is already there is
  skipped before an hour is spent converting it;
* whether the copy converted on an earlier run can be reused. If the cable
  came out while sending, the converted file is still in staging, and a
  second Start sends it without converting it again;
* whether there is room, which is measured against the device and not the PC.
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aynthor.core.device.fs import (
    Cancelled,
    DeviceError,
    DeviceFS,
    DeviceTarget,
    Progress,
    SendCancelled,
)
from aynthor.core.sheets import tracks
from aynthor.core.system import app_data_dir

# Left free on the device after a file lands. A card filled to the last byte
# makes the next write fail somewhere less obvious than here.
HEADROOM = 64 * 1024 * 1024

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def staging_root(target: DeviceTarget, base: Path | None = None) -> Path:
    """The folder on this PC that stands in for the device's ROMs folder."""
    root = base if base is not None else app_data_dir() / "Staging"
    device = _UNSAFE.sub("_", target.device_name).strip(". ") or "Device"
    storage = _UNSAFE.sub("_", target.storage).strip(". ") or "Storage"
    return root / device / storage


def remote_for(local: Path, staging: Path) -> PurePosixPath | None:
    """Where on the device a staged file goes, relative to the ROMs folder.
    None for a file that is not under staging, which stays on this PC."""
    try:
        relative = local.relative_to(staging)
    except ValueError:
        return None
    if not relative.parts:
        return None
    return PurePosixPath(*relative.parts)


@dataclass(frozen=True)
class Plan:
    remote: PurePosixPath | None   # None: leave this job out
    replace: bool = False          # an older copy is removed first
    reason: str = ""


def _fold(path: PurePosixPath) -> str:
    """One spelling for a path. The device treats `Game.chd` and `game.chd`
    as the same file, so the set of what this run sent has to as well."""
    return str(path).replace("\\", "/").casefold()


def _taken(sent: set, path: PurePosixPath) -> bool:
    want = _fold(path)
    return any(_fold(item) == want for item in sent)


def plan(fs: DeviceFS, remote: PurePosixPath, policy: str,
         sent: set) -> Plan:
    """What to do about `remote`, given what is on the device and what this
    run has already sent there."""
    existing = fs.stat(remote)
    if existing is None and not _taken(sent, remote):
        return Plan(remote)
    if existing is not None and existing.is_dir:
        raise DeviceError(
            f"There is a folder called {remote.name} on {fs.label} where the file should go.")
    if policy == "skip":
        return Plan(None, reason=f"Already on {fs.label}")
    if policy == "overwrite" and not _taken(sent, remote):
        return Plan(remote, replace=existing is not None)
    # Rename, or an overwrite that would land on something this run wrote a
    # moment ago, which is another game, not an old copy of this one.
    counter = 1
    while True:
        candidate = remote.with_name(f"{remote.stem}_{counter}{remote.suffix}")
        if not _taken(sent, candidate) and fs.stat(candidate) is None:
            return Plan(candidate)
        counter += 1


def send(fs: DeviceFS, local: Path, decided: Plan,
         on_progress: Progress | None = None,
         cancelled: Cancelled | None = None) -> PurePosixPath:
    """Copy `local` to where `plan` decided, after checking there is room."""
    remote = decided.remote
    if remote is None:
        raise ValueError("send() called for a job the plan left out")
    # Before any folder is created or any old copy removed. Stop during the
    # conversion used to reach here afterwards and delete the game on the
    # device, then send nothing.
    if cancelled is not None and cancelled():
        raise SendCancelled("Stopped before the file was sent.")
    size = local.stat().st_size
    freed = 0
    if decided.replace:
        old = fs.stat(remote)
        freed = old.size if old is not None else 0
    free = fs.free_space()
    if size + HEADROOM > free + freed:
        raise DeviceError(
            f"{local.name} needs {_gb(size)} and {fs.label} has {_gb(free)} left.")
    fs.mkdirs(remote.parent)
    if decided.replace and fs.stat(remote) is not None:
        fs.remove(remote)
    fs.upload(local, remote, on_progress, cancelled)
    landed = fs.stat(remote)
    if landed is None or landed.size != size:
        raise DeviceError(
            f"{remote.name} arrived on {fs.label} at the wrong size. "
            "Unplug the cable, plug it back in and press Start again.")
    return remote


def send_disc(fs: DeviceFS, sheet: Path, tracks: list[PurePosixPath], decided: Plan,
              on_progress: Progress | None = None,
              cancelled: Cancelled | None = None,
              sent: set | None = None) -> PurePosixPath:
    """A cue sheet or GDI and the tracks it lists, which go in the same folder
    under their own names because that is what the sheet says.

    Tracks go first and the sheet last. The sheet is what the next Start
    looks for, so a disc cut off halfway is sent again rather than mistaken
    for one already there.
    """
    remote = decided.remote
    if remote is None:
        raise ValueError("send_disc() called for a job the plan left out")
    if cancelled is not None and cancelled():
        raise SendCancelled("Stopped before the file was sent.")
    claimed = sent if sent is not None else set()
    parts = [(sheet.parent.joinpath(*track.parts), remote.parent / track) for track in tracks]
    # A cue names its tracks. Two discs that both say track01.bin cannot share
    # one folder: replacing the track keeps the cue and loses the other disc.
    # Refuse before anything is deleted.
    for _local, there in parts:
        if _taken(claimed, there):
            raise DeviceError(
                f"{there.name} is already used by another disc in this run. "
                "Put each disc in its own folder.")
        existing = fs.stat(there)
        if existing is not None and existing.is_dir:
            raise DeviceError(
                f"There is a folder called {there.name} on {fs.label} "
                "where the track should go.")
        if existing is not None and not decided.replace:
            raise DeviceError(
                f"{there.name} is already on {fs.label}. "
                "Put each disc in its own folder.")
    sizes = [local.stat().st_size for local, _ in parts]
    total = sum(sizes) + sheet.stat().st_size
    freed = 0
    for _, there in [*parts, (sheet, remote)]:
        old = fs.stat(there) if decided.replace or there != remote else None
        freed += old.size if old is not None else 0
    free = fs.free_space()
    if total + HEADROOM > free + freed:
        raise DeviceError(
            f"{sheet.name} and its tracks need {_gb(total)} and {fs.label} has "
            f"{_gb(free)} left.")

    done = 0

    def scaled(size: int) -> Progress | None:
        if on_progress is None or total == 0:
            return on_progress
        start = done
        return lambda pct: on_progress(min(100, (start + size * pct // 100) * 100 // total))

    for (local, there), size in zip(parts, sizes, strict=True):
        send(fs, local, Plan(there, replace=decided.replace), scaled(size), cancelled)
        done += size
    return send(fs, sheet, decided, scaled(total - done), cancelled)


def send_tree(fs: DeviceFS, folder: Path, remote: PurePosixPath, decided: Plan,
              on_progress: Progress | None = None,
              cancelled: Cancelled | None = None,
              sent: set | None = None) -> list[PurePosixPath]:
    """Send every file inside an unpacked folder. The folder itself is not a file."""
    if cancelled is not None and cancelled():
        raise SendCancelled("Stopped before the file was sent.")
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    if not files:
        raise DeviceError(f"{folder.name} unpacked to an empty folder.")
    claimed = sent if sent is not None else set()
    targets: list[tuple[Path, PurePosixPath]] = []
    for path in files:
        relative = PurePosixPath(*path.relative_to(folder).parts)
        there = remote / relative
        if _taken(claimed, there):
            raise DeviceError(
                f"{there.name} is already used by another game in this run.")
        targets.append((path, there))
    total = sum(path.stat().st_size for path, _there in targets)
    free = fs.free_space()
    if total + HEADROOM > free:
        raise DeviceError(
            f"{folder.name} needs {_gb(total)} and {fs.label} has {_gb(free)} left.")
    done = 0
    sent_paths: list[PurePosixPath] = []
    for path, there in targets:
        if cancelled is not None and cancelled():
            raise SendCancelled("Stopped before the file was sent.")

        def scaled(pct: int, start: int = done, size: int = path.stat().st_size) -> None:
            if on_progress is not None and total:
                on_progress(min(100, (start + size * pct // 100) * 100 // total))

        send(fs, path, Plan(there, replace=decided.replace),
             scaled if on_progress is not None else None, cancelled)
        done += path.stat().st_size
        sent_paths.append(there)
    return sent_paths


def _gb(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    return f"{size / 1024 ** 2:.0f} MB"


# ------------------------------------------------- reuse a converted copy


def _marker(staged: Path) -> Path:
    return staged.with_name(staged.name + ".aynthor.json")


def fingerprint(source: Path, member: str, fmt: str, options: dict) -> dict:
    """What a staged file was made from. If any of it changes the file is
    made again."""
    stat = source.stat()
    wanted = {k: v for k, v in options.items()
              if k not in ("on_conflict", "delete_source", "keys_path")}
    return {
        "source": str(source),
        "member": member,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "format": fmt,
        "options": json.loads(json.dumps(wanted, default=str, sort_keys=True)),
    }


def can_reuse(staged: Path, made_from: dict) -> bool:
    try:
        stored = json.loads(_marker(staged).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not staged.is_file() or staged.stat().st_size != stored.get("output_size"):
        return False
    stored.pop("output_size", None)
    return stored == made_from


def remember(staged: Path, made_from: dict) -> None:
    record = dict(made_from, output_size=staged.stat().st_size)
    _marker(staged).write_text(json.dumps(record, sort_keys=True), encoding="utf-8")


def clear(staged: Path) -> None:
    """Remove a staged file, the tracks it lists if it is a cue sheet, its
    record, and any folders that leaves empty."""
    for path in (*tracks(staged), _marker(staged), staged):
        with suppress(OSError):
            path.unlink(missing_ok=True)
    folder = staged.parent
    for _ in range(3):
        try:
            folder.rmdir()
        except OSError:
            break
        folder = folder.parent
