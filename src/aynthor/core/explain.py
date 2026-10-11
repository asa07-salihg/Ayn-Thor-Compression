"""Say what went wrong with a row, in words a first-time user can act on.

Why
    A failed row used to show the converter's own text, such as a tools folder
    path or `[WinError 112] There is not enough space on the disk`, in a log
    that stays hidden until something fails. Someone filling their first card
    needs three things instead: what happened, what to do about it, and a
    button that does it. The original text is kept for bug reports.

    Only failures this app can actually recognise are reworded: the sentence
    every converter shares for a missing program (`converters.base.missing_tool`),
    the missing `prod.keys`, the archive errors `core.unpack` raises, and the
    few Windows errors that a full, locked or busy card produces. Anything else
    is reported as the converter stopping, with its own words underneath.

Used by
    `ui.failure_dialog`, `ui.queue_view` (the Status tooltip).

Reference
    Windows error numbers seen here (5, 19, 32, 112):
    https://learn.microsoft.com/en-us/windows/win32/debug/system-error-codes--0-499-
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Fix(str, Enum):
    """The one action that would most likely make the row work."""

    NONE = "none"
    OPEN_TOOLS = "open_tools"
    CHOOSE_KEYS = "choose_keys"
    OPEN_FOLDER = "open_folder"
    GET_7ZIP = "get_7zip"


@dataclass(frozen=True)
class Explanation:
    summary: str
    advice: str
    fix: Fix = Fix.NONE
    details: str = ""


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    summary: str
    advice: str
    fix: Fix = Fix.NONE


# The marker `missing_tool` writes. Only the text before it names the program.
_MISSING_MARK = " is not installed (looked in "
_MISSING_SUMMARY = "{tool} isn't installed yet."
_MISSING_ADVICE = (
    "It's one of the free programs this app uses to convert files. Open Tools "
    "and press Install missing programs, then press Start again.")

_RULES = (
    _Rule(
        re.compile(r"prod\.keys not found", re.IGNORECASE),
        "Switch games need a prod.keys file from your own Switch.",
        "Choose the file, then press Start again. The app never downloads or "
        "shares it.",
        Fix.CHOOSE_KEYS,
    ),
    _Rule(
        re.compile(r"rar needs full 7-zip|cannot read this rar", re.IGNORECASE),
        "This RAR file needs 7-Zip to open it.",
        "Install 7-Zip from 7-zip.org, then add the file again.",
        Fix.GET_7ZIP,
    ),
    _Rule(
        re.compile(r"\[winerror 112\]|\[errno 28\]|no space left|not enough space",
                   re.IGNORECASE),
        "There isn't enough free space where this game is being saved.",
        "Free up some space on the card or drive, or choose a different place "
        "in Settings, then press Start again.",
        Fix.OPEN_FOLDER,
    ),
    _Rule(
        re.compile(r"\[winerror 3[23]\]|being used by another process", re.IGNORECASE),
        "Another program has this file open.",
        "Close any emulator, file preview or copy that might be using it, then "
        "press Start again.",
    ),
    _Rule(
        re.compile(r"\[winerror (?:5|19)\]|\[errno 13\]|write.protected|"
                   r"permission denied|access is denied", re.IGNORECASE),
        "Windows wouldn't let the app save there.",
        "If it's an SD card, check the small lock switch on its side and slide "
        "it away from Lock. Otherwise make sure the folder isn't read-only.",
    ),
    _Rule(
        re.compile(r"after unpacking|\bis not in \S|unpacked to an empty folder|"
                   r"cannot read \S.*\.(?:zip|7z|rar)\b|crc failed|data error|"
                   r"unexpected end of (?:archive|data)", re.IGNORECASE),
        "The archive couldn't be unpacked.",
        "The download may be damaged or incomplete. Try downloading it again.",
    ),
    _Rule(
        re.compile(r"cannot be unpacked|already a z3ds|open works on", re.IGNORECASE),
        "This file can't be turned into that.",
        "Click the Becomes cell on this row and pick another option.",
    ),
    _Rule(
        re.compile(r"^file not found:", re.IGNORECASE),
        "The original file isn't there any more.",
        "It may have been moved, renamed or deleted after it was added, or its "
        "drive was unplugged. Remove the row and add the file again.",
    ),
)

_GENERIC = _Rule(
    re.compile(""),
    "The conversion stopped with an error.",
    "The details below are what the converter reported. Include them if you "
    "report a problem.",
)


def explain_failure(message: str) -> Explanation:
    """What the user should read instead of `message`, which is kept as details."""
    tool = _missing_tool_name(message)
    if tool:
        return Explanation(
            _MISSING_SUMMARY.format(tool=tool), _MISSING_ADVICE, Fix.OPEN_TOOLS, message)
    for rule in _RULES:
        if rule.pattern.search(message):
            return Explanation(rule.summary, rule.advice, rule.fix, message)
    return Explanation(_GENERIC.summary, _GENERIC.advice, _GENERIC.fix, message)


def all_wording() -> list[str]:
    """Every sentence this module can show, so tests can read them all."""
    texts = [_MISSING_SUMMARY, _MISSING_ADVICE, _GENERIC.summary, _GENERIC.advice]
    for rule in _RULES:
        texts += [rule.summary, rule.advice]
    return texts


def _missing_tool_name(message: str) -> str:
    head, found, _ = message.partition(_MISSING_MARK)
    if not found:
        return ""
    lines = head.splitlines() or [""]
    # A caller may prefix the converter's sentence ("Could not unpack: ..."),
    # and no program name contains ": ".
    return lines[-1].rsplit(": ", 1)[-1].strip()
