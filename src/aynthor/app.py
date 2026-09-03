"""Start the Qt application.

Why
    Kept separate from `__main__` so the `--nsz-cli` passthrough can run
    without importing Qt at all. A frozen build spawns that child process for
    every Switch job, and loading PySide6 in it would cost a second and around
    a hundred megabytes of memory each time for a window that never appears.

Used by
    `__main__.main`.

Reference
    Why nsz runs out of process: `core.nsz_runner`.
"""

from __future__ import annotations

import sys


def run() -> int:
    from aynthor.core.runtime import is_frozen

    if is_frozen():
        # First launch of a fresh install: get the bundled converters out of
        # the temporary extraction directory before anything looks for them.
        from aynthor.core.runtime import ensure_tools_extracted

        ensure_tools_extracted()

    from PySide6.QtWidgets import QApplication

    from aynthor import __version__
    from aynthor.ui import state
    from aynthor.ui.main_window import MainWindow
    from aynthor.ui.theme import app_icon, apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Ayn Thor Compression")
    app.setOrganizationName(state.ORGANISATION)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())
    apply_theme(app, state.load_mode())

    window = MainWindow()
    window.show()
    return app.exec()
