"""What every converter shares: the interface, progress parsing, small helpers.

Why
    Nine converters wrap nine command-line tools that agree on almost nothing.
    What they do agree on is the shape of the work -- validate, run, report --
    and the fact that each prints a percentage somewhere in its output. Pulling
    that into a base class is what keeps the queue's progress column working
    the same way for chdman, DolphinTool and 7-Zip alike.

Used by
    Every module in this package; `core.converters.registry` maps formats to
    the concrete classes.

Reference
    The individual tools' flags are documented in each converter, with a link to
    each project's own reference.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode

# Deliberately loose: chdman prints "Compressing, 42.3% complete", DolphinTool
# prints a bare "42%", 7-Zip prints "42% 12 - name". One number followed by a
# percent sign is the only thing all of them have in common.
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")


def parse_progress(line: str) -> int | None:
    """Pull a 0-100 percentage out of a tool's output line, if there is one."""
    match = _PERCENT.search(line)
    if not match:
        return None
    return max(0, min(100, int(float(match.group(1)))))


def is_decompress(job: ConversionJob) -> bool:
    return job.options.get("mode") == ConversionMode.DECOMPRESS.value


def place_file(
    job: ConversionJob,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[bool, str]:
    """Copy the input next to where the converter would have written it.

    Used when the file is already the container this platform wants and only
    the folder differs: `snes/Game.7z` becoming `snes/Game.7z/Game.7z`.
    Archiving it again would nest a 7z inside a 7z; compressing a CHD to CHD
    would just fail. With delete-source on, the runner turns this into a move.

    On Windows the folder cannot be created while a file of the same name
    still sits there (`Game.chd` file → `Game.chd/` directory). That case
    moves the file aside, creates the folder, then moves it in.

    `on_progress` is required for large Moves: unpacking a RAR ends at 99%,
    and a silent copy of a 14 GB NSP looks frozen until the copy finishes.
    """
    src = job.input_path
    dst = job.output_path
    try:
        if dst.resolve() == src.resolve():
            if on_progress:
                on_progress(100)
            return True, "Already in place."
    except OSError:
        pass

    parent = dst.parent
    try:
        if parent.exists() and parent.is_file():
            try:
                same = parent.resolve() == src.resolve()
            except OSError:
                same = parent == src
            if not same:
                return False, (
                    f"Could not create game folder: {parent.name} is already a file.")
            return _fold_into_own_name(src, dst, on_progress)
        parent.mkdir(parents=True, exist_ok=True)
        _copy_with_progress(src, dst, on_progress)
    except OSError as exc:
        return False, f"Could not copy into its folder: {exc}"
    return True, "Placed in its game folder."


def _fold_into_own_name(
    src: Path,
    dst: Path,
    on_progress: Callable[[int], None] | None = None,
) -> tuple[bool, str]:
    """`Game.chd` (file) → `Game.chd/Game.chd` on a filesystem that forbids
    creating a directory over an existing file of the same path."""
    aside = src.with_name(src.name + ".aynthor-placing")
    n = 0
    while aside.exists():
        n += 1
        aside = src.with_name(f"{src.name}.aynthor-placing-{n}")
    folder = dst.parent
    try:
        src.rename(aside)
        folder.mkdir(parents=True, exist_ok=False)
        aside.rename(dst)
    except OSError as exc:
        _rollback_fold(aside, src, folder)
        return False, f"Could not copy into its folder: {exc}"
    if on_progress:
        on_progress(100)
    return True, "Placed in its game folder."


_COPY_CHUNK = 8 * 1024 * 1024


def _copy_with_progress(
    src: Path,
    dst: Path,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    """Copy `src` to `dst`, reporting 0-100. Always copies; delete-source is
    the runner's job, so a same-volume rename here would surprise callers."""
    total = src.stat().st_size
    copied = 0
    last = -1
    with src.open("rb") as incoming, dst.open("wb") as outgoing:
        while True:
            chunk = incoming.read(_COPY_CHUNK)
            if not chunk:
                break
            outgoing.write(chunk)
            copied += len(chunk)
            if on_progress and total > 0:
                pct = min(99, int(copied * 100 / total))
                if pct != last:
                    last = pct
                    on_progress(pct)
    shutil.copystat(src, dst)
    if on_progress:
        on_progress(100)


def _rollback_fold(aside: Path, src: Path, folder: Path) -> None:
    try:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    except OSError:
        pass
    try:
        if aside.exists() and not src.exists():
            aside.rename(src)
    except OSError:
        pass


def failure(result: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    """Turn a non-zero exit into a message worth showing.

    The tool's own words come first. Ours are guesses; its are facts.
    """
    return False, (result.stderr or result.stdout or "Unknown error").strip()


@contextmanager
def size_progress(output: Path, expected_bytes: int, callback):
    """Report progress by watching the output file grow.

    Needed for tools that draw a progress bar only when attached to a terminal
    -- rom-converto is the one that matters here -- so nothing usable ever
    reaches us through the pipe. Comparing the output's size against the size
    the header says it will be is an accurate stand-in. Capped at 99 so the
    final 100 comes from the job actually finishing.
    """
    if not callback or expected_bytes <= 0:
        yield
        return

    stop = threading.Event()

    def poll() -> None:
        last = -1
        while not stop.wait(0.4):
            try:
                size = output.stat().st_size
            except OSError:
                continue
            pct = min(99, int(size * 100 / expected_bytes))
            if pct != last:
                last = pct
                callback(pct)

    worker = threading.Thread(target=poll, daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=1.0)


class BaseConverter(ABC):
    """One format's adapter around one or more external tools."""

    format: CompressionFormat
    on_progress: Callable[[int], None] | None = None

    @abstractmethod
    def convert(self, job: ConversionJob) -> tuple[bool, str]:
        """Do the work. Returns (succeeded, message shown to the user)."""

    def validate(self, job: ConversionJob) -> str | None:
        """Cheap pre-flight check. Returns an error message, or None to proceed."""
        if not job.input_path.is_file():
            return f"File not found: {job.input_path}"
        return None

    def emit(self, line: str) -> None:
        """Feed a tool output line to the progress callback."""
        if self.on_progress is None:
            return
        pct = parse_progress(line)
        if pct is not None:
            self.on_progress(pct)
