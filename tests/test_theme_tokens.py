"""Every colour the interface asks for by name has to exist.

Why this exists
    Opening the Tools window crashed with `KeyError: 'textFaint'`. The theme
    had been rewritten and that token renamed, but one call site still used the
    old name. Nothing caught it: the name is a string, the call is on a code
    path that only runs when a particular window opens, and the type checker
    has nothing to check.

    This reads the call sites out of the source and compares them against the
    tokens the theme actually defines, so a rename that misses one fails here
    instead of in front of a user. It needs no Qt, so it runs in the fast suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "src" / "aynthor" / "ui"
THEME = UI / "theme.py"

_CALL = re.compile(r'theme\.(?:color|token)\(\s*"(\w+)"')
_TERNARY = re.compile(r'theme\.(?:color|token)\(\s*"(\w+)"\s+if\s+.+?\s+else\s+"(\w+)"')
_DEFINED = re.compile(r'"(\w+)":\s*"#')


def defined_tokens() -> set[str]:
    text = THEME.read_text(encoding="utf-8")
    light = text[text.index("_LIGHT = {"):text.index("_DARK = {")]
    dark = text[text.index("_DARK = {"):text.index("FONT = ")]
    names = set(_DEFINED.findall(light)) & set(_DEFINED.findall(dark))
    # Added at apply time from the system accent rather than written literally.
    return names | {"accent", "accentText", "accentHover", "accentPress", "accentDeep"}


def used_tokens() -> dict[str, list[str]]:
    """Token name -> the files that ask for it."""
    used: dict[str, list[str]] = {}
    for path in sorted(UI.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        names = set(_CALL.findall(text))
        for first, second in _TERNARY.findall(text):
            names.update((first, second))
        for name in names:
            used.setdefault(name, []).append(path.name)
    return used


def test_light_and_dark_define_the_same_tokens():
    """A token in one theme and not the other is a crash waiting for a toggle."""
    text = THEME.read_text(encoding="utf-8")
    light = set(_DEFINED.findall(text[text.index("_LIGHT = {"):text.index("_DARK = {")]))
    dark = set(_DEFINED.findall(text[text.index("_DARK = {"):text.index("FONT = ")]))
    assert light == dark


def test_every_token_asked_for_by_name_exists():
    available = defined_tokens()
    unknown = {name: files for name, files in used_tokens().items() if name not in available}
    assert unknown == {}, (
        f"unknown theme tokens: {unknown}\navailable: {sorted(available)}")


def test_every_token_in_the_stylesheet_exists():
    """The stylesheet is formatted with the token dict, so a stray placeholder
    is a KeyError at startup rather than at the moment a window opens."""
    text = THEME.read_text(encoding="utf-8")
    sheet = text[text.index('_QSS = """'):text.index('def _shift(')]
    placeholders = set(re.findall(r"\{(\w+)\}", sheet))
    supplied = defined_tokens() | {
        "font", "display", "mono", "rControl", "rCard", "rInner", "chevron", "check",
    }
    assert placeholders - supplied == set()


@pytest.mark.parametrize("required", ["text", "ok", "warn", "error", "accent"])
def test_the_tokens_other_modules_rely_on_are_present(required):
    assert required in defined_tokens()
