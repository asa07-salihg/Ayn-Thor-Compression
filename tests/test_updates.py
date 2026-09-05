"""Version comparison and checksum handling for the self-updater.

This is the code that decides whether to replace the running executable, so the
parts that can be tested without a network are tested hard: a tag that does not
parse must never look newer than what is installed, and a checksum file that
does not name the asset must be an error rather than a silent pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aynthor.core import updates


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.0.0", (1, 0, 0)), ("v1.0.0", (1, 0, 0)), ("v1.2", (1, 2)),
     ("2.0.0-beta.1", (2, 0, 0)), ("v10.0.1", (10, 0, 1))],
)
def test_parse_version(text, expected):
    assert updates.parse_version(text) == expected


def test_an_unparseable_tag_never_looks_newer():
    """A release named "nightly" must not trigger an update."""
    assert updates.parse_version("nightly") == (0,)
    assert updates.is_newer("nightly", "1.0.0") is False


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [("1.0.1", "1.0.0", True), ("1.1.0", "1.0.9", True), ("2.0.0", "1.9.9", True),
     ("1.0.0", "1.0.0", False), ("0.9.9", "1.0.0", False),
     ("v1.0.1", "1.0.0", True), ("1.10.0", "1.9.0", True)],
)
def test_is_newer(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer


def test_double_digit_versions_compare_numerically():
    """String comparison would put 1.9.0 above 1.10.0."""
    assert updates.is_newer("1.10.0", "1.9.0") is True


# --------------------------------------------------------------- checksums

CHECKSUMS = (
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08  "
    "AynThorCompression.exe\n"
    "0000000000000000000000000000000000000000000000000000000000000000  other.zip\n"
)


def test_digest_is_found_by_asset_name():
    digest = updates._expected_digest(CHECKSUMS, "AynThorCompression.exe")
    assert digest.startswith("9f86d081")


DIGEST = "a" * 64
OTHER = "b" * 64


def test_a_leading_star_from_binary_mode_is_ignored():
    """sha256sum writes `hash *name` in binary mode."""
    text = f"{DIGEST}  *AynThorCompression.exe\n"
    assert updates._expected_digest(text, "AynThorCompression.exe") == DIGEST


def test_a_hash_that_is_not_a_sha256_is_refused():
    """It could never match a real digest, so accepting it only turned a
    malformed checksum file into a confusing mismatch."""
    with pytest.raises(updates.UpdateError, match="not a SHA-256"):
        updates._expected_digest("abc123  AynThorCompression.exe\n",
                                 "AynThorCompression.exe")


def test_the_asset_listed_twice_with_different_hashes_is_refused():
    """Taking the first silently picks one of two answers."""
    text = f"{DIGEST}  AynThorCompression.exe\n{OTHER}  AynThorCompression.exe\n"
    with pytest.raises(updates.UpdateError, match="more than once"):
        updates._expected_digest(text, "AynThorCompression.exe")


def test_the_same_hash_listed_twice_is_fine():
    text = f"{DIGEST}  AynThorCompression.exe\n{DIGEST}  *AynThorCompression.exe\n"
    assert updates._expected_digest(text, "AynThorCompression.exe") == DIGEST


def test_a_missing_asset_is_an_error_not_a_pass():
    with pytest.raises(updates.UpdateError, match="not listed"):
        updates._expected_digest(CHECKSUMS, "SomethingElse.exe")


def test_sha256_of_a_file(tmp_path: Path):
    import hashlib

    blob = tmp_path / "blob"
    payload = b"y" * (1024 * 1024 + 3)  # crosses the read chunk boundary
    blob.write_bytes(payload)
    assert updates._sha256(blob) == hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------ release parsing

def release_payload(**overrides) -> dict:
    payload = {
        "tag_name": "v1.2.0",
        "html_url": "https://example.invalid/releases/v1.2.0",
        "body": "Fixed things.",
        "assets": [
            {"name": "AynThorCompression.exe",
             "browser_download_url": "https://example.invalid/a.exe", "size": 1234},
            {"name": "SHA256SUMS.txt",
             "browser_download_url": "https://example.invalid/s.txt", "size": 90},
        ],
    }
    payload.update(overrides)
    return payload


def parse(payload: dict) -> updates.Release:
    """Build a Release the way fetch_latest does, without the network."""
    assets = {a["name"]: a for a in payload.get("assets", [])}
    exe, sums = assets.get("AynThorCompression.exe"), assets.get("SHA256SUMS.txt")
    tag = payload.get("tag_name", "")
    return updates.Release(
        version=tag.lstrip("vV"), tag=tag,
        page_url=payload.get("html_url", ""), notes=payload.get("body", ""),
        asset_url=exe["browser_download_url"] if exe else None,
        asset_size=exe["size"] if exe else 0,
        checksum_url=sums["browser_download_url"] if sums else None,
    )


def test_a_complete_release_is_installable():
    assert parse(release_payload()).is_installable is True


def test_a_release_without_a_checksum_file_is_not_installable():
    """Without it there is nothing to verify the download against."""
    payload = release_payload()
    payload["assets"] = [a for a in payload["assets"] if a["name"] != "SHA256SUMS.txt"]
    assert parse(payload).is_installable is False


def test_a_source_only_release_is_not_installable():
    assert parse(release_payload(assets=[])).is_installable is False


def test_the_version_drops_the_tag_prefix():
    assert parse(release_payload()).version == "1.2.0"


def test_the_api_url_points_at_the_configured_repository():
    from aynthor import PROJECT_REPO

    assert PROJECT_REPO in updates.LATEST_RELEASE_API
    assert updates.LATEST_RELEASE_API.startswith("https://api.github.com/repos/")


def test_the_payload_shape_this_suite_assumes_is_json_serialisable():
    json.dumps(release_payload())


# ------------------------------------------- the writer and the reader agree

def test_the_checksum_file_the_build_writes_is_the_one_the_updater_reads(tmp_path: Path):
    """These two are the whole verification chain, and they live in different
    files. If the format drifts, an update silently becomes uninstallable."""
    import hashlib
    import importlib.util

    from aynthor import CHECKSUM_ASSET, RELEASE_ASSET

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_exe", root / "packaging" / "build_exe.py")
    build_exe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_exe)

    payload = b"pretend this is an exe"
    exe = tmp_path / RELEASE_ASSET
    exe.write_bytes(payload)
    build_exe.OUTPUT = exe
    build_exe.CHECKSUMS = tmp_path / CHECKSUM_ASSET

    written = build_exe.write_checksums()
    assert written == hashlib.sha256(payload).hexdigest()

    text = build_exe.CHECKSUMS.read_text(encoding="utf-8")
    assert updates._expected_digest(text, RELEASE_ASSET) == written


def test_the_checksum_file_names_the_asset_without_a_directory(tmp_path: Path):
    """A path in there breaks `sha256sum -c` and the updater's lookup alike."""
    import importlib.util

    from aynthor import CHECKSUM_ASSET, RELEASE_ASSET

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "build_exe_paths", root / "packaging" / "build_exe.py")
    build_exe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_exe)

    exe = tmp_path / "nested" / RELEASE_ASSET
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    build_exe.OUTPUT = exe
    build_exe.CHECKSUMS = tmp_path / CHECKSUM_ASSET
    build_exe.write_checksums()

    line = build_exe.CHECKSUMS.read_text(encoding="utf-8").strip()
    assert line.endswith(f"  {RELEASE_ASSET}")
    assert "/" not in line and "\\" not in line


# ------------------------------------- the swap script is a batch file

@pytest.mark.parametrize("bad", ["%", '"', "\r", "\n"])
def test_a_path_batch_cannot_carry_is_refused(bad, tmp_path, monkeypatch):
    """`%` is legal in a Windows folder name and is variable expansion to cmd,
    so an install under `C:\\%Games%\\` set TARGET to something else entirely
    and the script moved the wrong file, or nothing."""
    import sys

    from aynthor.core import runtime

    folder = tmp_path / f"a{bad}b"
    exe = folder / "AynThorCompression.exe"
    monkeypatch.setattr(runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(updates, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(exe))

    with pytest.raises(updates.UpdateError, match="cannot be updated automatically"):
        updates.apply_update(tmp_path / "new.exe")


def test_an_ordinary_path_is_not_refused(tmp_path, monkeypatch):
    """The guard must not stop a normal install from updating."""
    import sys

    monkeypatch.setattr(updates, "is_frozen", lambda: True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "AynThorCompression.exe"))
    started: list[list[str]] = []
    monkeypatch.setattr(updates.subprocess, "Popen",
                        lambda cmd, **_kw: started.append(cmd))

    updates.apply_update(tmp_path / "new.exe")
    assert started, "the swap script should have been launched"
    assert (tmp_path / "aynthor-update.cmd").is_file()
