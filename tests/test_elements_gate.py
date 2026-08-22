"""The regeneration gate and its three states (CHG-20260822-04 task 4).

D4 requires the gate to distinguish **match**, **regenerable drift** and **source missing**, with
both failures hard. The distinction is the point: drift means regenerate (or stop hand-editing
elements, which guideline §2/§8 forbid), while source-missing means the store those elements were
derived from is no longer there to derive from. One shared red would tell an operator neither.

Every failure state is produced by actually breaking a repo, never by stubbing the detector — a gate
tested only against the happy path is how this repo's false-greens have historically survived.

The fixtures build a small synthetic store rather than copying the real 2.7 MB tree: the gate's
logic is per-version and shape-driven, so a two-reference store exercises it exactly as the vendored
one does, and `test_elements_tree.py` already covers the real trees.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, dispatch

REFERENCE = """---
name: sample
description: a shipped reference
---

# Sample

intro

## Purpose

why this exists

### Detail

more

## Workflow

steps
"""

HALT_POLICY = {
    "gates": {"before_implement": {"low": "auto", "medium": "auto", "high": "halt"}},
    "always_halt_actions": ["production deploy / release"],
    "gate_meaning": {"before_implement": "after the CHG, before touching code"},
}
ROLE_REFS = {
    "common": ["sample"],
    "roles": {"analyst": ["other"]},
    "situational": {"cicd": ["other"]},
    "aliases": {"A1": "analyst"},
}


@pytest.fixture
def repo(tmp_path):
    """A miniature governed repo: one store version plus its freshly emitted element tree."""
    skill = tmp_path / "skills" / "v1.2.3"
    (skill / "references").mkdir(parents=True)
    (skill / "assets").mkdir()
    (skill / "SKILL.md").write_bytes(b"---\nname: s\nmetadata:\n  version: 1.2.3\n---\n")
    (skill / "references" / "sample.md").write_bytes(REFERENCE.encode("utf-8"))
    (skill / "references" / "other.md").write_bytes(REFERENCE.replace("Sample", "Other").encode("utf-8"))
    (skill / "assets" / "halt_policy.json").write_bytes(json.dumps(HALT_POLICY).encode("utf-8"))
    (skill / "assets" / "role_refs.json").write_bytes(json.dumps(ROLE_REFS).encode("utf-8"))
    dispatch.emit_all(skill, dispatch.elements_dir(tmp_path, "1.2.3"))
    return tmp_path


def _state(repo):
    return dispatch.verify_elements(repo)["state"]


def _row(repo, version="1.2.3"):
    report = dispatch.verify_elements(repo)
    return next(r for r in report["versions"] if r["version"] == version)


# --------------------------------------------------------------------------------------
# match
# --------------------------------------------------------------------------------------

def test_freshly_emitted_tree_matches(repo):
    row = _row(repo)
    assert row["state"] == dispatch.MATCH
    assert "byte-identical" in row["detail"]


def test_match_exits_zero_through_the_cli(repo, capsys):
    assert cli.main(["elements", "--repo", str(repo)]) == dispatch.EXIT_MATCH
    assert "match" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# drift — regeneration works and disagrees
# --------------------------------------------------------------------------------------

def test_hand_edited_element_is_drift(repo):
    """The case guideline §8 names: derived artifacts are generated, never edited."""
    target = next((repo / "elements" / "v1.2.3" / "elements").rglob("*.md"))
    target.write_bytes(target.read_bytes() + b"\nsneaked in\n")
    row = _row(repo)
    assert row["state"] == dispatch.DRIFT
    assert "differ" in row["detail"]


def test_store_changed_without_regenerating_is_drift(repo):
    """The other half of the same state: the source moved and nobody re-derived."""
    src = repo / "skills" / "v1.2.3" / "references" / "sample.md"
    src.write_bytes(src.read_bytes().replace(b"## Workflow", b"## Workflow renamed"))
    assert _row(repo)["state"] == dispatch.DRIFT


def test_store_version_with_no_element_tree_is_drift(repo):
    """Task 3's done-when, enforced by the gate: the source is there, so this is fixable by
    regenerating — which is drift, not a missing source."""
    for path in sorted((repo / "elements" / "v1.2.3").rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    (repo / "elements" / "v1.2.3").rmdir()
    row = _row(repo)
    assert row["state"] == dispatch.DRIFT
    assert "regenerate" in row["detail"]


def test_drift_exits_ten_through_the_cli(repo):
    target = next((repo / "elements" / "v1.2.3" / "elements").rglob("*.md"))
    target.write_bytes(b"replaced\n")
    assert cli.main(["elements", "--repo", str(repo)]) == dispatch.EXIT_DRIFT


# --------------------------------------------------------------------------------------
# source missing — the comparison cannot even be made
# --------------------------------------------------------------------------------------

def test_deleted_store_version_is_source_missing(repo):
    """Enumerating versions from `elements/` as well as `skills/` is what finds this. Enumerating
    only the store would skip the orphaned tree, and a missing source would read as nothing to do."""
    skill = repo / "skills" / "v1.2.3"
    for path in sorted(skill.rglob("*"), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    skill.rmdir()
    row = _row(repo)
    assert row["state"] == dispatch.SOURCE_MISSING
    assert "skills/v1.2.3" in row["detail"]


def test_deleted_source_reference_is_source_missing(repo):
    """Detected from the committed elements' own provenance — each names the path it came from —
    rather than from a judgement about which files the version ought to have had."""
    (repo / "skills" / "v1.2.3" / "references" / "other.md").unlink()
    row = _row(repo)
    assert row["state"] == dispatch.SOURCE_MISSING
    assert "references/other.md" in row["detail"]


def test_deleted_policy_asset_is_source_missing(repo):
    """The (iv) rule's teeth: a family committed in the tree whose policy is gone from the archive
    is a missing source, not a family that was never supposed to exist."""
    (repo / "skills" / "v1.2.3" / "assets" / "role_refs.json").unlink()
    row = _row(repo)
    assert row["state"] == dispatch.SOURCE_MISSING
    assert "role_refs.json" in row["detail"]


def test_source_missing_exits_eleven_through_the_cli(repo):
    (repo / "skills" / "v1.2.3" / "references" / "other.md").unlink()
    assert cli.main(["elements", "--repo", str(repo)]) == dispatch.EXIT_SOURCE_MISSING


# --------------------------------------------------------------------------------------
# the two failures stay distinguishable
# --------------------------------------------------------------------------------------

def test_the_three_exit_codes_are_distinct():
    codes = {dispatch.EXIT_MATCH, dispatch.EXIT_DRIFT, dispatch.EXIT_SOURCE_MISSING}
    assert len(codes) == 3
    assert dispatch.EXIT_MATCH == 0 and 0 not in {dispatch.EXIT_DRIFT, dispatch.EXIT_SOURCE_MISSING}


def test_source_missing_outranks_drift_across_versions(repo):
    """With one version drifting and another's source gone, the overall result must be the more
    fundamental failure — otherwise a run reports "regenerate" for something regeneration cannot fix."""
    second = repo / "skills" / "v1.3.0"
    (second / "references").mkdir(parents=True)
    (second / "assets").mkdir()
    (second / "SKILL.md").write_bytes(b"---\nname: s\nmetadata:\n  version: 1.3.0\n---\n")
    (second / "references" / "sample.md").write_bytes(REFERENCE.encode("utf-8"))
    (second / "assets" / "halt_policy.json").write_bytes(json.dumps(HALT_POLICY).encode("utf-8"))
    dispatch.emit_all(second, dispatch.elements_dir(repo, "1.3.0"))

    target = next((repo / "elements" / "v1.3.0" / "elements").rglob("*.md"))
    target.write_bytes(b"edited\n")                      # v1.3.0 drifts
    (repo / "skills" / "v1.2.3" / "references" / "other.md").unlink()   # v1.2.3 loses a source

    report = dispatch.verify_elements(repo)
    assert report["state"] == dispatch.SOURCE_MISSING
    by_version = {r["version"]: r["state"] for r in report["versions"]}
    assert by_version == {"1.2.3": dispatch.SOURCE_MISSING, "1.3.0": dispatch.DRIFT}


def test_empty_repo_is_a_match_not_a_crash(tmp_path):
    """No store and no elements is vacuously consistent — the gate must not invent a failure for a
    repo that has not vendored anything yet."""
    assert _state(tmp_path) == dispatch.MATCH
