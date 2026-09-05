"""Download, verify and install the external converter tools.

Why
    The app is useless without binaries it does not ship, and asking a user to
    hunt down eight of them is how a tool gets closed and forgotten. So it
    fetches them. That makes this module the app's most security-sensitive
    code, and it is written accordingly:

    * Nothing reaches `tools/` before its SHA-256 matches `manifest`. A file
      that does not match is discarded and reported, not installed.
    * Archives are unpacked into a scratch directory and only the named members
      are copied out, so an archive cannot drop extra files next to the ones
      the app runs.
    * Archive members are matched by their full path inside the archive, not by
      filename. The 7-Zip extras archive ships x86, x64 and arm64 builds of the
      same filename; matching loosely installed the wrong architecture.
    * Every path that comes out of an archive is checked to be inside the
      scratch directory. An archive entry named `../../evil.exe` is a classic
      way to write outside the extraction root; Python's zipfile drops such
      components on its own and 7-Zip refuses them, but this code is what runs
      the result, so it verifies rather than trusts.

    Transport is handled by `core.net`, which enforces HTTPS through redirects
    and caps the download size. That is the weaker half of the guarantee: the
    checksums are what say the bytes are the ones we expected.

Used by
    `ui.tools_dialog` (the Tools window), `scripts/fetch_tools.py` (headless
    setup and CI).

Reference
    What each tool is and where it comes from: `manifest`, and
    THIRD-PARTY-NOTICES.md for licences.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from aynthor.core import net
from aynthor.core.system import no_window_kwargs, tools_dir
from aynthor.core.tools.manifest import (
    BOOTSTRAP_KEY,
    INSTALLABLE,
    SPECS_BY_KEY,
    TOOL_SPECS,
    ToolFile,
    ToolSpec,
)

Progress = Callable[[str], None]

_CHUNK = 256 * 1024

# What a converter release plausibly contains. Both are bounds on an archive
# that has not been verified yet, so they are deliberately generous: the point
# is to refuse a bomb, not to police upstream packaging.
_MAX_MEMBERS = 10_000
_MAX_UNPACKED = 4 * 1024**3

# Path components an archive has no business containing. Any of them means the
# entry is trying to escape the directory it is being unpacked into.
_UNSAFE_PARTS = {"..", ""}


class ToolError(RuntimeError):
    """An install that failed for a reason worth showing the user verbatim."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ToolsManager:
    def __init__(self) -> None:
        self.tools_root = tools_dir()
        self.tools_root.mkdir(parents=True, exist_ok=True)
        self._available: dict[str, bool] = {}

    # ------------------------------------------------------------------ status

    def refresh(self) -> None:
        """Forget what is installed. Call after installing or removing a tool."""
        self._available.clear()

    def is_available(self, key: str) -> bool:
        """Cached: the interface asks this while a batch runs, and the answer
        involves a filesystem stat per file and an import probe for nsz. Tools
        do not appear or vanish on their own, so it is read once per manager."""
        cached = self._available.get(key)
        if cached is not None:
            return cached
        self._available[key] = self._probe(key)
        return self._available[key]

    def _probe(self, key: str) -> bool:
        spec = SPECS_BY_KEY.get(key)
        if spec is None:
            return False
        if spec.pip_package:
            # In the frozen build nsz is bundled, so find_spec succeeds without
            # anything having been pip-installed.
            return importlib.util.find_spec(spec.pip_package) is not None
        return all((self.tools_root / name).is_file() for name in spec.filenames())

    def status(self) -> dict[str, bool]:
        return {spec.key: self.is_available(spec.key) for spec in INSTALLABLE}

    def matches_manifest(self, key: str) -> bool:
        """Do the installed files still hash to what this release pinned?

        Why
            `is_available` only asks whether the file is there, which was enough
            when a tool was installed once and never changed. It is not enough
            once a pin moves: an older build's 7za sat in `tools/` forever,
            reported as installed, and no update ever replaced it.

            An entry with no checksum (DolphinTool) cannot be told apart from an
            older one and is treated as matching, which is the same admission the
            Tools window already makes about it.
        """
        spec = SPECS_BY_KEY.get(key)
        if spec is None or spec.pip_package:
            return True
        for expected in spec.files:
            if expected.sha256 is None:
                continue
            path = self.tools_root / expected.name
            if not path.is_file() or sha256_of(path) != expected.sha256:
                return False
        return True

    def outdated(self) -> list[str]:
        """Installed tools whose files are not the ones this release pinned.

        Hashing every installed tool costs well under a second, and it only
        happens when the Tools window asks or an install runs, not on the path
        of a conversion.
        """
        return [
            spec.key
            for spec in INSTALLABLE
            if self.is_available(spec.key) and not self.matches_manifest(spec.key)
        ]

    def unverified(self) -> list[str]:
        """Installed tools whose manifest entry has no checksum to check."""
        return [
            spec.label
            for spec in INSTALLABLE
            if self.is_available(spec.key)
            and any(f.sha256 is None for f in spec.files)
        ]

    # ----------------------------------------------------------------- install

    def install_all(self, progress: Progress | None = None) -> list[str]:
        """Install everything missing or superseded. One message per failure.

        A tool whose files no longer match the manifest is reinstalled rather
        than skipped, which is what makes a new pin in a new release of this app
        actually reach the machine it is running on.
        """
        say = progress or (lambda _msg: None)
        errors: list[str] = []

        for spec in TOOL_SPECS:
            present = self.is_available(spec.key) or (
                spec.key == BOOTSTRAP_KEY and (self.tools_root / "7zr.exe").is_file()
            )
            if present and not self.matches_manifest(spec.key):
                say(f"{spec.label}: installed copy is not {spec.version}, replacing it")
                present = False
            if present:
                if spec.key != BOOTSTRAP_KEY:
                    say(f"{spec.label}: already installed")
                continue
            try:
                self.install(spec.key, say)
                self.refresh()
            except Exception as exc:  # noqa: BLE001 - every failure is reportable
                message = f"{spec.label}: {exc}"
                if spec.manual_hint:
                    message += f"\n  {spec.manual_hint}"
                errors.append(message)
                say(f"FAILED {message}")

        return errors

    def install(self, key: str, progress: Progress | None = None) -> None:
        say = progress or (lambda _msg: None)
        spec = SPECS_BY_KEY[key]

        if spec.pip_package:
            say(f"{spec.label}: installing {spec.pip_package} with pip")
            self._pip_install(spec.pip_package)
            say(f"{spec.label}: installed")
            return

        if spec.needs_7zr and not (self.tools_root / "7zr.exe").is_file():
            self.install(BOOTSTRAP_KEY, say)

        if not spec.url:
            raise ToolError(spec.manual_hint or "This tool has to be installed by hand.")

        say(f"{spec.label}: downloading {spec.version}")
        scratch = self._scratch(spec.key)
        try:
            download = self._download(spec.url, scratch)
            staged = self._stage(spec, download, scratch)
            self._verify(spec, staged)
            for name, path in staged.items():
                shutil.copy2(path, self.tools_root / name)
            say(f"{spec.label}: installed and verified")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    # ------------------------------------------------------------------ steps

    def _scratch(self, key: str) -> Path:
        path = self.tools_root / f"_staging_{key}"
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        return path

    @staticmethod
    def _download(url: str, scratch: Path) -> Path:
        try:
            return net.download(url, scratch / "download.bin")
        except net.NetworkError as exc:
            raise ToolError(str(exc)) from exc

    def _stage(self, spec: ToolSpec, download: Path, scratch: Path) -> dict[str, Path]:
        """Put every file the spec names into the scratch dir. Nothing is
        copied into tools/ until the whole set has been verified."""
        if spec.archive == "exe":
            only = spec.files[0]
            target = scratch / only.name
            download.replace(target)
            return {only.name: target}

        extracted = scratch / "unpacked"
        extracted.mkdir()
        if spec.archive == "zip":
            self._extract_zip(download, extracted)
        elif spec.archive == "7z":
            self._extract_7z(download, extracted)
        else:
            raise ToolError(f"Unsupported archive type: {spec.archive}")

        staged: dict[str, Path] = {}
        for wanted in spec.files:
            found = self._find_member(extracted, wanted)
            if found is None:
                if wanted.optional:
                    continue
                raise ToolError(f"{wanted.member or wanted.name} was not in the archive.")
            self._assert_inside(extracted, found)
            staged[wanted.name] = found
        return staged

    @staticmethod
    def _check_member_name(name: str) -> None:
        """Refuse an archive entry that points outside the extraction root."""
        normalised = name.replace("\\", "/")
        if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
            raise ToolError(f"Archive entry is an absolute path: {name}")
        if any(part in _UNSAFE_PARTS for part in PurePosixPath(normalised).parts):
            raise ToolError(f"Archive entry escapes the extraction folder: {name}")

    @staticmethod
    def _assert_inside(root: Path, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()):
            raise ToolError(f"Archive wrote outside the extraction folder: {path}")
        return resolved

    def _extract_zip(self, archive: Path, into: Path) -> None:
        with zipfile.ZipFile(archive) as opened:
            members = opened.infolist()
            # The archive itself is never hashed -- only what comes out of it
            # is -- so extraction happens before anything has been verified.
            # A 512 MB download is about a petabyte of deflate, and the
            # cleanup that removes the scratch directory only runs afterwards.
            if len(members) > _MAX_MEMBERS:
                raise ToolError(
                    f"Archive holds {len(members)} entries, more than the "
                    f"{_MAX_MEMBERS} a converter release ever should.")
            declared = sum(info.file_size for info in members)
            if declared > _MAX_UNPACKED:
                raise ToolError(
                    f"Archive unpacks to {declared / 1e9:.1f} GB, over the "
                    f"{_MAX_UNPACKED / 1e9:.0f} GB limit.")
            for info in members:
                if not info.is_dir():
                    self._check_member_name(info.filename)
            opened.extractall(into)

    def _extract_7z(self, archive: Path, into: Path) -> None:
        # Only the verified copy. This used to fall back to whatever `7zr` or
        # `7z` was first on PATH, which is an executable nobody checked, run to
        # unpack the archives every other tool arrives in. PATH on Windows
        # routinely includes directories the user's other software can write
        # to, so that fallback undid the guarantee the whole install path is
        # built on. If the bootstrap is missing it is downloaded and hashed
        # like everything else.
        seven_zr = self.tools_root / "7zr.exe"
        if not seven_zr.is_file():
            raise ToolError(
                "The verified 7zr is not installed, and no other copy is trusted "
                "to unpack this. Install the tools again from the Tools window.")
        result = subprocess.run(
            [str(seven_zr), "x", str(archive), f"-o{into}", "-y"],
            capture_output=True, text=True, check=False, **no_window_kwargs(),
        )
        if result.returncode != 0:
            raise ToolError((result.stderr or result.stdout or "7zr failed").strip())

        # 7-Zip does its own path sanitising; this is the check that it did.
        for extracted in into.rglob("*"):
            self._assert_inside(into, extracted)

    @staticmethod
    def _find_member(root: Path, wanted: ToolFile) -> Path | None:
        """Locate an archive member by the tail of its path.

        The tail rather than the exact path because archives wrap their
        contents in a top-level directory whose name carries the version or
        commit, which would otherwise have to be pinned twice.
        """
        needle = (wanted.member or wanted.name).replace("\\", "/").lower()
        for candidate in sorted(root.rglob("*")):
            if not candidate.is_file():
                continue
            path = candidate.relative_to(root).as_posix().lower()
            if path == needle or path.endswith("/" + needle):
                return candidate
        return None

    @staticmethod
    def _verify(spec: ToolSpec, staged: dict[str, Path]) -> None:
        for wanted in spec.files:
            path = staged.get(wanted.name)
            if path is None:
                continue
            if wanted.sha256 is None:
                # Deliberate, and documented per entry in the manifest.
                continue
            actual = sha256_of(path)
            if actual != wanted.sha256:
                raise ToolError(
                    f"{wanted.name} does not match the checksum in the manifest and was "
                    f"not installed.\n  expected {wanted.sha256}\n  got      {actual}"
                )

    @staticmethod
    def _pip_install(package: str) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True, text=True, check=False, **no_window_kwargs(),
        )
        if result.returncode != 0:
            raise ToolError((result.stderr or result.stdout or "pip failed").strip())
