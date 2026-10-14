"""Run a list of jobs, one after another, and say how each one went.

Every decision about a job is made when its turn comes, not when the file was
added and not when Start was pressed:

* Is there anything to do? A `.7z` that is already where it belongs is
  reported as skipped instead of being refused at the door, so it can still
  be queued and later moved to a card or a device.
* Is the result already there? For a folder that is the conflict setting
  against the disk and against what this batch has written so far; for a
  device it is asked of the device, before an hour is spent converting.
* Then convert or copy, then send it to the device if that is where it goes.

Jobs run one at a time. The converters already use every core they are given,
and these files usually live on an SD card, which is far slower with two
writers than with one.

The Qt side (`ui.job_runner`) only moves this onto a worker thread and turns
the callbacks into signals, which is why all of it can be tested without Qt.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath

from aynthor.core.converters.base import is_decompress, place_file
from aynthor.core.converters.registry import get_converter
from aynthor.core.device import deliver
from aynthor.core.device.fs import DeviceError, DeviceFS, SendCancelled
from aynthor.core.jobs import resolve_output_path
from aynthor.core.models import CompressionFormat, ConversionJob, ConversionMode
from aynthor.core.sheets import disc_size, is_sheet, missing_track, relative_tracks, tracks
from aynthor.core.unpack import ArchiveScratch, UnpackError, extract_member_to, unpacked

# Some filesystems record whole seconds, and a fast conversion can finish
# inside one, so a small allowance keeps a genuine output from being mistaken
# for a stale one.
CLOCK_MARGIN = 2.0


class Outcome(str, Enum):
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


def _nothing(*_args: object) -> None:
    return None


@dataclass
class Events:
    log: Callable[[str], None] = _nothing
    started: Callable[[int], None] = _nothing
    progress: Callable[[int, int], None] = _nothing
    stage: Callable[[int, str], None] = _nothing
    finished: Callable[[int, ConversionJob, Outcome, str], None] = _nothing


OpenDevice = Callable[[], AbstractContextManager[DeviceFS]]


@dataclass
class _Session:
    """The device, opened once for the whole batch."""

    opener: OpenDevice
    stack: ExitStack = field(default_factory=ExitStack)
    fs: DeviceFS | None = None

    def get(self) -> DeviceFS:
        if self.fs is None:
            self.fs = self.stack.enter_context(self.opener())
        return self.fs

    def drop(self) -> None:
        """Forget a device that stopped answering, so the next job reopens it."""
        self.stack.close()
        self.stack = ExitStack()
        self.fs = None


class Batch:
    def __init__(
        self,
        jobs: list[tuple[int, ConversionJob]],
        *,
        policy: str = "skip",
        events: Events | None = None,
        open_device: OpenDevice | None = None,
    ) -> None:
        self.jobs = jobs
        self.policy = policy
        self.events = events or Events()
        self._device = _Session(open_device) if open_device is not None else None
        self._cancelled = False
        self._claimed: set[Path] = set()
        self._sent: set[PurePosixPath] = set()
        self._scratches: dict[Path, ArchiveScratch] = {}
        self._pending_members: Counter[Path] = Counter()
        self._failed_archives: set[Path] = set()
        self._settled: set[int] = set()

    # ------------------------------------------------------------- control

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        total = len(self.jobs)
        self._pending_members = Counter(job.input_path for _, job in self.jobs if job.member)
        try:
            for index, (row, job) in enumerate(self.jobs, start=1):
                if self._cancelled:
                    self.events.log(f"Stopped with {total - index + 1} left to do.")
                    break
                self.events.started(row)
                shown = job.input_path.name
                if job.member:
                    shown = f"{shown} [{job.member.rsplit('/', 1)[-1]}]"
                self.events.log(f"[{index}/{total}] {shown}")
                try:
                    outcome, message = self._one(row, job)
                except Exception as exc:  # noqa: BLE001 - one bad job must not end the batch
                    outcome, message = Outcome.FAILED, f"{type(exc).__name__}: {exc}"
                self._settle(job, failed=outcome is Outcome.FAILED)
                job.status = outcome.value
                job.message = message
                self.events.finished(row, job, outcome, message)
        finally:
            self._close_scratches()
            if self._device is not None:
                self._device.drop()

    # ----------------------------------------------------------- one job

    def _one(self, row: int, job: ConversionJob) -> tuple[Outcome, str]:
        started_at = time.time()
        if job.remote:
            return self._to_device(row, job, started_at)

        if self._nothing_to_do(job):
            return Outcome.SKIPPED, (
                f"Nothing to do: {job.input_path.name} is already a "
                f"{job.input_path.suffix.lstrip('.')} where it belongs.")
        output = resolve_output_path(job.output_path, self.policy, self._claimed)
        if output is None:
            return Outcome.SKIPPED, f"{job.output_path.name} is already there."
        job.output_path = output
        self._claimed.add(output)

        ok, message = self.execute(row, job)
        self._measure(job)
        self._settle(job, failed=not ok)
        if not ok:
            return Outcome.FAILED, message
        if job.options.get("delete_source") and self.delete_source(job, started_at):
            message = f"{message} Source deleted."
        return Outcome.DONE, message

    def _to_device(self, row: int, job: ConversionJob, started_at: float) -> tuple[Outcome, str]:
        assert self._device is not None, "a job for a device needs a device to open"
        try:
            fs = self._device.get()
            decided = deliver.plan(fs, PurePosixPath(job.remote), self.policy, self._sent)
        except DeviceError as exc:
            self._device.drop()
            return Outcome.FAILED, str(exc)
        if decided.remote is None:
            return Outcome.SKIPPED, decided.reason

        staged = job.output_path
        if self._only_copies(job) and not job.member:
            local = job.input_path
            problem = missing_track(local)
            if problem:
                return Outcome.FAILED, problem
        else:
            made_from = deliver.fingerprint(job.input_path, job.member, job.format.value,
                                            job.options)
            if deliver.can_reuse(staged, made_from):
                self.events.log(f"Using {staged.name}, converted on the last run.")
            else:
                ok, message = self.execute(row, job)
                if not ok:
                    deliver.clear(staged)
                    return Outcome.FAILED, message
                staged = job.output_path   # a converter may have corrected the name
                deliver.remember(staged, made_from)
            local = staged

        size = disc_size(local)
        listed = relative_tracks(local)
        self.events.stage(row, f"Sending to {fs.label}")
        self.events.progress(row, 0)
        try:
            if listed:
                remote = deliver.send_disc(
                    fs, local, listed, decided,
                    on_progress=lambda pct: self.events.progress(row, pct),
                    cancelled=lambda: self._cancelled)
            else:
                remote = deliver.send(
                    fs, local, decided,
                    on_progress=lambda pct: self.events.progress(row, pct),
                    cancelled=lambda: self._cancelled)
        except SendCancelled:
            return Outcome.FAILED, "Stopped while sending. " + self._kept(local, staged)
        except DeviceError as exc:
            self._device.drop()
            return Outcome.FAILED, f"{exc} " + self._kept(local, staged)
        self._sent.add(remote)
        self._settle(job, failed=False)
        job.output_size = size
        if local == staged:
            deliver.clear(staged)
        message = f"Sent to {fs.label}."
        if remote != PurePosixPath(job.remote):
            message = f"Sent to {fs.label} as {remote.name}."
        if job.options.get("delete_source") and self._delete_after_send(job):
            message = f"{message} Source deleted."
        return Outcome.DONE, message

    @staticmethod
    def _kept(local: Path, staged: Path) -> str:
        if local == staged and staged.is_file():
            return "The converted file is kept, and goes across on the next Start."
        return ""

    def _delete_after_send(self, job: ConversionJob) -> bool:
        """The device confirmed the file at the right size, which is a stronger
        proof than a timestamp, so that is the only condition besides the
        archive rule."""
        if job.member and not self._archive_finished(job.input_path):
            return False
        return self._remove_source(job.input_path, kept=job.output_path)

    def _remove_source(self, source: Path, kept: Path | None = None) -> bool:
        """Delete the source, and the tracks it lists if it is a cue sheet:
        the CHD or the copy holds them now, and a folder of orphaned `.bin`
        files is most of the space the user asked to get back."""
        in_use = {_same(t) for t in tracks(kept)} if kept is not None else set()
        listed = [t for t in tracks(source) if _same(t) not in in_use]
        try:
            source.unlink()
        except OSError as exc:
            self.events.log(f"Could not delete {source.name}: {exc}")
            return False
        for track in listed:
            try:
                track.unlink(missing_ok=True)
            except OSError as exc:
                self.events.log(f"Could not delete {track.name}: {exc}")
        return True

    @staticmethod
    def _measure(job: ConversionJob) -> None:
        # After the run, because a converter may have corrected the output
        # path, which several of them do.
        try:
            job.output_size = job.output_path.stat().st_size
        except OSError:
            job.output_size = 0

    @staticmethod
    def _nothing_to_do(job: ConversionJob) -> bool:
        if job.member or job.format is CompressionFormat.NDS_TRIM:
            return False
        if job.options.get("mode") not in (None, ConversionMode.COMPRESS.value,
                                           ConversionMode.MOVE.value):
            return False
        try:
            return job.output_path.resolve() == job.input_path.resolve()
        except OSError:
            return job.output_path == job.input_path

    # ------------------------------------------------- convert or place

    def execute(self, row: int, job: ConversionJob) -> tuple[bool, str]:
        """Unpack if needed, create the output folder, convert or just place."""
        parent = job.output_path.parent
        if not parent.is_file():
            # `exist_ok` only forgives a directory, so this raised for the one
            # case game folders are built around: folding a loose `Game.7z`
            # into `Game.7z/Game.7z` asks for a folder whose path is the source
            # file. `place_file` moves the file aside and makes the folder.
            parent.mkdir(parents=True, exist_ok=True)
        original = job.input_path
        converter = get_converter(job.format)
        progress = self._progress(row)
        try:
            # Move from a zip or rar: write the member once, straight into its
            # folder, instead of unpacking beside it and copying.
            # A cue sheet's tracks are other members of the same archive, so
            # it is unpacked with them and placed from there.
            if job.member and self._will_place(job) and not is_sheet(Path(job.member)):
                return self._place_archive_member(job, progress)

            with self._opened(job, progress) as source:
                job.input_path = source
                if converter is None:
                    return False, f"No converter for {job.format.value}."
                if self._only_copies(job):
                    self.events.log(f"Copying into {job.output_path.parent.name}…")
                    return place_file(job, on_progress=progress)
                converter.on_progress = progress
                try:
                    return converter.convert(job)
                finally:
                    converter.on_progress = None
        finally:
            job.input_path = original

    def _progress(self, row: int) -> Callable[[int], None]:
        return lambda pct: self.events.progress(row, pct)

    def _place_archive_member(self, job: ConversionJob,
                              progress: Callable[[int], None]) -> tuple[bool, str]:
        archive = job.input_path
        self.events.log(f"Extracting into {job.output_path.parent.name}…")
        try:
            extract_member_to(archive, job.member, job.output_path, on_progress=progress)
        except UnpackError as exc:
            return False, str(exc)
        except OSError as exc:
            return False, f"Could not extract into its folder: {exc}"
        return True, "Placed in its game folder."

    @staticmethod
    def _will_place(job: ConversionJob) -> bool:
        """Whether this job only needs the file in its folder (no convert)."""
        if job.options.get("mode") == ConversionMode.MOVE.value:
            return True
        if job.format is CompressionFormat.NDS_TRIM or is_decompress(job):
            return False
        source = Path(job.member) if job.member else job.input_path
        return source.suffix.lower() == job.output_path.suffix.lower()

    @staticmethod
    def _only_copies(job: ConversionJob) -> bool:
        """Already the target container, or the user chose Move / archive Unzip."""
        if job.options.get("mode") == ConversionMode.MOVE.value:
            return True
        if job.format is CompressionFormat.NDS_TRIM or is_decompress(job):
            return False
        return job.input_path.suffix.lower() == job.output_path.suffix.lower()

    @contextmanager
    def _opened(self, job: ConversionJob, progress: Callable[[int], None]) -> Iterator[Path]:
        """The file the converter reads: the extracted member, or the input.

        Members of the same archive share one extraction: a zip of four discs
        is unpacked once and each row reads its file from that folder.
        """
        if not job.member:
            yield job.input_path
            return
        archive = job.input_path
        if self._pending_members[archive] <= 0:
            # A job outside `run` unpacks and cleans up on its own.
            with unpacked(archive, job.member, on_progress=progress) as inner:
                yield inner
            return
        scratch = self._scratches.get(archive)
        if scratch is None:
            scratch = ArchiveScratch(archive, on_progress=progress)
            self._scratches[archive] = scratch
        yield scratch.path_for(job.member)

    def _settle(self, job: ConversionJob, *, failed: bool) -> None:
        """Count a member job as finished, once, however it ended. The shared
        extraction is removed when the last disc of its archive is done."""
        if not job.member or id(job) in self._settled:
            return
        self._settled.add(id(job))
        self._member_done(job.input_path, failed=failed)

    def _member_done(self, archive: Path, *, failed: bool) -> None:
        if failed:
            self._failed_archives.add(archive)
        if self._pending_members[archive] > 0:
            self._pending_members[archive] -= 1
        if self._pending_members[archive] <= 0:
            scratch = self._scratches.pop(archive, None)
            if scratch is not None:
                self.events.log(f"Cleaning up the unpacked copy of {archive.name}…")
                scratch.close()

    def _archive_finished(self, archive: Path) -> bool:
        return self._pending_members[archive] <= 0 and archive not in self._failed_archives

    def _close_scratches(self) -> None:
        for scratch in self._scratches.values():
            scratch.close()
        self._scratches.clear()

    # ------------------------------------------------------ delete source

    def delete_source(self, job: ConversionJob, started_at: float) -> bool:
        """Remove the input, but only when there is provably something to keep.

        Four conditions, all of them because this destroys the user's ROM: the
        job reported success, the output is a different file from the input
        (NDS trim rewrites in place), that output exists and is not empty, and
        it was written by this run.

        The last is the difference between "an output exists" and "this
        conversion produced one". On overwrite a leftover from an earlier run
        met the other three by itself, and a converter that exited zero
        without writing anything would have deleted the source against
        somebody else's file.
        """
        try:
            if job.member and not self._archive_finished(job.input_path):
                # Other discs from this zip have not finished, or one failed.
                return False
            if job.output_path.resolve() == job.input_path.resolve():
                return False
            if not job.input_path.is_file():
                # An in-place fold already moved the file into its folder,
                # which now has the file's name.
                return True
            if not job.output_path.is_file() or job.output_path.stat().st_size == 0:
                self.events.log(f"Kept {job.input_path.name}: the output looks empty.")
                return False
            if job.output_path.stat().st_mtime < started_at - CLOCK_MARGIN:
                self.events.log(
                    f"Kept {job.input_path.name}: {job.output_path.name} was already "
                    "there and this run did not write it.")
                return False
        except OSError as exc:
            self.events.log(f"Could not delete {job.input_path.name}: {exc}")
            return False
        return self._remove_source(job.input_path, kept=job.output_path)


def _same(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path
