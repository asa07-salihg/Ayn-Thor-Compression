"""Build the single-file Windows executable.

Why
    PyInstaller is happy to produce an exe that starts and then fails on the
    first conversion, because the converter binaries were missing from `tools/`
    at build time and nothing checked. Two guards live here rather than in the
    spec: the tools check, and a test that the exe being replaced is not
    currently running. Windows refuses to overwrite a running exe, and
    PyInstaller only reports "Access is denied" after several minutes of work.

    It also writes `dist/SHA256SUMS.txt`. That is not a convenience: the
    updater refuses to install a release whose checksum file is missing, and
    verifies the download against it, so the file has to be produced by the
    same step that produced the exe. Writing it by hand afterwards is how the
    two drift apart.

Usage
    python packaging/build_exe.py [--allow-missing-tools]

    --allow-missing-tools builds anyway. CI uses it, because a release exe can
    download its tools at runtime and CI cannot always reach every host.

    Both files in dist/ are what a release needs:
        gh release create v1.0.0 dist/AynThorCompression.exe dist/SHA256SUMS.txt

Used by
    Whoever is cutting a release, and .github/workflows/release.yml.
    See CONTRIBUTING.md.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aynthor import CHECKSUM_ASSET, RELEASE_ASSET, __version__

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SPEC = ROOT / "packaging" / "AynThorCompression.spec"
OUTPUT = ROOT / "dist" / RELEASE_ASSET
CHECKSUMS = ROOT / "dist" / CHECKSUM_ASSET

# Bundled into the exe. z3ds_compressor is deliberately absent: rom-converto's
# ctr commands do the same job with a selectable level, and z3ds_compressor
# drags in four MinGW DLLs for a 200 KB tool. It stays installable from Tools.
BUNDLED_TOOLS = (
    "chdman.exe",
    "DolphinTool.exe",
    "maxcso.exe",
    "7za.exe",
    "rom-converto.exe",
    "ndstrim.exe",
    "ctrtool.exe",
    "decrypt.exe",
    "makerom.exe",
    "seeddb.bin",
)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller.")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def output_is_locked() -> bool:
    if not OUTPUT.is_file():
        return False
    try:
        with OUTPUT.open("ab"):
            return False
    except OSError:
        return True


def main() -> int:
    ensure_pyinstaller()

    if output_is_locked():
        print(f"{OUTPUT.name} is running. Close it and try again.")
        return 1

    missing = [name for name in BUNDLED_TOOLS if not (TOOLS / name).is_file()]
    if missing:
        print("Missing from tools/:", ", ".join(missing))
        if "--allow-missing-tools" not in sys.argv[1:]:
            print("Run `python scripts/fetch_tools.py` first, or pass --allow-missing-tools.")
            return 1
        print("Building without them. The app can download them at runtime.")

    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", str(SPEC)],
        cwd=ROOT,
    )

    if not OUTPUT.is_file():
        print("PyInstaller finished but produced no exe at", OUTPUT)
        return 1

    digest = write_checksums()
    print(f"\n{OUTPUT}  ({OUTPUT.stat().st_size / (1024 * 1024):.1f} MB)")
    print(f"{CHECKSUMS}")
    print(f"  {digest}")
    print("\nOn first run the exe creates a tools/ folder beside itself.")
    print(f"\nTo publish version {__version__}:")
    print(f"  gh release create v{__version__} \"{OUTPUT}\" \"{CHECKSUMS}\"")
    return 0


def write_checksums() -> str:
    """Write dist/SHA256SUMS.txt in the format the updater reads back.

    `sha256  filename`, two spaces, the bare filename with no directory. That
    is what `core.updates._expected_digest` parses, and what `sha256sum -c`
    and `Get-FileHash` users expect.
    """
    digest = hashlib.sha256()
    with OUTPUT.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    hexdigest = digest.hexdigest()
    CHECKSUMS.write_text(f"{hexdigest}  {OUTPUT.name}\n", encoding="utf-8")
    return hexdigest


if __name__ == "__main__":
    raise SystemExit(main())
