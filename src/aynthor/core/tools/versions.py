"""Ask each converter's project whether the pinned version is still current.

Why
    Every tool is pinned to an exact version with a checksum, which is what
    makes the downloads verifiable. The cost is drift: nothing tells you when a
    project has moved on, and a tool that is two years behind is a tool that is
    missing two years of format fixes.

    So the app can ask. What it will not do is install what it finds, and that
    restraint is the whole point rather than an omission: the guarantee this
    app makes is that nothing reaches `tools/` unless it matches a checksum
    recorded in `manifest`. Downloading a version that is by definition not in
    the manifest would mean running an executable nobody checked. Bumping a pin
    is a change to this repository, made by a person who read the upstream
    changelog for flag changes, and it ships in the next release.

    So this reports, and points at the release page.

Used by
    `ui.tools_dialog` (the Check for updates button),
    `scripts/check_tool_updates.py` (the same check before cutting a release).

Reference
    https://docs.github.com/en/rest/repos/repos#list-repository-tags
    Unauthenticated requests are rate limited to 60 an hour per address, and
    this makes one per tool, so a check costs about eight.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from aynthor.core import net
from aynthor.core.tools.manifest import ToolSpec

_GITHUB_REPO = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)")
_NUMBERS = re.compile(r"\d+")

# Enough to include the newest release of any project here; the API returns
# tags newest first.
_TAGS_PER_PAGE = 30

RATE_LIMITED = (
    "GitHub is rate limiting this address. Unauthenticated checks are capped at "
    "60 an hour and clear on their own; the pinned version is unaffected."
)


class Status(str, Enum):
    CURRENT = "current"
    BEHIND = "behind"
    MANUAL = "manual"      # not hosted somewhere this can ask
    UNKNOWN = "unknown"    # the request failed
    PIP = "pip"            # pip resolves its own version


@dataclass(frozen=True)
class VersionReport:
    spec: ToolSpec
    status: Status
    latest: str = ""
    detail: str = ""

    @property
    def label(self) -> str:
        return self.spec.label


def repository_of(spec: ToolSpec) -> str | None:
    """The `owner/name` this tool is published from, if that is GitHub."""
    for candidate in (spec.url or "", spec.homepage):
        match = _GITHUB_REPO.match(candidate)
        if match:
            return match.group(1).removesuffix(".git")
    return None


def as_numbers(text: str) -> tuple[int, ...]:
    """Comparable form of a version string.

    Deliberately forgiving, because these are other people's tags: `v1.0.6.3`,
    `26.02` and `namDHC v2.0 build` all have to work, and anything with no
    numbers at all sorts lowest so it can never look newer than what is pinned.
    """
    return tuple(int(n) for n in _NUMBERS.findall(text.split("-")[0])) or (0,)


def newer_tags(tags: Iterable[str], pinned: str) -> list[str]:
    current = as_numbers(pinned)
    return sorted({tag for tag in tags if as_numbers(tag) > current}, key=as_numbers)


def fetch_tags(repo: str, timeout: int = net.DEFAULT_TIMEOUT) -> list[str]:
    payload = net.fetch_json(
        f"https://api.github.com/repos/{repo}/tags?per_page={_TAGS_PER_PAGE}",
        timeout=timeout,
    )
    if not isinstance(payload, list):
        raise net.NetworkError(f"{repo} did not return a list of tags.")
    return [str(entry.get("name", "")) for entry in payload if entry.get("name")]


def _explain(exc: net.NetworkError) -> str:
    """Say what a failed check actually means.

    A check that fails is not a problem with the tool, and the raw status line
    reads as if it were: "returned 403 Forbidden" against a public repository
    invites the user to go looking for a permission they do not need. In
    practice a 403 or 429 here is GitHub's hourly limit on requests from one
    address, which nine tools can reach after a few rounds of clicking, and
    which clears on its own.
    """
    if exc.status in (403, 429):
        return RATE_LIMITED
    return str(exc)


def check_one(spec: ToolSpec, timeout: int = net.DEFAULT_TIMEOUT) -> VersionReport:
    if spec.pip_package:
        return VersionReport(spec, Status.PIP,
                             detail=f"pip resolves {spec.pip_package} itself")

    repo = repository_of(spec)
    if repo is None:
        return VersionReport(spec, Status.MANUAL,
                             detail=f"not published through GitHub; see {spec.homepage}")

    try:
        tags = fetch_tags(repo, timeout)
    except net.NetworkError as exc:
        return VersionReport(spec, Status.UNKNOWN, detail=_explain(exc))

    newer = newer_tags(tags, spec.version)
    if not newer:
        return VersionReport(spec, Status.CURRENT)
    return VersionReport(spec, Status.BEHIND, latest=newer[-1],
                         detail=f"newer: {', '.join(newer[-4:])}")


def check_all(
    specs: Iterable[ToolSpec],
    on_report: Callable[[VersionReport], None] | None = None,
    timeout: int = net.DEFAULT_TIMEOUT,
) -> list[VersionReport]:
    """Check every tool, reporting each as it arrives so a slow network still
    fills the window row by row.

    Once GitHub has said it is rate limiting this address, the remaining tools
    are reported without asking: the answer would be the same refusal, and nine
    more round trips to collect it makes the window sit there for no reason.
    """
    reports: list[VersionReport] = []
    limited = False
    for spec in specs:
        if limited and not spec.pip_package and repository_of(spec) is not None:
            report = VersionReport(spec, Status.UNKNOWN, detail=RATE_LIMITED)
        else:
            report = check_one(spec, timeout)
            limited = limited or report.detail == RATE_LIMITED
        reports.append(report)
        if on_report:
            on_report(report)
    return reports


def releases_url(spec: ToolSpec) -> str:
    repo = repository_of(spec)
    return f"https://github.com/{repo}/releases" if repo else spec.homepage
