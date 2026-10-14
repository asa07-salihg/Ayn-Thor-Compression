"""Before Start: what would go wrong, with a button that fixes each thing.

`core.preflight` finds the problems; this is the window that asks about
them. Each one gets a plain sentence, a fix (install the programs, choose
`prod.keys`) and a way to leave those files out of this run. Start stays
disabled until every problem that would fail a row is fixed or skipped,
so nobody watches a batch turn red for a reason the app already knew.

The delete-sources warning lives here too. It used to be a separate box
that appeared after Start, and now it is one more line to read before
anything is touched.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from aynthor.core.preflight import Problem, ProblemKind
from aynthor.core.settings import FormatSettings
from aynthor.core.tools.manifest import SPECS_BY_KEY
from aynthor.ui import icons
from aynthor.ui.tools_dialog import InstallWorker

_OPEN, _FIXED, _SKIPPED = "open", "fixed", "skipped"

_PROBLEM_ICONS = {
    ProblemKind.DEVICE_NOT_READY: ("sd-card", "warn"),
    ProblemKind.MISSING_TOOLS: ("package", "warn"),
    ProblemKind.NO_SWITCH_KEYS: ("key", "warn"),
    ProblemKind.UNKNOWN_PLATFORM: ("help", "textSecond"),
}


def _files(count: int) -> str:
    return f"{count} file{'s' if count != 1 else ''}"


def _joined(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def describe(problem: Problem) -> str:
    """The sentence shown for a problem."""
    count = len(problem.rows)
    needs = "needs" if count == 1 else "need"
    if problem.kind is ProblemKind.DEVICE_NOT_READY:
        return f"{problem.detail} ({_files(count)} {'is' if count == 1 else 'are'} waiting for it.)"
    if problem.kind is ProblemKind.MISSING_TOOLS:
        names = [SPECS_BY_KEY[key].label if key in SPECS_BY_KEY else key
                 for key in problem.tools]
        verb = "isn't" if len(names) == 1 else "aren't"
        return (f"{_files(count)} {needs} {_joined(names)} to convert, and "
                f"{'it' if len(names) == 1 else 'they'} {verb} installed yet.")
    if problem.kind is ProblemKind.NO_SWITCH_KEYS:
        return (f"{count} Switch file{'s' if count != 1 else ''} {needs} a prod.keys "
                "file from your own Switch.")
    return (f"The app couldn't tell which console {_files(count)} "
            f"{'is' if count == 1 else 'are'} for, so "
            f"{'it' if count == 1 else 'they'} would be saved next to the original "
            "instead of in your ROMs folder. To fix that, close this and click Choose... "
            "in the Platform column.")


class PreflightDialog(QDialog):
    def __init__(
        self,
        problems: list[Problem],
        settings: FormatSettings,
        recheck: Callable[[], list[Problem]],
        *,
        use_keys: Callable[[Path], None] | None = None,
        deletes_sources: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Before you start")
        self.setMinimumWidth(560)
        self.settings = settings
        self._recheck = recheck
        self._use_keys = use_keys
        self._problems = {problem.kind: problem for problem in problems}
        self._state = {kind: _OPEN for kind in self._problems}
        self._notes: dict[ProblemKind, str] = {}
        self._rows: dict[ProblemKind, dict[str, QWidget]] = {}
        self._worker: InstallWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(12)

        heading = QLabel("Before you start")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        for problem in problems:
            layout.addWidget(self._problem_card(problem))

        if deletes_sources:
            warning = QLabel(
                "'Delete the original after it converts' is on. Each original file "
                "is removed once its converted file has been written.")
            warning.setWordWrap(True)
            warning.setProperty("role", "warn")
            layout.addWidget(warning)

        layout.addStretch()
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.start_button = QPushButton(
            "Start and delete originals" if deletes_sources else "Start")
        self.start_button.setProperty("accent", True)
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.accept)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)

        self._refresh()

    # ----------------------------------------------------------------- cards

    def _problem_card(self, problem: Problem) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        column = QVBoxLayout(card)
        column.setContentsMargins(14, 12, 14, 12)
        column.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(12)
        icon_name, colour = _PROBLEM_ICONS[problem.kind]
        badge = QLabel()
        badge.setPixmap(icons.pixmap(icon_name, colour, 24, self.devicePixelRatioF()))
        badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(badge)
        text = QLabel(describe(problem))
        text.setWordWrap(True)
        top.addWidget(text, stretch=1)
        column.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(8)
        fix: QPushButton | None = None
        if problem.kind is ProblemKind.MISSING_TOOLS:
            fix = QPushButton("Install now")
            fix.clicked.connect(self._install)
        elif problem.kind is ProblemKind.NO_SWITCH_KEYS:
            fix = QPushButton("Choose prod.keys...")
            fix.clicked.connect(self._pick_keys)
        elif problem.kind is ProblemKind.DEVICE_NOT_READY:
            fix = QPushButton("Try again")
            fix.clicked.connect(self._apply_recheck)
        if fix is not None:
            fix.setProperty("accent", True)
            row.addWidget(fix)

        skip = QPushButton(self._skip_text(problem))
        skip.setProperty("subtle", True)
        skip.clicked.connect(lambda _c=False, k=problem.kind: self.skip(k))
        row.addWidget(skip)
        undo = QPushButton("Undo")
        undo.setProperty("subtle", True)
        undo.clicked.connect(lambda _c=False, k=problem.kind: self.undo(k))
        row.addWidget(undo)
        status = QLabel()
        status.setProperty("role", "second")
        row.addWidget(status, stretch=1)
        column.addLayout(row)

        self._rows[problem.kind] = {
            "text": text, "fix": fix, "skip": skip, "undo": undo, "status": status}
        return card

    @staticmethod
    def _skip_text(problem: Problem) -> str:
        if problem.kind is ProblemKind.NO_SWITCH_KEYS:
            return "Skip Switch files"
        if problem.kind is ProblemKind.UNKNOWN_PLATFORM:
            return "Skip them" if len(problem.rows) != 1 else "Skip it"
        return "Skip these files"

    def _refresh(self) -> None:
        for kind, widgets in self._rows.items():
            state = self._state[kind]
            if widgets["fix"] is not None:
                widgets["fix"].setVisible(state == _OPEN)
            widgets["skip"].setVisible(state == _OPEN)
            widgets["undo"].setVisible(state == _SKIPPED)
            widgets["status"].setText({
                _OPEN: self._notes.get(kind, ""),
                _FIXED: "Fixed.",
                _SKIPPED: "These files won't run this time.",
            }[state])
        busy = self._installing()
        self.start_button.setEnabled(not busy and self.ready())
        self.cancel_button.setEnabled(not busy)

    # --------------------------------------------------------------- choices

    def ready(self) -> bool:
        """Every problem that would fail a row is fixed or skipped."""
        return all(self._state[kind] != _OPEN
                   for kind, problem in self._problems.items() if problem.blocking)

    def skip(self, kind: ProblemKind) -> None:
        if kind in self._state:
            self._state[kind] = _SKIPPED
            self._refresh()

    def undo(self, kind: ProblemKind) -> None:
        if kind in self._state:
            self._state[kind] = _OPEN
            self._refresh()

    def skipped_rows(self) -> set[int]:
        return {row for kind, problem in self._problems.items()
                if self._state[kind] == _SKIPPED for row in problem.rows}

    def choose_keys(self, path: Path) -> None:
        if self._use_keys is not None:
            self._use_keys(path)
        else:
            self.settings.keys_path = str(path)
        self._apply_recheck()

    def _pick_keys(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose prod.keys", "", "Switch keys (*.keys);;All files (*)")
        if path:
            self.choose_keys(Path(path))

    def _apply_recheck(self) -> None:
        still = {problem.kind: problem for problem in self._recheck()}
        for kind in self._problems:
            if self._state[kind] == _OPEN and kind not in still:
                self._state[kind] = _FIXED
            elif kind in still and self._state[kind] == _OPEN:
                self._problems[kind] = still[kind]
                self._rows[kind]["text"].setText(describe(still[kind]))
        self._refresh()

    # ------------------------------------------------------------ installing

    def _install(self) -> None:
        widgets = self._rows[ProblemKind.MISSING_TOOLS]
        self._notes[ProblemKind.MISSING_TOOLS] = "Installing..."
        for key in ("fix", "skip"):
            widgets[key].setEnabled(False)
        self._worker = InstallWorker()
        self._worker.log.connect(self._install_progress)
        self._worker.done.connect(self._installed)
        # `done` is emitted from inside the thread, which may still be running
        # when it arrives; Start is re-enabled only once it has really stopped.
        self._worker.finished.connect(self._refresh)
        self._worker.start()
        self._refresh()

    def _install_progress(self, line: str) -> None:
        first = line.splitlines()[0] if line else ""
        self._notes[ProblemKind.MISSING_TOOLS] = first[:80]
        self._rows[ProblemKind.MISSING_TOOLS]["status"].setText(first[:80])

    def _installed(self, errors: list[str]) -> None:
        widgets = self._rows[ProblemKind.MISSING_TOOLS]
        for key in ("fix", "skip"):
            widgets[key].setEnabled(True)
        self._notes[ProblemKind.MISSING_TOOLS] = (
            "Some programs could not be installed. Check the internet connection, "
            "or open Tools for details." if errors else "")
        self._apply_recheck()

    def _installing(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def reject(self) -> None:
        if self._installing():
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._installing():
            event.ignore()
            return
        super().closeEvent(event)
