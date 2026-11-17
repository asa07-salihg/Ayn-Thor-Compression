"""Local tool pins written when Check for updates installs a newer build.

The release ships checksums in `manifest.py`. When the user installs a newer
upstream tool from the Tools window, that build is not in the manifest, so
its hash is stored next to the binaries in `pins.json`. The next open uses
those hashes instead of the older ones in the manifest, which is what stops
the row flipping back to Needs update.
"""

from __future__ import annotations

import json
from typing import Any

from aynthor.core.system import tools_dir
from aynthor.core.tools.manifest import ToolSpec

_PINS_NAME = "pins.json"


def pins_path():
    return tools_dir() / _PINS_NAME


def load_pins() -> dict[str, dict[str, Any]]:
    path = pins_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_pin(key: str, *, version: str, url: str, files: dict[str, str]) -> None:
    pins = load_pins()
    pins[key] = {"version": version, "url": url, "files": dict(files)}
    path = pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def clear_pin(key: str) -> None:
    pins = load_pins()
    if key not in pins:
        return
    del pins[key]
    path = pins_path()
    if not pins:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def effective_version(spec: ToolSpec) -> str:
    pin = load_pins().get(spec.key)
    if pin and pin.get("version"):
        return str(pin["version"])
    return spec.version


def effective_file_hashes(spec: ToolSpec) -> dict[str, str | None]:
    """name -> sha256. A local pin wins over the release manifest."""
    pin = load_pins().get(spec.key)
    if pin and isinstance(pin.get("files"), dict) and pin["files"]:
        return {name: (str(digest) if digest else None) for name, digest in pin["files"].items()}
    return {wanted.name: wanted.sha256 for wanted in spec.files}
