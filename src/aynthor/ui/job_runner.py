"""Run the queue on a worker thread and report back to the window.

The work itself is `core.batch`. This only gives it a thread of its own, so a
conversion that takes an hour does not freeze the window, and turns its
callbacks into Qt signals, which Qt delivers on the window's thread.

A device is opened on this thread and used only from it: COM objects belong to
the thread that made them.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, ExitStack

from PySide6.QtCore import QThread, Signal

from aynthor.core.batch import Batch, Events, Outcome
from aynthor.core.device import DeviceError, DeviceFS, DeviceTarget, com_thread, open_target
from aynthor.core.models import ConversionJob


class JobRunner(QThread):
    log = Signal(str)
    job_started = Signal(int)                      # row id
    job_progress = Signal(int, int)                # row id, percent
    job_stage = Signal(int, str)                   # row id, what it is doing now
    job_finished = Signal(int, object, str, str)   # row id, job, Outcome value, message

    def __init__(
        self,
        jobs: list[tuple[int, ConversionJob]],
        *,
        policy: str = "skip",
        device: DeviceTarget | None = None,
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._policy = policy
        self._device = device
        self._batch: Batch | None = None
        self._stop = False

    def cancel(self) -> None:
        self._stop = True
        if self._batch is not None:
            self._batch.cancel()

    def run(self) -> None:
        events = Events(
            log=self.log.emit,
            started=self.job_started.emit,
            progress=self.job_progress.emit,
            stage=self.job_stage.emit,
            finished=lambda row, job, outcome, message: self.job_finished.emit(
                row, job, Outcome(outcome).value, message),
        )
        with ExitStack() as stack:
            opener = None
            if self._device is not None and any(job.remote for _, job in self._jobs):
                opener = self._opener(stack)
            self._batch = Batch(self._jobs, policy=self._policy, events=events,
                                open_device=opener)
            if self._stop:
                self._batch.cancel()
            self._batch.run()

    def _opener(self, stack: ExitStack):
        target = self._device
        assert target is not None
        try:
            runtime = stack.enter_context(com_thread())
        except OSError as exc:
            message = f"Sending to {target.device_name} needs Windows ({exc})."

            def refuse() -> AbstractContextManager[DeviceFS]:
                raise DeviceError(message)
            return refuse
        return lambda: open_target(target, runtime)
