"""Windows 11 styling: system accent, system light/dark, Fluent surfaces.

Why
    This is a Windows utility, and it should look like one rather than like a
    web page rendered in Qt. That means three things Qt will not do on its own:

    * Take the accent colour from the system. Windows stores an eight-entry
      accent palette in the registry, and Fluent uses a different entry for
      light and dark themes, because the one that reads well on white is
      unreadable on near-black. Both are read here, and the text colour on top
      of each is chosen by luminance rather than assumed.
    * Follow the system light/dark setting, and change with it, unless the user
      has picked one explicitly.
    * Use Fluent's surface layers and radii. Fluent is not flat: a page sits on
      one fill, cards sit on a lighter one, and controls on a lighter one
      still, separated by hairlines rather than shadows. Radii are 4 for
      controls and 8 for cards, and getting that wrong is what makes a Qt app
      look like a Qt app.

    Everything falls back to sensible constants off Windows, so the interface
    is still usable when developing on Linux.

Used by
    `app.run`, `ui.main_window` (the View menu), and any widget that needs a
    status colour.

Reference
    Fluent colour roles and layering:
    https://learn.microsoft.com/windows/apps/design/style/color
    Accent palette layout in the registry:
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent
"""

from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QWidget

ASSETS = Path(__file__).resolve().parent / "assets"


class Mode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


# Windows 11's own defaults, used when the registry cannot be read.
_DEFAULT_ACCENT_LIGHT = "#005fb8"   # AccentDark1: readable on white
_DEFAULT_ACCENT_DARK = "#60cdff"    # AccentLight2: readable on near-black


def _relative_luminance(color: QColor) -> float:
    def channel(value: float) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def _text_on(color: str) -> str:
    """Black or white, whichever is readable on this accent."""
    return "#000000" if _relative_luminance(QColor(color)) > 0.45 else "#ffffff"


def system_accents() -> tuple[str, str]:
    """(accent for light theme, accent for dark theme) from the system.

    The palette is eight RGBA entries, lightest first:
        light3, light2, light1, accent, dark1, dark2, dark3, black
    Windows uses dark1 on light backgrounds and light2 on dark ones.
    """
    if sys.platform != "win32":
        return _DEFAULT_ACCENT_LIGHT, _DEFAULT_ACCENT_DARK
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
        )
        with key:
            palette, _ = winreg.QueryValueEx(key, "AccentPalette")
        if len(palette) < 32:
            raise ValueError("accent palette too short")

        def entry(index: int) -> str:
            offset = index * 4
            r, g, b = palette[offset], palette[offset + 1], palette[offset + 2]
            return f"#{r:02x}{g:02x}{b:02x}"

        return entry(4), entry(1)
    except (OSError, ValueError, ImportError):
        return _DEFAULT_ACCENT_LIGHT, _DEFAULT_ACCENT_DARK


def system_prefers_dark() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        with key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except (OSError, ImportError):
        return True


# Fluent's solid fills. Layered, not flat: page, then card, then control.
_LIGHT = {
    "page":        "#f3f3f3",
    "card":        "#ffffff",
    "cardAlt":     "#fafafa",
    "control":     "#fdfdfd",
    "controlHover": "#f5f5f5",
    "controlPress": "#f0f0f0",
    "subtleHover": "#eaeaea",
    "stroke":      "#e2e2e2",
    "strokeStrong": "#cfcfcf",
    "divider":     "#ebebeb",
    "text":        "#1b1b1b",
    "textSecond":  "#5d5d5d",
    "textThird":   "#8f8f8f",
    "ok":          "#0f7b0f",
    "warn":        "#9d5d00",
    "error":       "#c42b1c",
    "dropIdle":    "#c9c9c9",
}

_DARK = {
    "page":        "#202020",
    "card":        "#2b2b2b",
    "cardAlt":     "#272727",
    "control":     "#2d2d2d",
    "controlHover": "#323232",
    "controlPress": "#282828",
    "subtleHover": "#383838",
    "stroke":      "#383838",
    "strokeStrong": "#4a4a4a",
    "divider":     "#303030",
    "text":        "#ffffff",
    "textSecond":  "#cfcfcf",
    "textThird":   "#8a8a8a",
    "ok":          "#6ccb5f",
    "warn":        "#fce100",
    "error":       "#ff99a4",
    "dropIdle":    "#4a4a4a",
}

FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", "DejaVu Sans", sans-serif'
DISPLAY_FONT = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI", sans-serif'
MONO = '"Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace'

# Fluent: 4 on controls, 8 on cards and dialogs. Nested corners get the
# difference, not the same value.
RADIUS_CONTROL = 4
RADIUS_CARD = 8

_tokens: dict[str, str] = dict(_DARK)
_is_dark = True


def token(name: str) -> str:
    """A colour by name. Unknown names raise rather than returning a default:
    a widget silently painted the wrong colour is harder to notice than a
    crash, and `tests/test_theme_tokens.py` checks every call site."""
    try:
        return _tokens[name]
    except KeyError:
        raise KeyError(
            f"No theme token named {name!r}. Available: {', '.join(sorted(_tokens))}"
        ) from None


def color(name: str) -> QColor:
    return QColor(token(name))


def is_dark() -> bool:
    return _is_dark


_QSS = """
* {{ font-family: {font}; font-size: 14px; }}
QWidget {{ color: {text}; }}
QMainWindow, QDialog {{ background: {page}; }}

QLabel[role="title"] {{ font-family: {display}; font-size: 20px; font-weight: 600; }}
QLabel[role="subtitle"] {{ font-size: 12px; color: {textSecond}; }}
QLabel[role="second"] {{ color: {textSecond}; }}
QLabel[role="third"] {{ color: {textThird}; font-size: 12px; }}
QLabel[role="warn"] {{ color: {warn}; }}
QLabel[role="drop"] {{ font-size: 15px; color: {textSecond}; }}
/* The per-format panels set this by object name, from before roles existed. */
QLabel#hintLabel {{ color: {textSecond}; font-size: 12px; }}

/* ---- cards ------------------------------------------------------------ */
QFrame[role="card"] {{
    background: {card};
    border: 1px solid {stroke};
    border-radius: {rCard}px;
}}
QFrame[role="dropzone"] {{
    background: {cardAlt};
    border: 1px dashed {dropIdle};
    border-radius: {rCard}px;
}}
QFrame[role="dropzone"][active="true"] {{
    border: 1px dashed {accent};
    background: {controlHover};
}}
QFrame[role="bar"] {{
    background: {card};
    border-top: 1px solid {stroke};
}}

/* ---- buttons ---------------------------------------------------------- */
QPushButton {{
    background: {control};
    border: 1px solid {stroke};
    border-bottom: 1px solid {strokeStrong};
    border-radius: {rControl}px;
    padding: 5px 14px;
    min-height: 20px;
}}
QPushButton:hover {{ background: {controlHover}; }}
QPushButton:pressed {{ background: {controlPress}; color: {textSecond};
                       border-bottom-color: {stroke}; }}
QPushButton:disabled {{ background: {cardAlt}; color: {textThird};
                        border-color: {divider}; }}

QPushButton[accent="true"] {{
    background: {accent}; border: 1px solid {accent};
    border-bottom: 1px solid {accentDeep};
    color: {accentText}; font-weight: 600; padding: 5px 22px;
}}
QPushButton[accent="true"]:hover {{ background: {accentHover}; border-color: {accentHover}; }}
QPushButton[accent="true"]:pressed {{ background: {accentPress}; border-color: {accentPress}; }}
QPushButton[accent="true"]:disabled {{ background: {cardAlt}; border-color: {divider};
                                       color: {textThird}; }}

QPushButton[subtle="true"] {{
    background: transparent; border: 1px solid transparent;
    color: {text}; padding: 5px 11px;
}}
QPushButton[subtle="true"]:hover {{ background: {subtleHover}; }}
QPushButton[subtle="true"]:pressed {{ background: {controlPress}; color: {textSecond}; }}

/* ---- inputs ----------------------------------------------------------- */
QLineEdit, QComboBox, QSpinBox {{
    background: {control};
    border: 1px solid {stroke};
    border-bottom: 1px solid {strokeStrong};
    border-radius: {rControl}px;
    padding: 5px 9px;
    selection-background-color: {accent};
    selection-color: {accentText};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ background: {controlHover}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-bottom: 2px solid {accent};
                                                    padding-bottom: 4px; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: {cardAlt}; color: {textThird}; border-color: {divider}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{
    background: {card}; border: 1px solid {stroke}; border-radius: {rControl}px;
    padding: 3px; outline: none;
    selection-background-color: {subtleHover}; selection-color: {text}; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding: 2px 8px;
                                     border-radius: {rInner}px; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid {strokeStrong};
    border-radius: {rInner}px; background: {control}; }}
QCheckBox::indicator:hover {{ background: {controlHover}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};
                                image: url("{check}"); }}
QCheckBox:disabled {{ color: {textThird}; }}

/* ---- table ------------------------------------------------------------ */
QTableView {{
    background: {card};
    alternate-background-color: {cardAlt};
    border: none;
    gridline-color: transparent;
    outline: none;
    selection-background-color: {subtleHover};
    selection-color: {text};
}}
QTableView::item {{ padding: 4px 10px; border: none;
                    border-bottom: 1px solid {divider}; }}
QHeaderView {{ background: {card}; }}
QHeaderView::section {{
    background: {card}; color: {textSecond}; font-size: 12px;
    border: none; border-bottom: 1px solid {stroke};
    padding: 7px 10px; }}
QTableCornerButton::section {{ background: {card}; border: none;
                               border-bottom: 1px solid {stroke}; }}

/* ---- lists (settings categories) -------------------------------------- */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 8px 12px; border-radius: {rControl}px;
                     color: {text}; margin: 1px 0; }}
QListWidget::item:hover {{ background: {subtleHover}; }}
QListWidget::item:selected {{ background: {subtleHover}; color: {text};
                              border-left: 3px solid {accent}; padding-left: 9px; }}
QListWidget::item:disabled {{ color: {textThird}; }}

/* ---- log -------------------------------------------------------------- */
QPlainTextEdit#log {{
    background: {cardAlt}; border: none; border-top: 1px solid {stroke};
    font-family: {mono}; font-size: 12px; color: {textSecond}; padding: 6px 10px; }}

/* ---- progress --------------------------------------------------------- */
QProgressBar {{ border: none; border-radius: 2px; background: {subtleHover};
                max-height: 4px; min-height: 4px; text-align: center;
                color: transparent; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}

/* ---- menus ------------------------------------------------------------ */
QMenu {{ background: {card}; border: 1px solid {stroke};
         border-radius: {rCard}px; padding: 4px; }}
QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: {rControl}px; }}
QMenu::item:selected {{ background: {subtleHover}; }}
QMenu::separator {{ height: 1px; background: {divider}; margin: 4px 8px; }}

/* ---- scrollbars ------------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle {{ background: {strokeStrong}; border-radius: 3px; }}
QScrollBar::handle:vertical {{ min-height: 28px; width: 6px; }}
QScrollBar::handle:horizontal {{ min-width: 28px; height: 6px; }}
QScrollBar::handle:hover {{ background: {textThird}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QToolTip {{ background: {card}; color: {text}; border: 1px solid {stroke};
            padding: 5px 9px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QSplitter::handle {{ background: transparent; }}
"""


def _shift(hex_color: str, amount: int) -> str:
    c = QColor(hex_color)
    return QColor(
        max(0, min(255, c.red() + amount)),
        max(0, min(255, c.green() + amount)),
        max(0, min(255, c.blue() + amount)),
    ).name()


def build_stylesheet(tokens: dict[str, str]) -> str:
    return _QSS.format(
        font=FONT, display=DISPLAY_FONT, mono=MONO,
        rControl=RADIUS_CONTROL, rCard=RADIUS_CARD, rInner=RADIUS_CONTROL - 2,
        chevron=(ASSETS / "chevron-down.svg").as_posix(),
        check=(ASSETS / "check.svg").as_posix(),
        **tokens,
    )


def _palette(tokens: dict[str, str]) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: tokens["page"],
        QPalette.ColorRole.WindowText: tokens["text"],
        QPalette.ColorRole.Base: tokens["card"],
        QPalette.ColorRole.AlternateBase: tokens["cardAlt"],
        QPalette.ColorRole.Text: tokens["text"],
        QPalette.ColorRole.Button: tokens["control"],
        QPalette.ColorRole.ButtonText: tokens["text"],
        QPalette.ColorRole.ToolTipBase: tokens["card"],
        QPalette.ColorRole.ToolTipText: tokens["text"],
        QPalette.ColorRole.Highlight: tokens["accent"],
        QPalette.ColorRole.HighlightedText: tokens["accentText"],
        QPalette.ColorRole.PlaceholderText: tokens["textThird"],
        QPalette.ColorRole.Link: tokens["accent"],
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    disabled = QPalette.ColorGroup.Disabled
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText,
                 QPalette.ColorRole.WindowText):
        palette.setColor(disabled, role, QColor(tokens["textThird"]))
    return palette


def resolve(mode: Mode) -> bool:
    """Should the dark palette be used for this mode?"""
    if mode == Mode.LIGHT:
        return False
    if mode == Mode.DARK:
        return True
    return system_prefers_dark()


def apply_theme(app: QApplication, mode: Mode = Mode.SYSTEM) -> None:
    """Apply the theme. Safe to call while the window is open.

    Qt does not re-resolve a palette a widget has already inherited, so every
    live widget is repolished. Without that, the tables and the log keep the
    previous theme's background while everything around them changes.
    """
    global _tokens, _is_dark
    _is_dark = resolve(mode)

    accent_light, accent_dark = system_accents()
    accent = accent_dark if _is_dark else accent_light

    _tokens = dict(_DARK if _is_dark else _LIGHT)
    _tokens["accent"] = accent
    _tokens["accentText"] = _text_on(accent)
    # Fluent's accent button gets lighter on hover and darker when pressed, in
    # both themes; the direction of "lighter" is what flips.
    _tokens["accentHover"] = _shift(accent, 14 if _is_dark else 18)
    _tokens["accentPress"] = _shift(accent, -18 if _is_dark else -22)
    _tokens["accentDeep"] = _shift(accent, -34)

    app.setStyle("Fusion")
    app.setPalette(_palette(_tokens))
    app.setStyleSheet(build_stylesheet(_tokens))

    style = app.style()
    for widget in app.allWidgets():
        widget.setPalette(_palette(_tokens))
        style.unpolish(widget)
        style.polish(widget)
        widget.update()


def restyle(widget: QWidget) -> None:
    """Re-evaluate a widget's stylesheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def app_icon() -> QIcon:
    return QIcon(str(ASSETS / "app.ico"))
