"""Check GitHub for a newer release, and install it.

Why
    The app is a single exe with no installer, which is what makes it easy to
    put on a card and hard to keep current: nothing tells the user a new build
    exists. So it asks GitHub itself, the same way an external release tracker
    would, and can replace itself with what it finds.

    Three things make that safe enough to do automatically:

    * The download is verified against the `SHA256SUMS.txt` published with the
      release before anything is replaced. A release without that file is
      reported, not installed.
    * Windows will not let a running exe be overwritten, so the replacement is
      done by a small script that waits for this process to exit first. The
      previous exe is kept alongside until the new one has started.
    * Nothing happens without the user pressing a button. There is no silent
      update and no background check on a timer.

    Running from source there is nothing to replace, so the check reports what
    is available and stops.

Used by
    `ui.update_check` (the More menu and the About box).

Reference
    Releases API: https://docs.github.com/en/rest/releases/releases#get-the-latest-release
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from aynthor import CHECKSUM_ASSET, PROJECT_REPO, RELEASE_ASSET, __version__
from aynthor.core import net
from aynthor.core.runtime import is_frozen
from aynthor.core.system import no_window_kwargs

LATEST_RELEASE_API = f"https://api.github.com/repos/{PROJECT_REPO}/releases/latest"

_TIMEOUT = 15
_CHUNK = 256 * 1024
_VERSION_PART = re.compile(r"\d+")


class UpdateError(RuntimeError):
    """Something went wrong that is worth showing the user verbatim."""


@dataclass(frozen=True)
class Release:
    version: str          # normalised, without the leading v
    tag: str
    page_url: str
    notes: str
    asset_url: str | None
    asset_size: int
    checksum_url: str | None

    @property
    def is_installable(self) -> bool:
        return bool(self.asset_url and self.checksum_url)


def parse_version(text: str) -> tuple[int, ...]:
    """Turn "v1.2.3" or "1.2" into a comparable tuple.

    Deliberately forgiving: a tag that does not parse compares as (0,), which
    means it is never mistaken for something newer than what is installed.
    """
    numbers = _VERSION_PART.findall(text.split("-")[0])
    return tuple(int(n) for n in numbers) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def fetch_latest(timeout: int = _TIMEOUT) -> Release:
    """Ask GitHub what the latest release is. Raises UpdateError on failure."""
    try:
        payload = net.fetch_json(LATEST_RELEASE_API, timeout=timeout)
    except net.NetworkError as exc:
        message = str(exc)
        if "404" in message:
            raise UpdateError(
                "No releases have been published for this project yet.") from exc
        raise UpdateError(message) from exc

    assets = {a.get("name"): a for a in payload.get("assets", []) if a.get("name")}
    exe = assets.get(RELEASE_ASSET)
    checksums = assets.get(CHECKSUM_ASSET)
    tag = str(payload.get("tag_name") or "")

    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        page_url=str(payload.get("html_url") or ""),
        notes=str(payload.get("body") or "").strip(),
        asset_url=exe.get("browser_download_url") if exe else None,
        asset_size=int(exe.get("size", 0)) if exe else 0,
        checksum_url=checksums.get("browser_download_url") if checksums else None,
    )


def check() -> Release | None:
    """The latest release if it is newer than this build, else None."""
    release = fetch_latest()
    return release if is_newer(release.version) else None


# --------------------------------------------------------------------- install

def _download(url: str, destination: Path, on_progress: Callable[[int], None] | None,
              expected_size: int = 0) -> Path:
    try:
        return net.download(url, destination, on_progress,
                            expected_size=expected_size, timeout=_TIMEOUT)
    except net.NetworkError as exc:
        raise UpdateError(str(exc)) from exc


def _expected_digest(checksum_text: str, asset_name: str) -> str:
    """Pull one file's hash out of a `sha256  filename` listing.

    The value has to look like a SHA-256 and the file has to be listed once.
    A token that is not 64 hex characters could never match a real digest, so
    accepting it only turned a malformed checksum file into a confusing
    mismatch; two differing entries for the same asset is worse, because taking
    the first silently picks one of two answers.
    """
    found: list[str] = []
    for line in checksum_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == asset_name:
            found.append(parts[0].lower())

    if not found:
        raise UpdateError(f"{asset_name} is not listed in {CHECKSUM_ASSET}.")
    if len(set(found)) > 1:
        raise UpdateError(
            f"{CHECKSUM_ASSET} lists {asset_name} more than once, with different "
            "hashes. Nothing was installed.")
    digest = found[0]
    if not _SHA256_RE.fullmatch(digest):
        raise UpdateError(
            f"The hash listed for {asset_name} is not a SHA-256. Nothing was "
            "installed.")
    return digest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(release: Release,
                      on_progress: Callable[[int], None] | None = None) -> Path:
    """Fetch the new exe and check it against the release's own checksum file.

    Returns the path to the verified download, which sits beside the running
    exe so the replacement is a rename on the same volume.
    """
    if not release.is_installable:
        raise UpdateError(
            f"Release {release.tag} has no {RELEASE_ASSET} with a {CHECKSUM_ASSET} "
            "beside it, so it cannot be verified. Download it by hand instead.")

    # Beside the exe, so the replacement is a rename on the same volume rather
    # than a copy across drives.
    target_dir = (Path(sys.executable).resolve().parent if is_frozen()
                  else Path(tempfile.gettempdir()))
    download = target_dir / f"{RELEASE_ASSET}.new"
    download.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        sums = _download(release.checksum_url, Path(scratch) / CHECKSUM_ASSET, None)
        expected = _expected_digest(sums.read_text(encoding="utf-8", errors="replace"),
                                    RELEASE_ASSET)

    _download(release.asset_url, download, on_progress, release.asset_size)
    actual = _sha256(download)
    if actual != expected:
        download.unlink(missing_ok=True)
        raise UpdateError(
            "The download did not match the checksum published with the release "
            f"and was discarded.\n  expected {expected}\n  got      {actual}")

    if on_progress:
        on_progress(100)
    return download


# The replacement script. Windows holds a lock on a running exe, so this waits
# for the process to go away before touching it, keeps the old build as .old
# until the new one has started, and deletes itself last.
# Characters the replacement script cannot carry through a batch variable.
_UNSCRIPTABLE = ('%', '"', '\r', '\n')

_SHA256_RE = re.compile(r"[0-9a-f]{64}")

_SWAP_SCRIPT = """@echo off
setlocal
set "TARGET={target}"
set "NEW={new}"
set "OLD={target}.old"

for /l %%i in (1,1,60) do (
    ping -n 2 127.0.0.1 >nul
    del "%OLD%" >nul 2>&1
    move /y "%TARGET%" "%OLD%" >nul 2>&1 && goto :replace
)
goto :cleanup

:replace
move /y "%NEW%" "%TARGET%" >nul 2>&1 || move /y "%OLD%" "%TARGET%" >nul 2>&1
start "" "%TARGET%"

:cleanup
ping -n 3 127.0.0.1 >nul
del "%OLD%" >nul 2>&1
del "%~f0" >nul 2>&1
"""


def apply_update(download: Path) -> None:
    """Hand over to the swap script and expect the caller to quit immediately.

    Only meaningful in a frozen build: from source there is no exe to replace.
    """
    if not is_frozen():
        raise UpdateError(
            "This is running from source, so there is no executable to replace. "
            "Use `git pull` instead.")

    target = Path(sys.executable).resolve()
    new = download.resolve()
    for path in (target, new):
        # `%` is legal in a Windows folder name and is variable expansion to
        # cmd, so an install under `C:\%Games%\` would set TARGET to something
        # else entirely and the script would move the wrong file, or nothing.
        # Escaping is not enough for a quote, which cannot appear in a path
        # anyway, so both are simply refused with a reason.
        if any(ch in str(path) for ch in _UNSCRIPTABLE):
            raise UpdateError(
                f"This folder cannot be updated automatically because its path "
                f"contains one of {' '.join(_UNSCRIPTABLE)}:\n  {path}\n"
                "Download the new version and replace the file by hand.")

    script = target.parent / "aynthor-update.cmd"
    script.write_text(
        _SWAP_SCRIPT.format(target=target, new=new),
        encoding="utf-8",
    )

    subprocess.Popen(
        ["cmd", "/c", str(script)],
        cwd=str(target.parent),
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        **{k: v for k, v in no_window_kwargs().items() if k != "creationflags"},
    )


def can_self_update() -> bool:
    """False when running from source, or from a folder we cannot write to."""
    if not is_frozen():
        return False
    return os.access(Path(sys.executable).resolve().parent, os.W_OK)
