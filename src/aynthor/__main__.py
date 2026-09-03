"""Entry point for `python -m aynthor`, the console script and the frozen exe.

Why
    Three things have to happen before anything else, and all of them break in
    ways that are hard to diagnose if they happen later:

    * `freeze_support()` first. nsz uses multiprocessing, and in a frozen build
      every worker re-enters this file. Without this call each worker starts a
      new copy of the application instead of doing its work.
    * The `--nsz-cli` passthrough second, before Qt is imported, so the child
      process stays a command-line tool.
    * Only then the window.

Used by
    `pyproject.toml` (console script), `packaging/AynThorCompression.spec`.

Reference
    https://docs.python.org/3/library/multiprocessing.html#multiprocessing.freeze_support
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()

    args = sys.argv[1:]
    if args and args[0] == "--nsz-cli":
        from aynthor.core.nsz_runner import run_nsz_cli

        return run_nsz_cli(args[1:])

    from aynthor.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
