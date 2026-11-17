"""Ask each converter's project whether the installed version is still current.

Every tool ships with a checksum in `manifest`. The Tools window can also
install a newer upstream build and remember its hash in `pins.json`. This
module compares tags against that effective version.

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


def rewrite_version_url(url: str, pinned_version: str, tag: str) -> str:
    """The download URL for `tag`, built by rewriting the pinned URL.

    Upstream tags and path shapes differ (`26.03` vs `7z2603`, `v0.21.0` vs
    `0.21.0`), so every spelling of the old and new version is tried, longest
    first, until the URL changes.
    """
    if not url:
        raise ValueError("No download URL to rewrite.")
    old_bare = pinned_version.lstrip("vV")
    new_bare = tag.lstrip("vV")
    pairs = [
        (pinned_version, tag),
        (old_bare, new_bare),
        (f"v{old_bare}", f"v{new_bare}"),
        (f"V{old_bare}", f"V{new_bare}"),
        (old_bare.replace(".", ""), new_bare.replace(".", "")),
    ]
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for old, new in pairs:
        if not old or old == new or (old, new) in seen:
            continue
        seen.add((old, new))
        ordered.append((old, new))
    ordered.sort(key=lambda pair: len(pair[0]), reverse=True)

    out = url
    for old, new in ordered:
        if old in out:
            out = out.replace(old, new)
    if out == url:
        raise ValueError(
            f"Could not put {tag!r} into the download URL for pinned {pinned_version!r}."
        )
    return out


def url_for_tag(spec: ToolSpec, tag: str) -> str:
    if not spec.url:
        raise ValueError(f"{spec.label} has no download URL.")
    return rewrite_version_url(spec.url, spec.version, tag)


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

    from aynthor.core.tools.pins import effective_version

    current = effective_version(spec)

    try:
        tags = fetch_tags(repo, timeout)
    except net.NetworkError as exc:
        return VersionReport(spec, Status.UNKNOWN, detail=_explain(exc))

    newer = newer_tags(tags, current)
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
