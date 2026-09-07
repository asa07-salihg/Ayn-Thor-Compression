"""Turn a dropped file into the queue rows the runner will see.

Why
    A row is not "this path". Adding `Game.zip` that holds `Game.iso` used to
    queue "compress to 7z", which nested an ISO inside a zip inside a 7z, and
    no emulator reads that. The archive has to be listed first, the ROM inside
    decides the platform and the format, and the row remembers which member to
    unpack at run time. Folder labels live here too, so adding `psx` shows
    `psx/Game.chd/Game.cue` rather than a bare filename.

    Keeping this out of the queue widget is what lets the tests below prove
    the zip-of-an-ISO case without a window.

Used by
    `ui.queue_view.add_paths`, `ui.main_window` (folder labels).

Reference
    Game folders and archive peeking:
    `docs/superpowers/specs/2026-09-07-game-folders-and-archive-unpack-design.md`
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from aynthor.core.formats import natural_mode, suggest_output_path
from aynthor.core.models import CompressionFormat, ConversionMode, QueueItem
from aynthor.core.output import output_for, safe_folder_name, strip_disc_tag
from aynthor.core.presets import PresetTable, detect_platform_format
from aynthor.core.settings import FormatSettings
from aynthor.core.switch import (
    detect_content_type,
    is_switch_rom,
    normalize_game_name,
    title_family,
)
from aynthor.core.unpack import is_archive, list_members, rom_members, should_peek


def folder_label(added: Path, file: Path) -> str:
    """What the File column shows for a file found by adding a folder.

    Relative to the parent of the folder that was added, so adding `psx`
    labels a row `psx/Final Fantasy VIII.chd/Final Fantasy VIII.chd` rather
    than hiding the folder the user just picked.
    """
    try:
        return file.relative_to(added.parent).as_posix()
    except ValueError:
        return file.name


def queue_items_for(
    path: Path,
    settings: FormatSettings,
    *,
    label: str = "",
    presets: PresetTable | None = None,
) -> tuple[list[QueueItem], str | None]:
    """Zero or more rows for one file, or a skip reason.

    An archive that holds ROMs becomes one row per ROM. Anything else is a
    single row, or a reason it should not be queued at all.
    """
    if should_peek(path):
        listed = list_members(path)
        if listed is not None:
            roms = rom_members(listed)
            sizes = {m.name: m.size for m in listed}
            items: list[QueueItem] = []
            last_reason: str | None = None
            for member in roms:
                item, reason = _one(
                    path, settings, label, member, presets,
                    source_bytes=sizes.get(member, 0))
                if item is not None:
                    items.append(item)
                else:
                    last_reason = reason
            if items:
                return _grouped_archive_items(path, items, settings), None
            if roms:
                return [], last_reason or f"{path.name}: no convertible ROM inside"
        if path.suffix.lower() == ".rar":
            return [], (
                f"{path.name}: cannot read this RAR. 7za cannot open RAR; "
                "install 7-Zip (7z.exe) from 7-zip.org."
            )
    return _as_list(_one(path, settings, label, "", presets))


def _grouped_archive_items(
    archive: Path, items: list[QueueItem], settings: FormatSettings,
) -> list[QueueItem]:
    """Members of one zip are one game: four discs in `Game.zip` become one
    folder named after the zip, not four unrelated rows.

    The archive's stem (disc tags stripped) is the game name. A Switch dump
    that already set `game_group` from the filename is left alone.
    """
    group = safe_folder_name(strip_disc_tag(archive.name)) or safe_folder_name(archive.stem)
    if not group:
        return items
    grouped: list[QueueItem] = []
    for item in items:
        if item.game_group:
            grouped.append(item)
            continue
        options = dict(item.tool_options or {})
        options["game_group"] = group
        item.tool_options = options
        item.game_group = group
        if item.format is not None:
            item.output = output_for(
                item.path, item.format, item.mode, settings, options,
                item.platform, item.member)
        grouped.append(item)
    return grouped


def _as_list(
    result: tuple[QueueItem | None, str | None],
) -> tuple[list[QueueItem], str | None]:
    item, reason = result
    if item is None:
        return [], reason
    return [item], None


def _one(
    path: Path,
    settings: FormatSettings,
    label: str,
    member: str,
    presets: PresetTable | None,
    *,
    source_bytes: int = 0,
) -> tuple[QueueItem | None, str | None]:
    source = path.parent.joinpath(*PurePosixPath(member).parts) if member else path
    detected = detect_platform_format(source, presets)
    shown = source.name if member else path.name
    if detected.skip:
        return None, f"{shown}: {detected.skip_reason}"
    fmt = detected.format
    if fmt is None:
        return None, f"{shown}: no format handles this file"

    options = _with_switch_metadata(source, fmt, dict(detected.tool_options))
    platform = detected.platform or ""
    mode = natural_mode(source, fmt)
    output = output_for(path, fmt, mode, settings, options, platform, member)

    if _should_place(source, fmt, options, settings, member):
        mode = ConversionMode.COMPRESS
        output = output_for(path, fmt, mode, settings, options, platform, member)

    if (not member and is_archive(path) and fmt is not CompressionFormat.SEVEN_ZIP):
        # Peek found nothing to convert. chdman cannot read a zip; skip rather
        # than queue a disc job whose input is still the archive.
        return None, f"{path.name}: no convertible ROM inside"

    if (mode is ConversionMode.COMPRESS and output == path
            and fmt is not CompressionFormat.NDS_TRIM and not member):
        return None, f"{path.name}: already a {path.suffix.lstrip('.')}"

    size = source_bytes
    if size <= 0 and not member:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

    return QueueItem(
        path=path,
        format=fmt,
        mode=mode,
        output=output,
        tool_options=options,
        platform=platform,
        game_group=options.get("game_group", ""),
        content_type=options.get("content_type", ""),
        member=member,
        source_bytes=size,
        label=label,
    ), None


def _should_place(
    source: Path,
    fmt: CompressionFormat,
    options: dict,
    settings: FormatSettings,
    member: str,
) -> bool:
    """The file is already the container this platform wants.

    With game folders on, a loose `Game.chd` still has to move into
    `Game.chd/Game.chd`. Without them, a `.chd` stays a request to open it.
    A ROM inside an archive is always placed or converted; it is not already
    sitting where the emulator will look.
    """
    if fmt is CompressionFormat.NDS_TRIM:
        return False
    suggested = suggest_output_path(source, fmt, ConversionMode.COMPRESS, options)
    if suggested.suffix.lower() != source.suffix.lower():
        return False
    return bool(settings.game_folders or member)


def _with_switch_metadata(path: Path, fmt: CompressionFormat, options: dict) -> dict:
    if fmt != CompressionFormat.NSZ and not is_switch_rom(path):
        return options
    options.setdefault("game_group", normalize_game_name(path))
    options.setdefault("content_type", detect_content_type(path).value)
    if family := title_family(path):
        options.setdefault("title_family", family)
    return options
