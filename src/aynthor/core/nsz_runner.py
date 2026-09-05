"""Run the bundled nsz package as a subprocess of ourselves.

Why
    Two problems, one solution. First, nsz's pip console script is a launcher
    stub that only works next to the Python environment it was installed into,
    so it cannot be shipped inside a frozen exe. Second, nsz uses
    `multiprocessing` and mutates global state during a run, so importing it
    into the GUI process left worker processes behind when a job was cancelled.

    The app therefore re-invokes its own executable with `--nsz-cli` and lets
    that process be nsz. `__main__.main` picks the flag up before Qt is
    imported, so the child never builds a window.

    nsz resolves its keys file relative to `sys.argv[0]` at import time, which
    is why the passthrough sets argv[0] to a bare name: the lookup then falls
    back to the working directory, where `stage_keys` has put the keys.

Used by
    `core.converters.nsz.NszConverter`, `__main__.main` (the flag).

Reference
    https://github.com/nicoboss/nsz
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from aynthor.core.runtime import is_frozen
from aynthor.core.system import app_data_dir


def nsz_command() -> tuple[list[str], Path, dict[str, str]]:
    """Return (command prefix, working directory, extra env) for the nsz CLI.

    nsz resolves keys.txt relative to sys.argv[0] at import time; the
    passthrough sets argv[0] to a bare name so the lookup falls back to the
    working directory, where the converter stages keys.txt.
    """
    workdir = app_data_dir()
    if is_frozen():
        return [sys.executable, "--nsz-cli"], workdir, {}
    # Dev mode: run the package with the project root on PYTHONPATH so `-m`
    # works even when the package is not pip-installed.
    project_root = Path(__file__).resolve().parents[2]
    pythonpath = os.pathsep.join(
        p for p in (str(project_root), os.environ.get("PYTHONPATH", "")) if p
    )
    return (
        [sys.executable, "-m", "aynthor", "--nsz-cli"],
        workdir,
        {"PYTHONPATH": pythonpath},
    )


@contextmanager
def staged_keys(keys_file: Path, workdir: Path) -> Iterator[None]:
    """Put keys.txt where nsz will find it, for exactly as long as the run.

    Why
        nsz reads keys.txt from its working directory, so the file has to be
        copied there. What it must not do is stay there: this used to leave a
        second permanent copy of the user's console keys in the app's data
        folder, where nothing would ever remove it and the user had no reason
        to look. The keys are the most sensitive file this app touches and
        SECURITY.md promises they are only read, so the copy exists for the
        length of one conversion and is deleted afterwards, including when the
        conversion fails.

        A keys file the user pointed at directly is left alone: it is theirs,
        it was already there, and deleting it would destroy it.
    """
    target = workdir / "keys.txt"
    if keys_file.resolve() == target.resolve():
        yield
        return

    workdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(keys_file, target)
    try:
        yield
    finally:
        # Leaving it behind is the thing being fixed, but failing a conversion
        # over a cleanup error would be perverse, so a locked file is tolerated.
        with suppress(OSError):
            target.unlink(missing_ok=True)


def run_nsz_cli(args: list[str]) -> int:
    sys.argv = ["nsz", *args]
    try:
        # Imported here on purpose: nsz pulls in multiprocessing and warns
        # about missing keys at import time, and this process only exists to
        # run it. Nothing else should pay that cost.
        from nsz import main as nsz_main

        nsz_main()
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        return 0 if code is None else 1
    except Exception as exc:  # noqa: BLE001 - surface tool errors to the caller
        print(f"nsz failed: {exc}", file=sys.stderr)
        return 1
    return 0
