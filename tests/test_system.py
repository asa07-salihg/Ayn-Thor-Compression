"""Running an external tool and reading its output back.

The interesting part is the reading. chdman, DolphinTool and maxcso all redraw
their progress with a carriage return and send no newline until the very end,
so anything line-buffered delivers the whole run as one line after the fact and
the progress bar never moves. These run real subprocesses and check that each
update arrives while the process is still going.
"""

from __future__ import annotations

import sys

from aynthor.core.system import run_tool


def python_writing(script: str) -> list[str]:
    """Run a snippet of Python as a tool and collect the lines it produced."""
    seen: list[str] = []
    run_tool(sys.executable, ["-c", script], on_output=seen.append)
    return seen


def test_carriage_returns_are_separate_updates():
    """This is what makes a progress bar move rather than jump to 100."""
    lines = python_writing(
        "import sys\n"
        "for pct in (10, 55, 99):\n"
        "    sys.stdout.write(f'Compressing, {pct}% complete\\r')\n"
        "    sys.stdout.flush()\n"
        "sys.stdout.write('Done\\n')"
    )
    assert lines == ["Compressing, 10% complete", "Compressing, 55% complete",
                     "Compressing, 99% complete", "Done"]


def test_newlines_are_lines_too():
    assert python_writing("print('one'); print('two')") == ["one", "two"]


def test_a_final_line_with_no_terminator_is_not_lost():
    assert python_writing("import sys; sys.stdout.write('no newline here')") == [
        "no newline here"]


def test_blank_output_produces_no_lines():
    assert python_writing("pass") == []


def test_stderr_is_merged_so_errors_reach_the_log():
    lines = python_writing("import sys; sys.stderr.write('it failed\\n')")
    assert "it failed" in lines


def test_output_is_also_returned_as_one_string():
    result = run_tool(sys.executable, ["-c", "print('a'); print('b')"], on_output=lambda _l: None)
    assert result.stdout == "a\nb"


def test_the_exit_code_comes_back():
    result = run_tool(sys.executable, ["-c", "raise SystemExit(3)"], on_output=lambda _l: None)
    assert result.returncode == 3


def test_bytes_that_are_not_utf8_do_not_crash_the_run():
    """A tool printing a filename in the system code page must not kill a batch."""
    result = run_tool(
        sys.executable,
        ["-c", "import sys; sys.stdout.buffer.write(b'caf\\xe9 done\\n')"],
        on_output=lambda _l: None,
    )
    assert result.returncode == 0
    assert "done" in result.stdout


def test_a_split_multibyte_character_is_reassembled():
    """Chunk boundaries fall wherever they fall; a decoder that is not
    incremental turns a split character into two replacement marks."""
    script = (
        "import sys, time\n"
        "data = 'ü' * 20000 + '\\n'\n"
        "sys.stdout.buffer.write(data.encode('utf-8'))\n"
    )
    result = run_tool(sys.executable, ["-c", script], on_output=lambda _l: None)
    assert "\ufffd" not in result.stdout
    assert result.stdout.count("ü") == 20000


def test_stop_ends_the_running_tool():
    import threading
    import time

    from aynthor.core import system

    system.clear_tool_stop()
    holder: dict = {}

    def work() -> None:
        holder["result"] = run_tool(
            sys.executable, ["-c", "import time; time.sleep(30)"],
            on_output=lambda _line: None,
        )

    thread = threading.Thread(target=work)
    thread.start()
    try:
        deadline = time.monotonic() + 2
        while system._tool_process is None and time.monotonic() < deadline:
            time.sleep(0.02)
        system.stop_running_tool()
        thread.join(3)
        assert not thread.is_alive()
        assert holder["result"].returncode != 0
    finally:
        system.clear_tool_stop()


def test_without_a_callback_it_still_captures_everything():
    result = run_tool(sys.executable, ["-c", "print('quiet')"])
    assert result.returncode == 0
    assert "quiet" in result.stdout
