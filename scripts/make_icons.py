"""Build the application icon from the SVG logo.

Windows wants an .ico holding every size it might show: 16 px in a title bar,
32 px on the taskbar, 256 px in Explorer's large view. The logo is a game card
squashed between two bars and squinting about it, and those squinting eyes
turn into an X below 40 px. So there are two drawings: `logo.svg` for the
large sizes, and `logo-small.svg`, with plain dashes for eyes, for the small
ones. This renders both and packs them into
`app.ico`, which PyInstaller embeds in the exe and the window uses as its
icon. It also writes the logo the README shows.

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


def render(svg: Path, size: int) -> bytes:
    """The SVG drawn at `size` pixels, as PNG bytes."""
    from PySide6.QtCore import QBuffer, QIODevice, QSize
    from PySide6.QtGui import QImageReader

    reader = QImageReader(str(svg), b"svg")
    reader.setScaledSize(QSize(size, size))
    image = reader.read()
    if image.isNull():
        raise SystemExit(f"Could not render {svg.name}: {reader.errorString()}")
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
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


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    _application = QGuiApplication(sys.argv[:1])  # image plugins need one

    images = [(size, render(ASSETS / "logo-small.svg", size)) for size in SMALL_SIZES]
    images += [(size, render(ASSETS / "logo.svg", size)) for size in LARGE_SIZES]
    ico = ASSETS / "app.ico"
    ico.write_bytes(pack_ico(images))

    DOCS.mkdir(parents=True, exist_ok=True)
    logo = DOCS / "logo.png"
    logo.write_bytes(render(ASSETS / "logo.svg", 256))

    print(f"{ico.relative_to(ROOT)}  ({len(images)} sizes, {ico.stat().st_size} bytes)")
    print(f"{logo.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
