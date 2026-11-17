"""Build the application icon and the README / social images from the SVG logo.

Windows wants an .ico holding every size it might show: 16 px in a title bar,
32 px on the taskbar, 256 px in Explorer's large view. The logo is a game card
squashed between two bars and squinting about it, and those squinting eyes
turn into an X below 40 px. So there are two drawings: `logo.svg` for the
large sizes, and `logo-small.svg`, with plain dashes for eyes, for the small
ones. This renders both and packs them into
`app.ico`, which PyInstaller embeds in the exe and the window uses as its
icon.

It also writes the images the GitHub page uses:

* `docs/images/logo.png` for the README mark
* `docs/images/banner.png` for the top of the README
* `docs/images/social-preview.png` for the repository link preview

Run `python scripts/make_icons.py` after editing either SVG, and commit the
files it writes.

ICO layout (ICONDIR, ICONDIRENTRY, PNG payloads):
https://learn.microsoft.com/en-us/previous-versions/ms997538(v=msdn.10)
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "aynthor" / "ui" / "assets"
DOCS = ROOT / "docs" / "images"

SMALL_SIZES = (16, 20, 24, 32)
LARGE_SIZES = (40, 48, 64, 128, 256)

# Brand colours from logo.svg
BG = (22, 18, 16)
ACCENT = (238, 90, 36)
TITLE = (255, 248, 240)
SUBTITLE = (255, 210, 180)


def render(svg: Path, size: int):
    """The SVG drawn at `size` pixels, as a QImage."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImageReader

    reader = QImageReader(str(svg), b"svg")
    reader.setScaledSize(QSize(size, size))
    image = reader.read()
    if image.isNull():
        raise SystemExit(f"Could not render {svg.name}: {reader.errorString()}")
    return image


def png_bytes(image) -> bytes:
    from PySide6.QtCore import QBuffer, QIODevice

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise SystemExit("Could not encode PNG")
    return bytes(buffer.data())


def pack_ico(images: list[tuple[int, bytes]]) -> bytes:
    """An .ico whose entries are PNG payloads, which Windows has read since Vista."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 means 256 in an ICONDIRENTRY
        entries += struct.pack(
            "<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(payload))
        payload += png
    return header + entries + payload


def _qcolor(rgb: tuple[int, int, int], alpha: int = 255):
    from PySide6.QtGui import QColor

    return QColor(rgb[0], rgb[1], rgb[2], alpha)


_FONT_FAMILIES: tuple[str, str] | None = None


def _load_fonts() -> tuple[str, str]:
    """Family names for regular and bold text, loaded from Windows font files."""
    global _FONT_FAMILIES
    if _FONT_FAMILIES is not None:
        return _FONT_FAMILIES

    from PySide6.QtGui import QFontDatabase

    fonts = Path(r"C:\Windows\Fonts")
    regular_id = QFontDatabase.addApplicationFont(str(fonts / "segoeui.ttf"))
    bold_id = QFontDatabase.addApplicationFont(str(fonts / "segoeuib.ttf"))
    if regular_id < 0 or bold_id < 0:
        raise SystemExit("Could not load Segoe UI from C:\\Windows\\Fonts")
    regular = QFontDatabase.applicationFontFamilies(regular_id)[0]
    bold = QFontDatabase.applicationFontFamilies(bold_id)[0]
    _FONT_FAMILIES = (regular, bold)
    return _FONT_FAMILIES


def compose_card(
    width: int,
    height: int,
    logo_size: int,
    title: str,
    subtitle: str,
    title_px: int,
    subtitle_px: int,
):
    """Logo on the left, title and subtitle on the right, on the dark background."""
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import (
        QFont,
        QImage,
        QPainter,
        QPainterPath,
        QRadialGradient,
    )

    regular_family, bold_family = _load_fonts()

    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(_qcolor(BG))

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    left_glow = QRadialGradient(QPointF(width * 0.22, height * 0.5), width * 0.45)
    left_glow.setColorAt(0.0, _qcolor(ACCENT, 55))
    left_glow.setColorAt(1.0, _qcolor(ACCENT, 0))
    painter.fillRect(image.rect(), left_glow)

    right_glow = QRadialGradient(QPointF(width * 0.85, height * 0.35), width * 0.4)
    right_glow.setColorAt(0.0, _qcolor(ACCENT, 28))
    right_glow.setColorAt(1.0, _qcolor(ACCENT, 0))
    painter.fillRect(image.rect(), right_glow)

    logo = render(ASSETS / "logo.svg", logo_size)
    left = int(width * 0.07)
    top = (height - logo_size) // 2
    clip = QPainterPath()
    radius = max(12.0, logo_size / 5.0)
    clip.addRoundedRect(QRectF(left, top, logo_size, logo_size), radius, radius)
    painter.setClipPath(clip)
    painter.drawImage(left, top, logo)
    painter.setClipping(False)

    title_font = QFont(bold_family)
    title_font.setPixelSize(title_px)
    title_font.setBold(True)
    sub_font = QFont(regular_family)
    sub_font.setPixelSize(subtitle_px)

    text_x = left + logo_size + int(width * 0.035)
    text_y = top + int(logo_size * 0.28)
    painter.setPen(_qcolor(TITLE))
    painter.setFont(title_font)
    painter.drawText(text_x, text_y, title)

    painter.setPen(_qcolor(SUBTITLE))
    painter.setFont(sub_font)
    painter.drawText(text_x, text_y + title_px + int(height * 0.06), subtitle)

    painter.fillRect(0, height - 6, width, 6, _qcolor(ACCENT))
    painter.end()
    return image


def write_docs_images() -> list[Path]:
    DOCS.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    logo = DOCS / "logo.png"
    logo.write_bytes(png_bytes(render(ASSETS / "logo.svg", 256)))
    written.append(logo)

    banner = DOCS / "banner.png"
    banner.write_bytes(png_bytes(compose_card(
        1280, 400, 180,
        "Ayn Thor Compression",
        "Shrink ROMs. Send them to your handheld.",
        title_px=54, subtitle_px=26,
    )))
    written.append(banner)

    social = DOCS / "social-preview.png"
    social.write_bytes(png_bytes(compose_card(
        1280, 640, 220,
        "Ayn Thor Compression",
        "Free Windows app for CHD, RVZ, NSZ, ZCCI and more",
        title_px=64, subtitle_px=30,
    )))
    written.append(social)
    return written


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    _application = QGuiApplication(sys.argv[:1])  # image plugins need one

    images = [(size, png_bytes(render(ASSETS / "logo-small.svg", size))) for size in SMALL_SIZES]
    images += [(size, png_bytes(render(ASSETS / "logo.svg", size))) for size in LARGE_SIZES]
    ico = ASSETS / "app.ico"
    ico.write_bytes(pack_ico(images))
    print(f"{ico.relative_to(ROOT)}  ({len(images)} sizes, {ico.stat().st_size} bytes)")

    for path in write_docs_images():
        print(f"{path.relative_to(ROOT)}  ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
