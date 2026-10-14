"""Where a converted file is written.

Three separate rules decide this and they have an order: an ES-DE ROMs
folder wins for a row that knows its platform, then a plain output folder,
then the input's own folder. Keeping them here rather than in the queue
widget is the same rule the rest of `core` follows, and it is why they can
be tested without Qt or a display server -- which is exactly what caught
them being in the wrong module.

On top of those sits the game folder layout, which is how the card this app
was written for is actually organised:

    ROMs/psx/Final Fantasy VIII.chd/Final Fantasy VIII.chd
    ROMs/psx/Final Fantasy VIII.chd/Final Fantasy VIII (Disc 2).chd
    ROMs/switch/Mario Kart 8 Deluxe.nsp/Mario Kart 8 Deluxe.nsp
    ROMs/switch/Mario Kart 8 Deluxe.nsp/sxs-mk8u_v1376256.nsp

A folder named exactly like its primary file, extension included. ES-DE
calls this "directories interpreted as files": the folder shows as one
game, and launching it runs the file inside whose name matches the folder.
Extra discs, updates and DLC sit beside that file under their own names.

Output naming per format: `core.formats.suggest_output_path`.
ES-DE folder names: `core.esde`.
ES-DE user guide, "Directories interpreted as files":
https://gitlab.com/es-de/emulationstation-de/-/blob/master/USERGUIDE.md
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

from aynthor.core import esde
from aynthor.core.device.deliver import staging_root
from aynthor.core.esde import ESDE_PLATFORM_FOLDERS
from aynthor.core.formats import known_extensions, suggest_output_path
from aynthor.core.models import CompressionFormat, ConversionMode
from aynthor.core.settings import FormatSettings

# `(Disc 2)`, `(Disk 1)`, `(CD 3)`, `[Disc 2]`, `(Side A)`, `(Disc 1 of 3)`.
# Anchored to a bracket so a title that merely contains the word survives.
_DISC_TAG = re.compile(
    r"\s*[\(\[](?:disc|disk|cd|side)\s*([0-9]+|[a-z])\b[^\)\]]*[\)\]]", re.IGNORECASE)

# A folder named like one of these is a game, not a system folder. `.m3u` is
# the ES-DE multi-disc playlist and is never a conversion input, so it is not
# in the catalogue and has to be listed here.
_GAME_FOLDER_EXTRAS = frozenset({".m3u"})

# `Disc 2/`, `CD 1/`: a multi-disc dump where the disc is the folder and every
# disc image inside has the same file name.
_DISC_FOLDER = re.compile(r"^\s*(?:disc|disk|cd)\s*([0-9]+|[a-z])\s*$", re.IGNORECASE)

# Path separators, the drive colon, and the rest of what Windows refuses in a
# file name. Any of them means the text was never a single folder name.
_FORBIDDEN_IN_NAME = frozenset('/\\:*?"<>|') | {chr(c) for c in range(32)}

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
    member: str = "",
) -> Path:
    """Where a row's result will be written, after the card layout, the output
    folder and the game folder rules are applied.

    An ES-DE card wins over a plain output folder when the row knows which
    platform it is, because that is the whole point of naming the card: the
    file should land in the folder the emulator reads, not in one pile the user
    then has to sort.

    `member` is the ROM inside `path` when `path` is an archive. The output is
    named after the ROM, because that is what the file is; the archive's name
    is whatever the download was called.
    """
    if fmt is None:
        return path
    source = path.parent / member_name(member) if member else path
    suggested = suggest_output_path(source, fmt, mode, options)

    base = _destination(settings, platform, path)
    options = options or {}
    forced = str(options.get("game_folder", ""))
    if (forced or settings.game_folders) and _wants_game_folder(fmt, mode):
        if forced:
            # A folder already on the card keeps its exact name (often `.nsp`
            # while the new file becomes `.nsz`); realigning would orphan it.
            # Update/DLC extras must also keep the base folder's extension:
            # Base.xci/Base.xci owns same-game .nsp updates, not a new Base.nsp/.
            content = str(options.get("content_type", "")).lower()
            keep_name = bool(options.get("disk_anchor")) or content in (
                "update", "dlc")
            folder = forced if keep_name else aligned_folder(forced, suggested.name)
            name = file_name_in_folder(folder, suggested.name, options)
            return (base or system_folder_of(source)) / folder / name
        folder, name = game_folder_layout(suggested.name, options)
        return (base or system_folder_of(source)) / folder / name
    if base:
        return base / suggested.name
    return suggested


def member_name(member: str) -> str:
    """The file name an archive member's output is built from.

    Normally the member's own name. A multi-disc dump is often laid out as
    `Disc 1/Game.iso`, `Disc 2/Game.iso`, though: the disc is the folder and
    both files are called the same thing. Naming both outputs after the file
    alone gave one game two rows heading for one path, so the folder's disc
    number is folded into the name and the discs stay apart.
    """
    parts = PurePosixPath(member.replace("\\", "/")).parts
    if not parts:
        return member
    name = parts[-1]
    if len(parts) < 2 or _DISC_TAG.search(Path(name).stem):
        return name
    found = _DISC_FOLDER.match(parts[-2])
    if not found:
        return name
    leaf = Path(name)
    return f"{leaf.stem} (Disc {found.group(1)}){leaf.suffix}"


def aligned_folder(folder: str, output_name: str) -> str:
    """The game folder named for the file that will actually be written.

    An empty `Game.nsp/` on disk is still that folder, but compressing to NSZ
    must produce `Game.nsz/Game.nsz`: ES-DE launches the file whose name
    matches the folder, and a `.nsz` sitting in a `.nsp` folder is invisible
    to it.
    """
    stem = Path(folder).stem
    suffix = Path(output_name).suffix or Path(folder).suffix
    group = safe_folder_name(stem) or stem
    return f"{group}{suffix}"


def file_name_in_folder(
    folder: str, output_name: str, options: dict | None = None,
) -> str:
    """The file that lands in `folder`. The primary ROM takes the folder's
    own name, exactly; extras keep theirs.

    ES-DE treats a folder named `Game.chd` as the game, and launches the file
    inside that is also called `Game.chd`. An update, DLC or disc 2 sitting
    beside it keeps the name it arrived with.
    """
    if _keeps_own_name(output_name, options):
        return output_name
    return folder


def _is_first_disc(disc: str) -> bool:
    """Whether this disc token means "the one the folder is named after".

    `01` is disc one. Comparing the token as text made it disc *something
    else*, so a redump-style `Final Fantasy VII (Disc 01/02/03)` set produced
    a folder with no file matching its own name, which ES-DE hands to the
    emulator as a directory, and nothing launches.
    """
    if disc in ("", "a"):
        return True
    return disc.isdigit() and int(disc) == 1


def _keeps_own_name(output_name: str, options: dict | None) -> bool:
    options = options or {}
    if options.get("keep_name"):
        # Joining a game folder that already has its primary file. Without
        # this the new file was given the folder's own name, which is the
        # path of the ROM already sitting there: with the conflict policy on
        # overwrite the extra was copied straight over the base game, and
        # with the default Skip the row was dropped and Start said there was
        # nothing to do.
        return True
    content = str(options.get("content_type", "")).lower()
    if content in ("update", "dlc"):
        return True
    tag = _DISC_TAG.search(Path(output_name).stem)
    disc = tag.group(1).lower() if tag else ""
    return not _is_first_disc(disc)


def _wants_game_folder(fmt: CompressionFormat, mode: ConversionMode) -> bool:
    # Unzipping an archive already produces a folder, and one more level
    # around it would only be a folder ES-DE cannot launch.
    return not (fmt == CompressionFormat.SEVEN_ZIP and mode == ConversionMode.DECOMPRESS)


def strip_disc_tag(name: str) -> str:
    """The title with `(Disc 2)` and friends removed. Empty when nothing is left.

    Only a recognised ROM extension is dropped. `Path.stem` cuts at the last
    dot, which is right for `Game.chd` and wrong for a title: "New Super Mario
    Bros. U Deluxe" came back as "New Super Mario Bros", so an update never
    matched the game folder of that name already on the card and was written
    into a second folder of its own.
    """
    text = Path(name)
    stem = text.stem if text.suffix.lower() in _game_folder_suffixes() else name
    return _DISC_TAG.sub("", stem).strip()


def game_folder_layout(output_name: str, options: dict | None = None) -> tuple[str, str]:
    """`(folder, file)` for one output under the game folder layout.

    The folder is the game's name plus the output extension. The file keeps
    its own name unless it is the primary file, which takes the folder's name
    so ES-DE has something to launch: a folder called `Game.chd` with only
    `Game (Disc 1).chd` inside is passed to the emulator as a directory.

    The game's name is the row's `game_group` when there is one (a Switch set,
    or a title from an imported list), otherwise the stem with its disc tag
    removed. Primary means: not a disc at all, disc 1, or a Switch base game.
    Discs 2 and up, updates and DLC keep their names beside it.
    """
    options = options or {}
    output = Path(output_name)
    suffix = output.suffix
    tag = _DISC_TAG.search(output.stem)
    disc = tag.group(1).lower() if tag else ""

    group = safe_folder_name(options.get("game_group", ""))
    if not group:
        group = safe_folder_name(strip_disc_tag(output.name)) or safe_folder_name(output.stem)
    folder = f"{group}{suffix}"

    content = str(options.get("content_type", "")).lower()
    if content in ("update", "dlc"):
        return folder, output_name
    if _is_first_disc(disc):
        return folder, folder
    return folder, output_name


def disc_part(name: str) -> str:
    """'Disc 2' / 'Side A' from a filename, or empty."""
    tag = _DISC_TAG.search(Path(name).stem)
    if not tag:
        return ""
    token = tag.group(1)
    if token.isdigit():
        return f"Disc {token}"
    return f"Side {token.upper()}"


def is_game_folder(folder: Path) -> bool:
    """A folder named like a ROM (`Game.chd`, `Game.m3u`) is a game, not a
    system folder, so a result must not be nested inside it."""
    return folder.suffix.lower() in _game_folder_suffixes()


def system_folder_of(path: Path) -> Path:
    """The folder a result goes beside its input in: the input's parent, or
    the grandparent when the input already sits in its own game folder.
    Without this a re-run over a finished card produced
    `Game.chd/Game.cue/Game.cue`."""
    parent = path.parent
    return parent.parent if is_game_folder(parent) else parent


@lru_cache(maxsize=1)
def _game_folder_suffixes() -> frozenset[str]:
    return frozenset(known_extensions()) | _GAME_FOLDER_EXTRAS


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
    # Length first: trimming and then cutting can put a trailing space or dot
    # back on the end, and those are legal to create and impossible to open
    # on Windows. NTFS streams hide behind a colon, which is already replaced.
    cleaned = cleaned[:_MAX_NAME].rstrip(". ")
    if not cleaned or cleaned in {".", ".."} or set(cleaned) <= {"."}:
        return ""
    if cleaned.upper().split(".")[0] in _RESERVED_ON_WINDOWS:
        return f"_{cleaned}"
    return cleaned


_ROMS_ROOT: dict[str, Path] = {}


def _roms_root(configured: str) -> Path:
    """Cached: `resolve_roms_root` stats the disk to work out whether it was
    given the ROMs folder or the folder above it, and this is asked once per
    row. A two thousand file card did that two thousand times, and the answer
    cannot change while the queue is being filled."""
    cached = _ROMS_ROOT.get(configured)
    if cached is None:
        cached = esde.resolve_roms_root(Path(configured))
        _ROMS_ROOT[configured] = cached
    return cached


def forget_roms_root() -> None:
    """Drop the cache above, because between two fills the answer can change.

    It is only true for the length of one fill. Someone who points the app at
    a blank card and then copies an ES-DE tree onto it has changed the
    answer, and with the cache never cleared every output for the rest of the
    session went to `E:/psx` rather than `E:/ROMs/psx`. Called whenever
    settings are applied and before each batch of files is added.
    """
    _ROMS_ROOT.clear()


def platform_destination(
    settings: FormatSettings, platform: str, path: Path | None = None,
) -> Path | None:
    """Where game folders for this platform live on the card / output root."""
    return _destination(settings, platform, path or Path("."))


def device_staging(settings: FormatSettings) -> Path | None:
    """The folder on this PC that stands in for the device's ROMs folder, or
    None when games are not going to a device."""
    if settings.device is None:
        return None
    base = Path(settings.staging_dir) if settings.staging_dir else None
    return staging_root(settings.device, base)


def _destination(settings: FormatSettings, platform: str, path: Path) -> Path | None:
    """The folder a result goes in, or None to leave it beside its input."""
    staging = device_staging(settings)
    if staging is not None and platform:
        folders = ESDE_PLATFORM_FOLDERS.get(platform)
        if folders:
            return staging / folders[0]
    if settings.esde_root and platform and staging is None:
        folders = ESDE_PLATFORM_FOLDERS.get(platform)
        if folders:
            return _roms_root(settings.esde_root) / folders[0]
    if settings.output_dir:
        return Path(settings.output_dir)
    return None
