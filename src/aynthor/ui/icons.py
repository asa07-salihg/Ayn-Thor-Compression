"""Line icons drawn in the theme's colours, and the app's logo.

Text-only buttons gave every control the same weight, so someone scanning
the window for where to add games had to read every label. One small line
icon per action fixes that without turning the window into a toolbar.

Each icon is an SVG whose strokes say `currentColor`. That word is
replaced with a theme colour before the SVG is drawn, so one file serves
the light theme, the dark theme and the accent button, and the result is
sharp at any display scaling. Drawing goes through Qt's SVG image plugin,
the same one the stylesheet's check mark already needs, so the exe ships
nothing new for it.

The icons: `ui/assets/icons/*.svg`, 24 by 24, 1.75 px round strokes.
The logo: `ui/assets/logo.svg`, and `scripts/make_icons.py` for app.ico.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QIcon, QImageReader, QPixmap

from aynthor.ui import theme
from aynthor.ui.theme import ASSETS

ICONS = ASSETS / "icons"
_ICON_SIZES = (16, 20, 24, 32, 40, 48)
# Below this the large logo's squinting eyes read as an X, so the simpler face is drawn.
_SMALL_LOGO_LIMIT = 40


# PNG bytes, never a Qt object. This cache lives until the interpreter exits,
# after the QApplication is gone, and freeing a QPixmap or QImage then
# segfaults on Linux. The pixmap is built from these bytes only while the
# application still exists.
@lru_cache(maxsize=512)
def _png(path: str, colour: str, size: int) -> bytes:
    data = Path(path).read_bytes()
    if colour:
        data = data.replace(b"currentColor", colour.encode("ascii"))
    source = QBuffer()
    source.setData(QByteArray(data))
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source, QByteArray(b"svg"))
    reader.setScaledSize(QSize(size, size))
    image = reader.read()
    out = QBuffer()
    out.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(out, "PNG")
    return bytes(out.data())


def _render(path: str, colour: str, size: int) -> QPixmap:
    pixmap = QPixmap()
    pixmap.loadFromData(_png(path, colour, size), "PNG")
    return pixmap


def names() -> list[str]:
    """Every icon there is a file for."""
    return sorted(path.stem for path in ICONS.glob("*.svg"))


def _svg(name: str) -> str:
    """The file for an icon. A misspelt name raises instead of drawing nothing,
    so the smoke tests that build each window catch it."""
    path = ICONS / f"{name}.svg"
    if not path.is_file():
        raise FileNotFoundError(f"No icon named {name!r}. Available: {', '.join(names())}")
    return str(path)


def icon(name: str, colour: str = "text") -> QIcon:
    """An icon for a button. `colour` is a theme token; the disabled state
    uses the faint text colour, as a disabled label does."""
    path = _svg(name)
    normal = theme.token(colour)
    faint = theme.token("textThird")
    result = QIcon()
    for size in _ICON_SIZES:
        result.addPixmap(_render(path, normal, size), QIcon.Mode.Normal)
        result.addPixmap(_render(path, faint, size), QIcon.Mode.Disabled)
    return result


def pixmap(name: str, colour: str, size: int, ratio: float = 1.0) -> QPixmap:
    """An icon for a label, drawn at the screen's scale so it is not blurred."""
    drawn = QPixmap(_render(_svg(name), theme.token(colour), round(size * ratio)))
    drawn.setDevicePixelRatio(ratio)
    return drawn


def logo(size: int, ratio: float = 1.0) -> QPixmap:
    source = ASSETS / ("logo.svg" if size >= _SMALL_LOGO_LIMIT else "logo-small.svg")
    drawn = QPixmap(_render(str(source), "", round(size * ratio)))
    drawn.setDevicePixelRatio(ratio)
    return drawn
