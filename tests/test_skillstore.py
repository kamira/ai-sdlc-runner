"""Tests for the offline local skill store resolver (CHG-20260617-05)."""
from __future__ import annotations

from pathlib import Path

from ai_sdlc_runner import contract, skillstore


def _store(tmp_path: Path, versions) -> Path:
    """Create a fake store with the given versions (each a dir with a SKILL.md)."""
    store = tmp_path / "skills"
    for v in versions:
        d = store / f"v{v}"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: ai-sdlc\nmetadata:\n  version: {v}\n---\n")
    return store


def test_store_versions_sorted_desc(tmp_path):
    store = _store(tmp_path, ["1.0.0", "1.1.0", "1.0.5"])
    assert skillstore.store_versions(store) == ["1.1.0", "1.0.5", "1.0.0"]


def test_store_versions_ignores_non_version_and_empty(tmp_path):
    store = _store(tmp_path, ["1.0.0"])
    (store / "notes").mkdir()                       # non-version dir
    (store / "v2.0.0").mkdir()                       # version dir without SKILL.md
    assert skillstore.store_versions(store) == ["1.0.0"]


def test_resolve_exact_and_by_major_minor(tmp_path):
    store = _store(tmp_path, ["1.0.0", "1.0.7", "1.1.0"])
    assert skillstore.resolve_path(store, version="1.1.0").endswith("v1.1.0")
    # major.minor match returns the highest patch.
    assert skillstore.resolve_path(store, major=1, minor=0).endswith("v1.0.7")
    # latest when nothing specified.
    assert skillstore.resolve_path(store).endswith("v1.1.0")


def test_resolve_missing_returns_none(tmp_path):
    store = _store(tmp_path, ["1.0.0"])
    assert skillstore.resolve_path(store, major=9, minor=9) is None
    assert skillstore.resolve_path(store, version="3.0.0") is None


def test_resolve_empty_store_returns_none(tmp_path):
    assert skillstore.resolve_path(tmp_path / "nope") is None
    assert skillstore.latest_version(tmp_path / "nope") is None


def test_detect_uses_newest_store_version_vs_lock(tmp_path):
    store = _store(tmp_path, ["1.0.0", "1.1.0"])
    proj = tmp_path / "proj"
    proj.mkdir()
    contract.resolve_contract(proj, "1.0.0")        # lock at 1.0.0
    info = skillstore.detect(store, project_dir=proj)
    assert info.local == "1.1.0" and info.baseline == "1.0.0"
    assert info.kind == "minor" and info.needs_migrate is True
    assert info.latest_tag == "1.1.0"               # newest available in the store


def test_detect_empty_store_is_none(tmp_path):
    assert skillstore.detect(tmp_path / "nope") is None
