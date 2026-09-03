"""The tool manifest, and the verification that guards installs.

This app downloads executables and runs them, so these are the tests that
matter most: a manifest entry without a checksum, or a verifier that accepts a
file it should not, is a supply-chain hole rather than a cosmetic bug.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from aynthor.core.tools.manager import ToolError, ToolsManager, sha256_of
from aynthor.core.tools.manifest import (
    BOOTSTRAP_KEY,
    INSTALLABLE,
    SPECS_BY_KEY,
    TOOL_SPECS,
    ToolFile,
    ToolSpec,
)

# The only entry allowed to ship without a checksum, because Dolphin publishes
# none. If another one appears here, it needs a documented reason first.
UNVERIFIABLE = {"DolphinTool"}


def test_keys_are_unique():
    keys = [spec.key for spec in TOOL_SPECS]
    assert len(keys) == len(set(keys))


def test_every_download_is_over_https():
    for spec in TOOL_SPECS:
        if spec.url:
            assert spec.url.startswith("https://"), spec.key


def test_every_tool_records_where_it_came_from():
    for spec in TOOL_SPECS:
        assert spec.homepage.startswith("https://"), spec.key
        assert spec.license, spec.key
        assert spec.version, spec.key


def test_only_the_documented_entry_lacks_a_checksum():
    without = {
        spec.key for spec in TOOL_SPECS
        if any(f.sha256 is None for f in spec.files)
    }
    assert without == UNVERIFIABLE


def test_checksums_look_like_sha256():
    for spec in TOOL_SPECS:
        for wanted in spec.files:
            if wanted.sha256 is None:
                continue
            assert len(wanted.sha256) == 64, f"{spec.key}/{wanted.name}"
            assert wanted.sha256 == wanted.sha256.lower()
            int(wanted.sha256, 16)  # raises if it is not hex


def test_archive_entries_name_a_member():
    for spec in TOOL_SPECS:
        if spec.archive == "exe":
            continue
        for wanted in spec.files:
            assert wanted.member, f"{spec.key}/{wanted.name} has no archive path"


def test_seven_zip_pins_the_x64_build():
    """The extras archive ships x86 at the root and x64 in a subfolder.

    Matching on filename alone installed the 32-bit build on 64-bit machines.
    """
    members = {f.name: f.member for f in SPECS_BY_KEY["7z"].files}
    assert members["7za.exe"] == "x64/7za.exe"
    assert members["7za.dll"] == "x64/7za.dll"


def test_the_3ds_decryptor_is_pinned_to_a_commit_not_a_branch():
    """A branch archive changes whenever the branch moves, so it cannot be hashed."""
    url = SPECS_BY_KEY["3ds-decryptor"].url
    assert "refs/heads" not in url
    assert "/archive/" in url


def test_archive_types_are_ones_the_manager_understands():
    assert {spec.archive for spec in TOOL_SPECS} <= {"exe", "zip", "7z"}


def test_bootstrap_is_excluded_from_the_installable_list():
    assert BOOTSTRAP_KEY not in {spec.key for spec in INSTALLABLE}


def test_pip_installed_tools_declare_no_files():
    for spec in TOOL_SPECS:
        if spec.pip_package:
            assert spec.files == ()


# --------------------------------------------------------------------- verify

def make_spec(sha: str | None) -> ToolSpec:
    return ToolSpec(
        key="test", label="Test", description="", homepage="https://example.invalid",
        license="MIT", version="1.0",
        files=(ToolFile("tool.exe", sha256=sha),),
    )


def test_verify_accepts_a_matching_file(tmp_path: Path):
    target = tmp_path / "tool.exe"
    target.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    ToolsManager._verify(make_spec(digest), {"tool.exe": target})


def test_verify_rejects_a_tampered_file(tmp_path: Path):
    target = tmp_path / "tool.exe"
    target.write_bytes(b"something else entirely")
    digest = hashlib.sha256(b"payload").hexdigest()
    with pytest.raises(ToolError, match="does not match the checksum"):
        ToolsManager._verify(make_spec(digest), {"tool.exe": target})


def test_verify_skips_an_entry_with_no_checksum(tmp_path: Path):
    target = tmp_path / "tool.exe"
    target.write_bytes(b"anything")
    ToolsManager._verify(make_spec(None), {"tool.exe": target})


def test_sha256_of_matches_hashlib(tmp_path: Path):
    target = tmp_path / "blob"
    payload = b"x" * (1024 * 1024 + 7)  # crosses the read chunk boundary
    target.write_bytes(payload)
    assert sha256_of(target) == hashlib.sha256(payload).hexdigest()


# ------------------------------------------------------------- member lookup

def test_member_lookup_prefers_the_exact_path(tmp_path: Path):
    (tmp_path / "x64").mkdir()
    (tmp_path / "7za.exe").write_bytes(b"32-bit")
    (tmp_path / "x64" / "7za.exe").write_bytes(b"64-bit")
    found = ToolsManager._find_member(tmp_path, ToolFile("7za.exe", member="x64/7za.exe"))
    assert found.read_bytes() == b"64-bit"


def test_member_lookup_sees_through_a_versioned_top_directory(tmp_path: Path):
    nested = tmp_path / "Repo-2fb1ac5" / "bin"
    nested.mkdir(parents=True)
    (nested / "ctrtool.exe").write_bytes(b"tool")
    found = ToolsManager._find_member(tmp_path, ToolFile("ctrtool.exe", member="bin/ctrtool.exe"))
    assert found == nested / "ctrtool.exe"


def test_member_lookup_returns_none_when_absent(tmp_path: Path):
    assert ToolsManager._find_member(tmp_path, ToolFile("missing.exe")) is None


def test_member_lookup_does_not_match_a_partial_name(tmp_path: Path):
    (tmp_path / "not7za.exe").write_bytes(b"decoy")
    assert ToolsManager._find_member(tmp_path, ToolFile("7za.exe")) is None


def test_zip_staging_extracts_only_the_named_members(tmp_path: Path, monkeypatch):
    """An archive must not be able to drop extra files next to the tools."""
    archive = tmp_path / "download.bin"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("wanted.exe", "good")
        zf.writestr("unwanted.dll", "surprise")

    spec = ToolSpec(
        key="test", label="Test", description="", homepage="https://example.invalid",
        license="MIT", version="1.0", archive="zip",
        files=(ToolFile("wanted.exe", member="wanted.exe",
                        sha256=hashlib.sha256(b"good").hexdigest()),),
    )
    manager = ToolsManager.__new__(ToolsManager)
    manager.tools_root = tmp_path / "tools"
    manager.tools_root.mkdir()

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    archive.replace(scratch / "download.bin")
    staged = manager._stage(spec, scratch / "download.bin", scratch)

    assert set(staged) == {"wanted.exe"}
    ToolsManager._verify(spec, staged)


# ------------------------------------------------------ archive containment

def staging_manager(tmp_path: Path) -> ToolsManager:
    manager = ToolsManager.__new__(ToolsManager)
    manager.tools_root = tmp_path / "tools"
    manager.tools_root.mkdir(exist_ok=True)
    manager._available = {}
    return manager


@pytest.mark.parametrize("member", [
    "../escaped.exe",
    "../../escaped.exe",
    "nested/../../escaped.exe",
    "/absolute.exe",
    "C:/windows/system32/evil.exe",
    "..\\escaped.exe",
])
def test_an_archive_entry_that_escapes_the_folder_is_refused(member):
    """The classic way to turn "unpack this" into "write anywhere"."""
    with pytest.raises(ToolError):
        ToolsManager._check_member_name(member)


@pytest.mark.parametrize("member", [
    "tool.exe", "bin/tool.exe", "x64/7za.exe", "Repo-1.2.3/bin/ctrtool.exe",
])
def test_an_ordinary_archive_entry_is_accepted(member):
    ToolsManager._check_member_name(member)


def test_a_zip_with_a_traversing_entry_is_rejected_before_extraction(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("tool.exe", "harmless")
        zf.writestr("../../pwned.exe", "not harmless")

    manager = staging_manager(tmp_path)
    into = tmp_path / "unpacked"
    into.mkdir()
    with pytest.raises(ToolError, match="escapes"):
        manager._extract_zip(archive, into)
    assert not (tmp_path.parent / "pwned.exe").exists()


def test_a_normal_zip_extracts(tmp_path: Path):
    archive = tmp_path / "fine.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("bin/tool.exe", "content")

    manager = staging_manager(tmp_path)
    into = tmp_path / "unpacked"
    into.mkdir()
    manager._extract_zip(archive, into)
    assert (into / "bin" / "tool.exe").read_text() == "content"


def test_a_member_resolved_outside_the_root_is_refused(tmp_path: Path):
    """The check that runs after extraction, for extractors we do not control."""
    root = tmp_path / "unpacked"
    root.mkdir()
    outside = tmp_path / "elsewhere.exe"
    outside.write_text("x")
    with pytest.raises(ToolError, match="outside"):
        ToolsManager._assert_inside(root, outside)


def test_a_member_inside_the_root_is_accepted(tmp_path: Path):
    root = tmp_path / "unpacked"
    root.mkdir()
    inside = root / "bin" / "tool.exe"
    inside.parent.mkdir()
    inside.write_text("x")
    assert ToolsManager._assert_inside(root, inside) == inside.resolve()


# ------------------------------------------------------------ availability

def test_availability_is_cached_until_refreshed(tmp_path: Path, monkeypatch):
    """The interface asks this while a batch runs; probing the filesystem for
    every format after every finished job made a long queue slower as it went."""
    manager = staging_manager(tmp_path)
    probes = []
    monkeypatch.setattr(ToolsManager, "_probe",
                        lambda self, key: probes.append(key) or False)

    manager.is_available("chdman")
    manager.is_available("chdman")
    manager.is_available("chdman")
    assert probes == ["chdman"]

    manager.refresh()
    manager.is_available("chdman")
    assert probes == ["chdman", "chdman"]


def test_an_unknown_key_is_simply_unavailable(tmp_path: Path):
    assert staging_manager(tmp_path).is_available("not-a-tool") is False


# ------------------------------------------------------- upstream versions

def test_a_github_hosted_tool_is_checkable():
    from aynthor.core.tools.versions import repository_of

    assert repository_of(SPECS_BY_KEY["maxcso"]) == "unknownbrackets/maxcso"
    assert repository_of(SPECS_BY_KEY["rom-converto"]) == "DevYukine/rom-converto"


def test_dolphin_is_the_only_tool_that_cannot_be_checked():
    from aynthor.core.tools.versions import repository_of

    unreachable = {s.key for s in INSTALLABLE if repository_of(s) is None and not s.pip_package}
    assert unreachable == {"DolphinTool"}


@pytest.mark.parametrize(
    ("text", "expected"),
    [("v1.0.6.3", (1, 0, 6, 3)), ("26.02", (26, 2)), ("namDHC v2.0 build", (2, 0)),
     ("corruption_fix", (0,)), ("v0.20.0", (0, 20, 0))],
)
def test_upstream_version_strings_compare_numerically(text, expected):
    """These are other people's tags, in whatever shape they chose."""
    from aynthor.core.tools.versions import as_numbers

    assert as_numbers(text) == expected


def test_a_tag_with_no_numbers_never_looks_newer():
    from aynthor.core.tools.versions import newer_tags

    assert newer_tags(["nightly", "latest"], "1.0.0") == []


def test_only_genuinely_newer_tags_are_reported():
    from aynthor.core.tools.versions import newer_tags

    tags = ["v0.14.0", "v0.15.0", "v0.19.0", "v0.20.0"]
    assert newer_tags(tags, "0.15.0") == ["v0.19.0", "v0.20.0"]


def test_double_digit_upstream_versions_sort_correctly():
    from aynthor.core.tools.versions import newer_tags

    assert newer_tags(["1.9.0", "1.10.0"], "1.9.0") == ["1.10.0"]


def test_a_pip_installed_tool_is_not_asked_about(monkeypatch):
    """pip resolves nsz itself, so there is no pin to compare against."""
    from aynthor.core.tools import versions

    monkeypatch.setattr(versions, "fetch_tags",
                        lambda *a, **k: pytest.fail("should not have asked"))
    report = versions.check_one(SPECS_BY_KEY["nsz"])
    assert report.status is versions.Status.PIP


def test_a_failed_check_is_reported_not_raised(monkeypatch):
    from aynthor.core import net
    from aynthor.core.tools import versions

    monkeypatch.setattr(versions, "fetch_tags",
                        lambda *a, **k: (_ for _ in ()).throw(net.NetworkError("offline")))
    report = versions.check_one(SPECS_BY_KEY["maxcso"])
    assert report.status is versions.Status.UNKNOWN
    assert "offline" in report.detail


def test_a_behind_tool_reports_the_newest_tag(monkeypatch):
    from aynthor.core.tools import versions

    monkeypatch.setattr(versions, "fetch_tags", lambda *a, **k: ["v1.13.0", "v1.14.0"])
    report = versions.check_one(SPECS_BY_KEY["maxcso"])
    assert report.status is versions.Status.BEHIND
    assert report.latest == "v1.14.0"


def test_a_current_tool_reports_nothing_newer(monkeypatch):
    from aynthor.core.tools import versions

    monkeypatch.setattr(versions, "fetch_tags", lambda *a, **k: ["v1.12.0", "v1.13.0"])
    assert versions.check_one(SPECS_BY_KEY["maxcso"]).status is versions.Status.CURRENT


def test_a_rate_limited_check_explains_itself(monkeypatch):
    """403 against a public repository reads as a permission problem it is not."""
    from aynthor.core import net
    from aynthor.core.tools import versions

    def refuse(*_a, **_k):
        raise net.NetworkError("... returned 403 Forbidden.", 403)

    monkeypatch.setattr(versions, "fetch_tags", refuse)
    report = versions.check_one(SPECS_BY_KEY["maxcso"])
    assert report.status is versions.Status.UNKNOWN
    assert report.detail == versions.RATE_LIMITED
    assert "403" not in report.detail


def test_the_rest_are_not_asked_once_github_is_rate_limiting(monkeypatch):
    """Nine more round trips to collect the same refusal is nine wasted waits."""
    from aynthor.core import net
    from aynthor.core.tools import versions

    calls = []

    def refuse(repo, *_a, **_k):
        calls.append(repo)
        raise net.NetworkError("... returned 403 Forbidden.", 403)

    monkeypatch.setattr(versions, "fetch_tags", refuse)
    specs = [SPECS_BY_KEY["maxcso"], SPECS_BY_KEY["ndstrim"], SPECS_BY_KEY["nsz"]]
    reports = versions.check_all(specs)

    assert len(calls) == 1
    assert [r.status for r in reports] == [
        versions.Status.UNKNOWN, versions.Status.UNKNOWN, versions.Status.PIP,
    ]
    assert reports[1].detail == versions.RATE_LIMITED
