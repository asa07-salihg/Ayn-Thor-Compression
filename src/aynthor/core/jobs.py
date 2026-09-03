"""Turn queue rows into the list of jobs the runner will execute.

Why
    A row is not a job. Between the two sits every rule that decides whether
    the work should happen at all: the conflict policy can drop a row whose
    output already exists, and the row's own options have to be layered on top
    of the format's defaults. Keeping that in a plain function means it can be
    tested without a window.

Used by
    `ui.main_window` when Start is pressed.

Reference
    Why jobs then run one at a time rather than in parallel:
    `ui.job_runner`, which walks the jobs this builds.
"""

from __future__ import annotations

from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionJob, QueueItem
from aynthor.core.settings import FormatSettings


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


def resolve_output_path(output: Path, on_conflict: str) -> Path | None:
    """Apply the conflict policy. None means "do not run this job"."""
    if not output.exists():
        return output
    if on_conflict == "skip":
        return None
    if on_conflict == "rename":
        candidate = output
        counter = 1
        while candidate.exists():
            candidate = output.with_name(f"{output.stem}_{counter}{output.suffix}")
            counter += 1
        return candidate
    return output  # overwrite


def build_jobs(
    queue: list[tuple[int, QueueItem]],
    settings: FormatSettings,
) -> list[tuple[int, ConversionJob]]:
    """Rows in, jobs out. The int is the table row, so progress can find it again."""
    jobs: list[tuple[int, ConversionJob]] = []

    for row, item in queue:
        if item.format is None:
            continue

        output = resolve_output_path(item.output, settings.on_conflict)
        if output is None:
            continue

        try:
            input_size = item.path.stat().st_size
        except OSError:
            input_size = 0

        jobs.append((
            row,
            ConversionJob(
                input_path=item.path,
                output_path=output,
                format=item.format,
                options=job_options(settings, item),
                input_size=input_size,
            ),
        ))
    return jobs
