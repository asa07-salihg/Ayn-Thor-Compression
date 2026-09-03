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
