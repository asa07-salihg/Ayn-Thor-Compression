"""Filesystem locations and the one function that runs an external tool.

Why
    Every converter shells out to a binary, and all of them need the same three
    things: the path to that binary, a subprocess that does not flash a console
    window on Windows, and output streamed back line by line so the progress
    bar can move. `run_tool` is that function. Doing it once here is also what
    keeps `CREATE_NO_WINDOW` from being forgotten in one converter and turning
    a batch run into a strobe light.

    This module is named `system` rather than `platform` because the old name
    shadowed the standard library module it needs to import.

Used by
    Every module under `core.converters`, `core.tools.manager`,
    `core.nsz_runner`, and the prod.keys lookup in `ui.main_window`.

Reference
    CREATE_NO_WINDOW / STARTUPINFO:
    https://docs.python.org/3/library/subprocess.html#subprocess.STARTUPINFO
    prod.keys search order follows nsz's own:
    https://github.com/nicoboss/nsz#requirements
"""

from __future__ import annotations

import codecs
import os
import platform
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from aynthor.core.runtime import app_root, ensure_tools_extracted, is_frozen

IS_WINDOWS = platform.system() == "Windows"

# Tools end a progress update with a carriage return and a finished line with a
# newline; both mean "this line is complete".
_LINE_BREAK = re.compile(r"[\r\n]")
_OUTPUT_CHUNK = 8192


def no_window_kwargs() -> dict:
    """subprocess kwargs that keep a console window from appearing on Windows."""
    if not IS_WINDOWS:
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
    }


def app_data_dir() -> Path:
    """Per-user writable folder, for tools and nsz's staged keys.

    Used when the app lives somewhere the user cannot write to, such as
    Program Files.
    """
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "AynThorCompression"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    """The folder converter binaries are read from.

    Order matters: a tools folder next to the app wins, because that is where a
    portable copy on an SD card keeps its binaries and where the frozen build
    extracts them. Only if that is empty do we fall back to the per-user folder.
    """
    if is_frozen():
        extracted = ensure_tools_extracted()
        if any(extracted.iterdir()):
            return extracted

    local = app_root() / "tools"
    local.mkdir(parents=True, exist_ok=True)
    if any(local.iterdir()):
        return local

    fallback = app_data_dir() / "tools"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def tool_path(name: str) -> Path:
    """Path to a tool. Returns the expected location even when it is missing,
    so callers can report *where* they looked."""
    tools = tools_dir()
    candidates = [tools / f"{name}.exe", tools / name] if IS_WINDOWS else [tools / name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def find_prod_keys() -> Path | None:
    """Locate the user's Switch keys. The app never ships them; see SECURITY.md."""
    for candidate in (
        app_root() / "prod.keys",
        Path.home() / ".switch" / "prod.keys",
        app_data_dir() / "prod.keys",
    ):
        if candidate.is_file():
            return candidate
    return None


def run_tool(
    executable: Path | str,
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    on_output: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a converter and return its result.

    With `on_output`, stdout and stderr are merged and read one character at a
    time. That looks wasteful, and it is deliberate: chdman, DolphinTool and
    maxcso all draw their progress with carriage returns and no newline, so
    line-buffered reading would deliver the entire run as a single line at the
    very end and the progress bar would never move.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    command = [str(executable), *args]

    if on_output is None:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=merged_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            **no_window_kwargs(),
        )

    # Binary pipe, decoded here. `read1` returns whatever has arrived instead
    # of blocking for a full buffer, which is what makes progress work: the
    # tools redraw with a carriage return and never send a newline until the
    # end, so a line-buffered read delivers the entire run in one go and the
    # progress bar never moves. Reading one byte at a time also worked and was
    # what this did first; this is the same behaviour without a syscall per
    # character.
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **no_window_kwargs(),
    )
    assert process.stdout is not None

    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    lines: list[str] = []
    buffer = ""

    def flush(text: str, *, final: bool = False) -> str:
        nonlocal buffer
        buffer += text
        parts = _LINE_BREAK.split(buffer)
        buffer = "" if final else parts.pop()
        for part in parts:
            if part:
                lines.append(part)
                on_output(part)
        return buffer

    while True:
        chunk = process.stdout.read1(_OUTPUT_CHUNK)
        if not chunk:
            break
        flush(decoder.decode(chunk))
    flush(decoder.decode(b"", final=True), final=True)

    process.stdout.close()
    return subprocess.CompletedProcess(command, process.wait(), "\n".join(lines), "")
