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

from PySide6.QtCore import QThread, Signal

from aynthor.core.converters.registry import get_converter
from aynthor.core.models import ConversionJob


class JobRunner(QThread):
    log = Signal(str)
    job_started = Signal(int)                    # row
    job_progress = Signal(int, int)              # row, percent
    job_finished = Signal(int, object, bool, str)  # row, job, ok, message

    def __init__(self, jobs: list[tuple[int, ConversionJob]]) -> None:
        super().__init__()
        self._jobs = jobs
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        total = len(self._jobs)
        for index, (row, job) in enumerate(self._jobs, start=1):
            if self._cancelled:
                self.log.emit(f"Cancelled with {total - index + 1} job(s) left.")
                break

            self.job_started.emit(row)
            self.log.emit(f"[{index}/{total}] {job.input_path.name}")

            converter = get_converter(job.format)
            if converter is None:
                self.job_finished.emit(row, job, False, f"No converter for {job.format.value}.")
                continue

            converter.on_progress = lambda pct, r=row: self.job_progress.emit(r, pct)
            try:
                ok, message = converter.convert(job)
            except Exception as exc:  # noqa: BLE001 - a crash here must not take the app with it
                ok, message = False, f"{type(exc).__name__}: {exc}"
            finally:
                converter.on_progress = None

            # Measured after the run because a converter may have corrected the
            # output path, which several of them do.
            try:
                job.output_size = job.output_path.stat().st_size
            except OSError:
                job.output_size = 0

            if ok and job.options.get("delete_source"):
                removed = self._delete_source(job)
                if removed:
                    message = f"{message} Source deleted."

            job.status = "done" if ok else "error"
            job.message = message
            self.job_finished.emit(row, job, ok, message)

    def _delete_source(self, job: ConversionJob) -> bool:
        """Remove the input, but only when there is provably something to keep.

        Three conditions, all of them because this destroys the user's ROM: the
        job reported success, the output is a different file from the input
        (NDS trim rewrites in place), and that output exists and is not empty.
        A converter that exits zero having written nothing is rare but it has
        happened, and the cost of getting this wrong is unrecoverable.
        """
        try:
            if job.output_path.resolve() == job.input_path.resolve():
                return False
            if not job.output_path.is_file() or job.output_path.stat().st_size == 0:
                self.log.emit(f"Kept {job.input_path.name}: the output looks empty.")
                return False
            job.input_path.unlink()
            return True
        except OSError as exc:
            self.log.emit(f"Could not delete {job.input_path.name}: {exc}")
            return False
