"""Report which pinned converter tools have a newer version upstream.

Why
    Every tool in the manifest is pinned to an exact version with a checksum,
    which is what makes the downloads verifiable. The cost of that is drift:
    nothing tells you when a project has moved on.

    This is the same check the app offers under Tools, in a form that can gate
    a release: it exits non-zero when something is behind.

    It deliberately changes nothing. Bumping a pin means reading the upstream
    changelog for flag changes, downloading the new artifact, recording its
    SHA-256 and editing the manifest by hand. A script that did it
    automatically would be a script that silently ships an untested tool.

Usage
    python scripts/check_tool_updates.py

Used by
    Whoever is cutting a release. See CONTRIBUTING.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aynthor.core.tools.manifest import TOOL_SPECS
from aynthor.core.tools.versions import Status, check_all

_MARK = {
    Status.CURRENT: "current ",
    Status.BEHIND: "BEHIND  ",
    Status.MANUAL: "MANUAL  ",
    Status.UNKNOWN: "ERROR   ",
    Status.PIP: "skip    ",
}


def main() -> int:
    reports = []

    def show(report) -> None:
        line = f"  {_MARK[report.status]} {report.spec.label}: {report.spec.version}"
        if report.detail:
            line += f"  ({report.detail})"
        print(line, flush=True)
        reports.append(report)

    check_all(TOOL_SPECS, on_report=show)

    behind = [r for r in reports if r.status is Status.BEHIND]
    unchecked = [r for r in reports if r.status in (Status.MANUAL, Status.UNKNOWN)]

    print()
    if behind:
        print(f"{len(behind)} behind: {', '.join(r.label for r in behind)}")
        print("Bumping one means reading its changelog for flag changes, downloading the")
        print("new artifact, hashing the extracted file and editing manifest.py by hand.")
    if unchecked:
        print(f"{len(unchecked)} not checked: {', '.join(r.label for r in unchecked)}")
    if not behind and not unchecked:
        print("Everything pinned is the latest release upstream.")
    return 1 if behind else 0


if __name__ == "__main__":
    raise SystemExit(main())
