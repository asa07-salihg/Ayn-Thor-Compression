"""Download every converter tool without opening the interface.

Why
    Needed in three places where no window exists: a fresh checkout, a CI
    build, and a machine where the app was installed but its Tools dialog
    cannot reach the network.

Usage
    python scripts/fetch_tools.py

    Exits non-zero if anything failed, so CI notices.

Used by
    Developers, and .github/workflows/release.yml.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aynthor.core.tools.manager import ToolsManager
from aynthor.core.tools.manifest import INSTALLABLE


def main() -> int:
    manager = ToolsManager()
    print(f"Installing into {manager.tools_root}\n")

    errors = manager.install_all(progress=print)

    print("\nStatus")
    status = manager.status()
    labels = {spec.key: spec.label for spec in INSTALLABLE}
    for key, ready in status.items():
        print(f"  {'ok     ' if ready else 'missing'}  {labels[key]}")

    unverified = manager.unverified()
    if unverified:
        print("\nInstalled without a checksum (upstream publishes none):")
        for label in unverified:
            print(f"  {label}")

    if errors:
        print("\nFailures")
        for error in errors:
            print(f"  {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
