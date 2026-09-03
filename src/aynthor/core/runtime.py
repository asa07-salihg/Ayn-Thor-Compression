"""Where the app is running from, and how to get the bundled tools out of it.

Why
    A PyInstaller one-file build unpacks itself into a temporary directory that
    is deleted on exit, so the converter binaries cannot simply be run from
    there -- and a user who downloads a tool from the Tools dialog would lose it
    on the next launch. On first run the bundled tools are therefore copied out
    next to the exe, into a `tools/` folder that survives.

Used by
    `core.system.tools_dir` (tool lookup), `app.run` (called once at startup).

Reference
    PyInstaller runtime layout and `sys._MEIPASS`:
    https://pyinstaller.org/en/stable/runtime-information.html
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# Only these are copied out of the bundle. Everything else in the temporary
# directory belongs to Python and Qt and must stay where PyInstaller put it.
_TOOL_SUFFIXES = {".exe", ".dll", ".bin"}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """The folder a user would call "where the app is".

    Frozen: next to the exe. From source: the project root, so a checkout's
    `tools/` and a `prod.keys` dropped beside it are found without configuring
    anything.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


def bundle_dir() -> Path | None:
    """PyInstaller's temporary extraction directory, or None when not frozen."""
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def ensure_tools_extracted() -> Path:
    """Copy bundled tools next to the exe. Returns that `tools/` folder."""
    dest = app_root() / "tools"
    dest.mkdir(parents=True, exist_ok=True)

    bundle = bundle_dir()
    source = (bundle / "tools") if bundle else None
    if source is None or not source.is_dir():
        return dest

    for item in source.iterdir():
        if not item.is_file() or item.suffix.lower() not in _TOOL_SUFFIXES:
            continue
        target = dest / item.name
        # Size is enough to spot a stale copy from an older release, and it
        # avoids hashing several hundred megabytes on every single launch.
        if target.is_file() and target.stat().st_size == item.stat().st_size:
            continue
        shutil.copy2(item, target)
    return dest
