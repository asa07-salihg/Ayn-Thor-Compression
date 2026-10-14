"""Turn queue rows into the list of jobs the runner will execute.

A row is not a job. Between the two sits every rule that decides whether
the work should happen at all: the conflict policy can drop a row whose
output already exists, and the row's own options have to be layered on top
of the format's defaults. Keeping that in a plain function means it can be
tested without a window.

Why jobs then run one at a time rather than in parallel:
`ui.job_runner`, which walks the jobs this builds.
"""

from __future__ import annotations

from pathlib import Path

from aynthor.core.device.deliver import remote_for
from aynthor.core.models import CompressionFormat, ConversionJob, QueueItem
from aynthor.core.output import device_staging
from aynthor.core.settings import FormatSettings


def _absolute(path: Path) -> Path:
    """Every path a converter is given, as an absolute one.

    Why
        The converters take their files as positional arguments and none of
        them supports `--` to end the options. A relative path is therefore one
        rename away from being read as a flag: a ROM called `-o` or
        `--recursive` would reach chdman's command line meaning something this
        app never intended, and such a name is trivial to create and does turn
        up in downloaded sets.

        An absolute path cannot be mistaken for one. On Windows it starts with
        a drive letter, on anything else with a separator, and both are the one
        thing an option can never begin with. Doing it here rather than in each
        converter means it holds for every tool, including the next one added.

    Reference
        https://cwe.mitre.org/data/definitions/88.html
    """
    return path if path.is_absolute() else path.resolve()


def job_options(settings: FormatSettings, item: QueueItem) -> dict:
    """The flags one row's converter will be given.

    Layered, most general first: the format's defaults, then the settings that
    apply to every format, then anything specific to this row. A row's own
    options win because they came from a platform preset or an imported list,
    both of which know more than a format-wide default does.
    """
    options = settings.for_format(item.format)
    options["mode"] = item.mode.value
    options["on_conflict"] = settings.on_conflict
    options["delete_source"] = settings.delete_source

    if item.tool_options:
        options.update(item.tool_options)

    # The keys path is app-wide, but a path set in the NSZ panel is more
    # specific, so it is never overwritten here.
    if (item.format == CompressionFormat.NSZ
            and settings.keys_path
            and not options.get("keys_path")):
        options["keys_path"] = settings.keys_path

    return options


# What the conflict setting is allowed to be. Anything else falls back to the
# safe one: the policy is read from the registry, and an unknown value used to
# reach the final `return output` and silently mean overwrite -- the one
# outcome that destroys a file.
CONFLICT_POLICIES = ("skip", "rename", "overwrite")


def conflict_policy(value: str) -> str:
    """The stored setting, or `skip` when it is not one this app wrote."""
    return value if value in CONFLICT_POLICIES else "skip"


def resolve_output_path(
    output: Path, on_conflict: str, taken: set[Path] | None = None,
) -> Path | None:
    """Apply the conflict policy. None means "do not run this job".

    `taken` is the set of outputs earlier rows in this same batch have already
    claimed. Without it the policy only ever looked at the disk, and at build
    time none of the batch has run yet, so two rows heading for one path both
    passed: a zip laid out as `Disc 1/Game.iso` and `Disc 2/Game.iso` produced
    two jobs writing `Game.chd`, both reported success, and one game was left
    on the card. A user who picked "rename" picked it for exactly that.
    """
    claimed = taken if taken is not None else set()

    def busy(candidate: Path) -> bool:
        return candidate.exists() or candidate in claimed

    if not busy(output):
        return output
    if on_conflict == "skip":
        return None
    if on_conflict == "rename":
        candidate = output
        counter = 1
        while busy(candidate):
            candidate = output.with_name(f"{output.stem}_{counter}{output.suffix}")
            counter += 1
        return candidate
    # Overwrite. Overwriting a file that was there before this batch is what
    # the user asked for; overwriting what another row in the same batch is
    # about to write is losing a game, so that one is stepped aside anyway.
    if output not in claimed:
        return output
    candidate = output
    counter = 1
    while busy(candidate):
        candidate = output.with_name(f"{output.stem}_{counter}{output.suffix}")
        counter += 1
    return candidate


def build_jobs(
    queue: list[tuple[int, QueueItem]],
    settings: FormatSettings,
) -> list[tuple[int, ConversionJob]]:
    """Rows in, jobs out. The int is the row id, so progress can find it again.

    Nothing is skipped here. Whether the output is already there is decided by
    the runner as each job starts, because by then the jobs before it have
    written their files, and a device can only be asked once it is open.
    """
    jobs: list[tuple[int, ConversionJob]] = []
    staging = device_staging(settings)

    for row, item in queue:
        if item.format is None:
            continue

        input_size = item.source_bytes if item.source_bytes > 0 else 0
        if input_size <= 0:
            try:
                input_size = item.path.stat().st_size
            except OSError:
                input_size = 0

        output = _absolute(item.output)
        remote = remote_for(output, _absolute(staging)) if staging is not None else None
        jobs.append((
            row,
            ConversionJob(
                input_path=_absolute(item.path),
                output_path=output,
                format=item.format,
                options=job_options(settings, item),
                member=item.member,
                remote=remote.as_posix() if remote is not None else "",
                input_size=input_size,
            ),
        ))
    return jobs
