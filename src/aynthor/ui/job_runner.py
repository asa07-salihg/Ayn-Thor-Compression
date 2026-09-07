"""Run the queue on a worker thread and report back to the window.

Why
    Every converter blocks for minutes at a time, so the work cannot happen on
    the thread that paints the window. A QThread with signals is the smallest
    thing that gives the queue a live progress column without any locking of
    our own: Qt queues the signals across the thread boundary.

    Jobs run one at a time, on purpose. The external tools already use every
    core they are given, so running several at once makes the whole batch
    slower on CPU and much slower on the disk these files live on, which is
    usually an SD card. It also keeps the log readable: interleaved output from
    three compressors is worth nothing when something fails.

    Cancellation is cooperative and takes effect between jobs. Killing a
    converter mid-write would leave a truncated file that looks finished.

Used by
    `ui.main_window`.

Reference
    https://doc.qt.io/qt-6/qthread.html
"""

from __future__ import annotations

import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from aynthor.core.converters.base import is_decompress, place_file
from aynthor.core.converters.registry import get_converter
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode
from aynthor.core.unpack import ArchiveScratch, UnpackError, extract_member_to, unpacked

# Some filesystems record whole seconds, and a fast conversion can finish
# inside one, so a small allowance keeps a genuine output from being mistaken
# for a stale one.
_CLOCK_MARGIN = 2.0


class JobRunner(QThread):
    log = Signal(str)
    job_started = Signal(int)                    # row
    job_progress = Signal(int, int)              # row, percent
    job_finished = Signal(int, object, bool, str)  # row, job, ok, message

    def __init__(self, jobs: list[tuple[int, ConversionJob]]) -> None:
        super().__init__()
        self._jobs = jobs
        self._cancelled = False
        self._scratches: dict[Path, ArchiveScratch] = {}
        self._pending_members: Counter[Path] = Counter()
        self._failed_archives: set[Path] = set()

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._jobs)
        self._pending_members = Counter(
            job.input_path for _, job in self._jobs if job.member)
        try:
            for index, (row, job) in enumerate(self._jobs, start=1):
                if self._cancelled:
                    self.log.emit(f"Cancelled with {total - index + 1} job(s) left.")
                    break

                self.job_started.emit(row)
                shown = job.input_path.name
                if job.member:
                    shown = f"{shown} [{job.member.rsplit('/', 1)[-1]}]"
                self.log.emit(f"[{index}/{total}] {shown}")

                started_at = time.time()
                try:
                    ok, message = self._execute(row, job)
                except Exception as exc:  # noqa: BLE001 - a crash here must not take the app with it
                    ok, message = False, f"{type(exc).__name__}: {exc}"

                if job.member and not ok:
                    self._failed_archives.add(job.input_path)

                # Measured after the run because a converter may have corrected the
                # output path, which several of them do.
                try:
                    job.output_size = job.output_path.stat().st_size
                except OSError:
                    job.output_size = 0

                if ok and job.options.get("delete_source"):
                    removed = self._delete_source(job, started_at)
                    if removed:
                        message = f"{message} Source deleted."

                job.status = "done" if ok else "error"
                job.message = message
                self.job_finished.emit(row, job, ok, message)
        finally:
            self._close_scratches()

    def _execute(self, row: int, job: ConversionJob) -> tuple[bool, str]:
        """Unpack if needed, create the output folder, convert or just place."""
        job.output_path.parent.mkdir(parents=True, exist_ok=True)
        original = job.input_path
        converter = get_converter(job.format)
        try:
            # Move from a zip/rar: write the member once into the game folder.
            # Unpacking beside the card into `.aynthor-unpack-*` then copying
            # doubled both time and free space for large NSPs.
            if job.member and self._will_place(job):
                return self._place_archive_member(row, job)

            with self._opened(row, job) as source:
                job.input_path = source
                if converter is None:
                    return False, f"No converter for {job.format.value}."
                if self._should_place(job):
                    self.log.emit(f"Copying into {job.output_path.parent.name}…")
                    return place_file(
                        job,
                        on_progress=lambda pct, r=row: self.job_progress.emit(r, pct),
                    )
                converter.on_progress = lambda pct, r=row: self.job_progress.emit(r, pct)
                try:
                    return converter.convert(job)
                finally:
                    converter.on_progress = None
        finally:
            job.input_path = original

    def _place_archive_member(self, row: int, job: ConversionJob) -> tuple[bool, str]:
        archive = job.input_path
        self.log.emit(f"Extracting into {job.output_path.parent.name}…")
        try:
            extract_member_to(
                archive,
                job.member,
                job.output_path,
                on_progress=lambda pct, r=row: self.job_progress.emit(r, pct),
            )
        except UnpackError as exc:
            return False, str(exc)
        except OSError as exc:
            return False, f"Could not extract into its folder: {exc}"
        finally:
            if self._pending_members[archive] > 0:
                self._pending_members[archive] -= 1
        return True, "Placed in its game folder."

    def _will_place(self, job: ConversionJob) -> bool:
        """Whether this job only needs the file in its game folder (no convert)."""
        if job.options.get("mode") == ConversionMode.MOVE.value:
            return True
        if job.format is CompressionFormat.NDS_TRIM or is_decompress(job):
            return False
        if job.member:
            return Path(job.member).suffix.lower() == job.output_path.suffix.lower()
        return job.input_path.suffix.lower() == job.output_path.suffix.lower()

    @contextmanager
    def _opened(self, row: int, job: ConversionJob):
        """The file the converter reads: the extracted member, or the input.

        Members of the same archive share one extraction. A zip of four discs
        is unpacked once, then each row reads its file from that folder.
        """
        if not job.member:
            yield job.input_path
            return
        archive = job.input_path
        if self._pending_members[archive] <= 0:
            # A one-off call (tests, or a row added outside run) unpacks and
            # cleans up on its own.
            with unpacked(
                archive, job.member,
                on_progress=lambda pct, r=row: self.job_progress.emit(r, pct),
            ) as inner:
                yield inner
            return
        scratch = self._scratches.get(archive)
        if scratch is None:
            scratch = ArchiveScratch(
                archive,
                on_progress=lambda pct, r=row: self.job_progress.emit(r, pct),
            )
            self._scratches[archive] = scratch
        try:
            yield scratch.path_for(job.member)
        finally:
            self._pending_members[archive] -= 1
            if self._pending_members[archive] <= 0:
                self._close_scratch(archive)

    def _close_scratch(self, archive: Path) -> None:
        scratch = self._scratches.pop(archive, None)
        if scratch is not None:
            self.log.emit(f"Cleaning up extract of {archive.name}…")
            scratch.close()

    def _close_scratches(self) -> None:
        for scratch in self._scratches.values():
            scratch.close()
        self._scratches.clear()

    @staticmethod
    def _should_place(job: ConversionJob) -> bool:
        """Already the target container, or the user chose Move / archive Unzip."""
        mode = job.options.get("mode")
        if mode == ConversionMode.MOVE.value:
            return True
        if job.format is CompressionFormat.NDS_TRIM or is_decompress(job):
            return False
        return job.input_path.suffix.lower() == job.output_path.suffix.lower()

    def _delete_source(self, job: ConversionJob, started_at: float) -> bool:
        """Remove the input, but only when there is provably something to keep.

        Four conditions, all of them because this destroys the user's ROM: the
        job reported success, the output is a different file from the input
        (NDS trim rewrites in place), that output exists and is not empty, and
        it was written by this run.

        The last one is the difference between "an output exists" and "this
        conversion produced one". With the conflict policy on overwrite a row
        is not skipped when its output is already there, so a leftover from an
        earlier run satisfied the other three on its own: a converter that
        exited zero without writing anything -- the exact case this guards
        against -- would then have deleted the source against somebody else's
        file. The margin absorbs a filesystem whose timestamps are coarse.
        """
        try:
            if job.member:
                # Other discs from this zip have not finished, or one of them
                # failed: keep the archive until every member has a result.
                if self._pending_members[job.input_path] > 0:
                    return False
                if job.input_path in self._failed_archives:
                    return False
            if job.output_path.resolve() == job.input_path.resolve():
                return False
            if not job.input_path.exists():
                # In-place fold already moved the file into the game folder.
                return True
            if not job.output_path.is_file() or job.output_path.stat().st_size == 0:
                self.log.emit(f"Kept {job.input_path.name}: the output looks empty.")
                return False
            if job.output_path.stat().st_mtime < started_at - _CLOCK_MARGIN:
                self.log.emit(
                    f"Kept {job.input_path.name}: {job.output_path.name} was already "
                    "there and this run did not write it.")
                return False
            job.input_path.unlink()
            return True
        except OSError as exc:
            self.log.emit(f"Could not delete {job.input_path.name}: {exc}")
            return False
