"""Look inside a ZIP, 7z or RAR, and open it for the length of one conversion.

Why
    A lot of disc images arrive zipped. Adding `Game.zip` that holds `Game.iso`
    used to queue "compress to 7z", which would have put an ISO inside a zip
    inside a 7z: three containers, and an emulator reads none of them. What the
    user meant was "here is the ISO, do to it what you do to ISOs". So the
    archive is listed when it is added, the ROM inside decides the platform and
    the format, and at run time the archive is unpacked into a scratch folder,
    the converter is handed the extracted file, and the scratch folder is
    removed afterwards.

    `.zip` is read with the standard library, which costs a central-directory
    read and nothing else, so every zip that is added can be peeked. `.7z` and
    `.rar` need 7-Zip. The extras `7za` the app installs can list a 7z but not
    a RAR, so RAR listing uses the full `7z.exe` (tools/ or a 7-Zip install).
    A `.7z` is only peeked when the folder already says the platform does not
    want a 7z (`psx/Game.7z`, not `snes/Game.7z`). Arcade romsets stay
    romsets and are never peeked, except RAR, which is never a romset format.

Used by
    `core.intake` (whether to look inside, what is inside) and `ui.job_runner`
    (unpacking, when the row runs).

Reference
    7-Zip `l -slt` output, one `Key = Value` block per entry:
    https://documentation.help/7-Zip/list.htm
    Why member names are checked before extraction:
    https://cwe.mitre.org/data/definitions/22.html
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from aynthor.core.converters.base import parse_progress
from aynthor.core.formats import known_extensions
from aynthor.core.system import run_tool, tool_path

ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar"})

# Romsets. A zip in one of these folders is the game, not a wrapper around one.
_ARCADE_PLATFORMS = frozenset({"fbneo", "mame", "arcade"})

# Track data is never queued on its own: MAME romsets are full of `.bin`
# files, and treating one as a PlayStation dump would have turned every arcade
# zip into a CHD row. When a cue sheet or GDI is present it is the sheet that
# gets the row, and chdman finds the tracks from it.
_NEEDS_SHEET = frozenset({".bin", ".img"})

# A dump that ships both a cue/GDI and an ISO of the same disc. The sheet
# is the one chdman should read; converting the ISO as well would write the
# same game twice.
_SHEET_EXTS = frozenset({".cue", ".gdi"})
_REDUNDANT_WITH_SHEET = frozenset({".iso"})

# Left in place after extraction, so 7-Zip's own traversal protection can be
# checked rather than trusted. Same rule the tool installer applies.
_UNSAFE_PARTS = frozenset({"..", ""})

# Room to leave on the disk after unpacking. An extraction that fills the drive
# to the last byte leaves the converter nowhere to write its output.
_HEADROOM = 256 * 1024 * 1024

# Strip noise so `Ys X_ Nordics….nsp` still matches `Ys X Nordics….nsp`.
_NAME_KEY = re.compile(r"[^a-z0-9]+")


class UnpackError(Exception):
    """The archive cannot be opened, or must not be."""


@dataclass(frozen=True)
class Member:
    name: str   # POSIX path inside the archive
    size: int   # unpacked, as the archive declares it


def is_archive(path: Path) -> bool:
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def should_peek(path: Path, platform: str = "") -> bool:
    """Whether to look inside this archive for a ROM to convert.

    Arcade romsets stay romsets. A `.zip` anywhere else is cheap to list, so
    it is always opened: that is how `Game.zip` holding `Game.iso` becomes a
    CHD row instead of a 7z of a zip of an ISO. A `.rar` is never a destination
    format, so it is always opened. A `.7z` needs 7za, so it is only listed
    when the folder already says the platform does not want a 7z
    (`psx/Game.7z`, not `snes/Game.7z` and not a download with no platform).
    """
    if not is_archive(path):
        return False
    ext = path.suffix.lower()
    if ext == ".rar":
        return True
    from aynthor.core.esde import platform_from_path
    from aynthor.core.models import CompressionFormat
    from aynthor.core.presets import PRESETS

    platform = platform or platform_from_path(path)
    if platform in _ARCADE_PLATFORMS:
        return False
    if ext == ".zip":
        return True
    if ext == ".7z":
        if not platform:
            return False
        preset = PRESETS.get(platform)
        return preset is not None and preset.format != CompressionFormat.SEVEN_ZIP
    return False


def list_members(archive: Path) -> list[Member] | None:
    """What the archive holds, or None when it cannot be read.

    None rather than an exception because the caller is deciding how to queue
    a file the user just dropped, and "treat it as the archive it is" is the
    right answer to a zip the library cannot open or a 7z with no 7za
    installed.
    """
    ext = archive.suffix.lower()
    try:
        if ext == ".zip":
            return _list_zip(archive)
        if ext == ".7z":
            return _list_7z(archive)
        if ext == ".rar":
            return _list_7z(archive, tool=_rar_tool())
    except (OSError, zipfile.BadZipFile, UnpackError):
        return None
    return None


def rom_members(members: list[Member]) -> list[str]:
    """The files inside worth queueing, one row each.

    Any file with an extension the app converts, with two exclusions. A `.bin`
    or `.img` counts only when a cue sheet or GDI is present, and then it is
    the sheet that is queued: chdman reads the sheet and finds the tracks
    itself. A nested archive is skipped; one level of unpacking is the feature,
    two is a puzzle.

    A zip that holds four disc images therefore becomes four rows. When the
    same disc is present both as a cue sheet and as an ISO, only the sheet
    is kept, so the user does not convert the game twice.
    """
    exts = (known_extensions() - ARCHIVE_EXTENSIONS) - _NEEDS_SHEET
    files = [
        PurePosixPath(m.name.replace("\\", "/"))
        for m in members
        if not m.name.endswith("/")
    ]
    sheets = {
        (path.parent, path.stem.lower())
        for path in files
        if path.suffix.lower() in _SHEET_EXTS
    }
    chosen: list[str] = []
    for path in files:
        ext = path.suffix.lower()
        if ext not in exts:
            continue
        if ext in _REDUNDANT_WITH_SHEET and (path.parent, path.stem.lower()) in sheets:
            continue
        chosen.append(path.as_posix())
    return sorted(chosen)


class ArchiveScratch:
    """One extraction of an archive, shared by every member that will run.

    A zip of four discs used to be unpacked four times, once per row. The
    runner keeps this until the last member of that archive has finished,
    then deletes the scratch folder.
    """

    def __init__(
        self,
        archive: Path,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        self.archive = archive
        self.root = _scratch_dir(archive)
        self._listed: list[Member] = []
        try:
            self._listed = extract_all(archive, self.root, on_progress)
        except BaseException:
            shutil.rmtree(self.root, ignore_errors=True)
            raise

    def path_for(self, member: str) -> Path:
        """The extracted file for `member`.

        7-Zip listing and the folder Windows actually creates can disagree
        (code page, stripped characters). Exact path first, then unique
        basename, then a fuzzy name key, then size from the listing.
        """
        found = _resolve_extracted(self.root, member, self._listed)
        if found is not None:
            return found
        sample = ", ".join(
            sorted(
                p.relative_to(self.root).as_posix()
                for p in self.root.rglob("*") if p.is_file()
            )[:5]
        ) or "nothing"
        raise UnpackError(
            f"{member} was not in {self.archive.name} after unpacking "
            f"(found: {sample})."
        )

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


@contextmanager
def unpacked(
    archive: Path,
    member: str,
    on_progress: Callable[[int], None] | None = None,
) -> Iterator[Path]:
    """Extract the archive and yield the member's path, cleaning up afterwards.

    The whole archive is extracted, not the one member, because a cue sheet is
    useless without the tracks beside it and the converter is the only thing
    that knows which files it will read.

    The scratch folder goes beside the archive, on the same drive: a 4 GB ISO
    unpacked into `%TEMP%` on a small C: fills it. When that folder is not
    writable (a read-only card) the system temp folder is used instead.
    """
    scratch = ArchiveScratch(archive, on_progress)
    try:
        yield scratch.path_for(member)
    finally:
        scratch.close()


def extract_all(
    archive: Path,
    into: Path,
    on_progress: Callable[[int], None] | None = None,
) -> list[Member]:
    """Unpack everything into `into`, refusing anything that would escape it
    or would not fit on the disk. Returns the listed members."""
    members = list_members(archive)
    if members is None:
        raise UnpackError(f"Cannot read {archive.name}.")
    for member in members:
        _check_member_name(member.name)
    declared = sum(m.size for m in members)
    free = shutil.disk_usage(into).free
    if declared + _HEADROOM > free:
        raise UnpackError(
            f"{archive.name} unpacks to {declared / 1e9:.1f} GB and only "
            f"{free / 1e9:.1f} GB is free next to it.")

    if archive.suffix.lower() == ".zip":
        _extract_zip(archive, into, declared, on_progress)
    elif archive.suffix.lower() == ".rar":
        _extract_7z(archive, into, on_progress, tool=_rar_tool())
    else:
        _extract_7z(archive, into, on_progress)

    written = [p for p in into.rglob("*") if p.is_file()]
    if not written:
        raise UnpackError(f"{archive.name} unpacked to an empty folder.")
    for extracted in written:
        if not extracted.resolve().is_relative_to(into.resolve()):
            raise UnpackError(f"{archive.name} wrote outside its scratch folder.")
    return members


def extract_member_to(
    archive: Path,
    member: str,
    destination: Path,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Extract one member straight to `destination` — no sibling unpack folder.

    Move used to unpack the whole RAR into `.aynthor-unpack-*` next to the
    card, then copy the NSP into the game folder. That doubled both time and
    free space for a 14 GB title. A Move only needs the one file, written once.
    """
    _check_member_name(member)
    listed = list_members(archive)
    if listed is None:
        raise UnpackError(f"Cannot read {archive.name}.")
    wanted = member.replace("\\", "/")
    meta = next(
        (m for m in listed if m.name.replace("\\", "/") == wanted
         or Path(m.name).name == Path(wanted).name),
        None,
    )
    size = meta.size if meta is not None else 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(destination.parent).free
    if size and size + _HEADROOM > free:
        raise UnpackError(
            f"{Path(member).name} needs {size / 1e9:.1f} GB and only "
            f"{free / 1e9:.1f} GB is free next to it.")

    # Stage beside the destination so the final step is a same-volume rename,
    # then delete the empty staging dir. Peak disk use is one copy of the file.
    staging = Path(tempfile.mkdtemp(prefix=".aynthor-member-", dir=destination.parent))
    try:
        if archive.suffix.lower() == ".zip":
            _extract_zip_member(archive, wanted, staging, size, on_progress)
        elif archive.suffix.lower() == ".rar":
            _extract_7z_member(
                archive, wanted, staging, on_progress, tool=_rar_tool())
        else:
            _extract_7z_member(archive, wanted, staging, on_progress)
        found = _resolve_extracted(staging, wanted, listed)
        if found is None or not found.is_file():
            raise UnpackError(
                f"{member} was not in {archive.name} after unpacking.")
        if destination.exists():
            destination.unlink()
        os.replace(found, destination)
        if on_progress:
            on_progress(100)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


_TITLE_ID_IN_NAME = re.compile(r"\[([0-9A-Fa-f]{16})\]")


def _safe_7z_mask(member: str) -> str | None:
    """A 7-Zip include mask that will not be eaten by `[]` wildcards.

    Switch dumps are named `Game [0100BAC01E57E800][v0].nsp`. Passing that
    path to `7z x` matches zero files because `[0100…]` is a character class.
    A unique title-id fragment with `*` is safe and still selects one file.
    """
    name = Path(member.replace("\\", "/")).name
    match = _TITLE_ID_IN_NAME.search(name)
    if match:
        return f"*{match.group(1)}*"
    if "[" not in name and "]" not in name:
        return name
    return None


def _extract_7z_member(
    archive: Path,
    member: str,
    into: Path,
    on_progress: Callable[[int], None] | None,
    tool: Path | None = None,
) -> None:
    """Extract one member via 7-Zip without the `[]` wildcard trap."""
    mask = _safe_7z_mask(member)
    if mask:
        _extract_7z(
            archive, into, on_progress, tool=tool, member=mask, recursive=True)
        if any(path.is_file() for path in into.rglob("*")):
            return
    # Fall back: unpack the whole archive into staging, then resolve.
    _extract_7z(archive, into, on_progress, tool=tool)


def _extract_zip_member(
    archive: Path,
    member: str,
    into: Path,
    size: int,
    on_progress: Callable[[int], None] | None,
) -> None:
    with zipfile.ZipFile(archive) as opened:
        info = None
        for entry in opened.infolist():
            name = entry.filename.replace("\\", "/")
            if name == member or Path(name).name == Path(member).name:
                info = entry
                break
        if info is None:
            raise UnpackError(f"{member} is not in {archive.name}.")
        opened.extract(info, into)
    if on_progress:
        on_progress(100 if size else 99)


def _name_key(name: str) -> str:
    return _NAME_KEY.sub("", Path(name).stem.casefold())


def _resolve_extracted(
    root: Path, member: str, listed: list[Member],
) -> Path | None:
    normalised = member.replace("\\", "/")
    exact = root / Path(*PurePosixPath(normalised).parts)
    if exact.is_file():
        return exact

    wanted = PurePosixPath(normalised)
    files = [path for path in root.rglob("*") if path.is_file()]
    by_name = [path for path in files if path.name == wanted.name]
    if len(by_name) == 1:
        return by_name[0]

    key = _name_key(wanted.name)
    suffix = wanted.suffix.casefold()
    by_key = [
        path for path in files
        if path.suffix.casefold() == suffix and _name_key(path.name) == key
    ]
    if len(by_key) == 1:
        return by_key[0]

    expected = next(
        (m.size for m in listed
         if m.name.replace("\\", "/") == normalised
         or Path(m.name).name == wanted.name),
        None,
    )
    if expected:
        by_size = [
            path for path in files
            if path.suffix.casefold() == suffix and path.stat().st_size == expected
        ]
        if len(by_size) == 1:
            return by_size[0]

    if len(by_name) > 1 and len(wanted.parts) > 1:
        tail = wanted.as_posix()
        scored = [
            path for path in by_name
            if path.relative_to(root).as_posix().endswith(tail)
        ]
        if len(scored) == 1:
            return scored[0]
    return None


# ------------------------------------------------------------------------ zip

def _list_zip(archive: Path) -> list[Member]:
    with zipfile.ZipFile(archive) as opened:
        return [Member(info.filename, info.file_size)
                for info in opened.infolist() if not info.is_dir()]


def _extract_zip(archive: Path, into: Path, total: int,
                 on_progress: Callable[[int], None] | None) -> None:
    done = 0
    last = -1
    with zipfile.ZipFile(archive) as opened:
        for info in opened.infolist():
            if info.is_dir():
                continue
            opened.extract(info, into)
            done += info.file_size
            if on_progress and total:
                pct = min(99, int(done * 100 / total))
                if pct != last:
                    last = pct
                    on_progress(pct)


# ------------------------------------------------------------------------- 7z

def _list_7z(archive: Path, tool: Path | None = None) -> list[Member]:
    seven = tool if tool is not None else tool_path("7za")
    if not seven.is_file():
        raise UnpackError("7za is not installed.")
    result = run_tool(seven, ["l", "-slt", "-ba", "-scsUTF-8", str(archive)])
    if result.returncode > 1:
        raise UnpackError((result.stderr or result.stdout or "7za failed").strip())
    return _parse_7z_listing(result.stdout)


def _parse_7z_listing(text: str) -> list[Member]:
    """`l -slt` prints one blank-line-separated block per entry, each a set of
    `Key = Value` lines. Folders carry `D` in their attributes."""
    members: list[Member] = []
    block: dict[str, str] = {}

    def flush() -> None:
        name = block.get("Path")
        # Windows attributes come first (`A`, `RA`, `D`), followed on archives
        # made elsewhere by a space and the POSIX mode (`D_ drwxr-xr-x`).
        attributes = block.get("Attributes", "").split(" ")[0]
        if name and "D" not in attributes:
            try:
                size = int(block.get("Size", "0") or 0)
            except ValueError:
                size = 0
            members.append(Member(name.replace("\\", "/"), size))
        block.clear()

    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            block[key.strip()] = value.strip()
    flush()
    return members


def _extract_7z(
    archive: Path,
    into: Path,
    on_progress: Callable[[int], None] | None,
    tool: Path | None = None,
    member: str | None = None,
    *,
    recursive: bool = False,
) -> None:
    seven = tool if tool is not None else tool_path("7za")
    if not seven.is_file():
        raise UnpackError("7za is not installed. Install it from Tools.")

    def emit(line: str) -> None:
        if on_progress is not None and (pct := parse_progress(line)) is not None:
            on_progress(min(99, pct))

    args = ["x", str(archive), f"-o{into}", "-y", "-bsp1", "-scsUTF-8"]
    if recursive:
        args.append("-r")
    if member:
        args.append(member)
    # Exit code 1 is "warning" (e.g. locked file skipped); 2+ is fatal.
    result = run_tool(seven, args, on_output=emit)
    if result.returncode > 1:
        raise UnpackError((result.stderr or result.stdout or "7za failed").strip())


def _rar_tool() -> Path:
    """7za cannot open RAR. The full 7z.exe can, from tools/ or a 7-Zip install."""
    bundled = tool_path("7z")
    if bundled.is_file():
        return bundled
    for folder in (
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    ):
        candidate = Path(folder) / "7-Zip" / "7z.exe"
        if candidate.is_file():
            return candidate
    raise UnpackError(
        "RAR needs full 7-Zip (7z.exe). 7za cannot open RAR. "
        "Install 7-Zip from 7-zip.org, or copy 7z.exe and 7z.dll into tools/."
    )


# -------------------------------------------------------------------- helpers

def _check_member_name(name: str) -> None:
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
        raise UnpackError(f"Archive entry is an absolute path: {name}")
    if any(part in _UNSAFE_PARTS for part in PurePosixPath(normalised).parts):
        raise UnpackError(f"Archive entry escapes the folder: {name}")


def _scratch_dir(archive: Path) -> Path:
    for parent in (archive.parent, None):
        try:
            return Path(tempfile.mkdtemp(prefix=".aynthor-unpack-", dir=parent))
        except OSError:
            continue
    raise UnpackError("No writable folder to unpack into.")
