"""Every link to this project comes from one place.

Correcting the repository address should be a single edit. This fails if a
module, a document or a workflow grows its own copy of the URL.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from aynthor import (
    DOCS_URL,
    ISSUES_URL,
    LATEST_RELEASE_URL,
    PROJECT_NAME,
    PROJECT_OWNER,
    PROJECT_REPO,
    PROJECT_URL,
    RELEASE_ASSET,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "aynthor"


def test_the_urls_are_built_from_the_repository_name():
    assert f"{PROJECT_OWNER}/{PROJECT_NAME}" == PROJECT_REPO
    for url in (PROJECT_URL, ISSUES_URL, LATEST_RELEASE_URL, DOCS_URL):
        assert url.startswith(f"https://github.com/{PROJECT_REPO}")


def test_no_module_hardcodes_the_project_url():
    """Except `aynthor/__init__.py`, which is where it is defined."""
    offenders = []
    for path in SOURCE.rglob("*.py"):
        if path.name == "__init__.py" and path.parent == SOURCE:
            continue
        text = path.read_text(encoding="utf-8")
        if f"github.com/{PROJECT_OWNER}" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_the_release_asset_name_is_what_the_workflow_publishes():
    """The updater looks for this exact filename, and so would any external
    release tracker, so the two must not drift apart."""
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert RELEASE_ASSET in workflow


@pytest.mark.parametrize("document", ["README.md", "SECURITY.md", "CONTRIBUTING.md"])
def test_documents_point_at_the_same_repository(document):
    text = (ROOT / document).read_text(encoding="utf-8")
    for url in re.findall(r"https://github\.com/[\w.-]+/[\w.-]+", text):
        owner_repo = url.removeprefix("https://github.com/")
        if owner_repo.split("/")[0] != PROJECT_OWNER:
            continue  # a third-party project, checked elsewhere
        assert owner_repo.removesuffix(".git") == PROJECT_REPO, url
