"""The committed element tree matches the store it came from (CHG-20260822-04 task 3).

Task 3's done-when is one sentence — **no store version exists without elements** — and the check
here is the whole of it: enumerate the store, and for every version prove the committed tree exists,
regenerates byte-for-byte, and contains exactly the dispatch families that version's archive can
support.

Everything is enumerated from `skills/` at run time. There is deliberately **no list of versions**
in this file: the panel rejected both hand-maintained forms of that list (a per-version capability
baseline, and a frozen "legacy versions" list) because a table maintained beside the archive goes
stale silently while still looking authoritative — the KN-4 shape. `assets/` ships inside the
archive and is the only inventory consulted.

Task 4 turns the regeneration comparison into a CI gate with a three-state result; the property it
will gate on is asserted here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import dispatch, skillstore

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE_DIR = REPO_ROOT / "skills"


def _versions():
    if not STORE_DIR.is_dir():
        return []
    return skillstore.store_versions(STORE_DIR)


VERSIONS = _versions()
pytestmark = pytest.mark.skipif(not VERSIONS, reason="no vendored store in this checkout")


def _tree(root: Path):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


@pytest.mark.parametrize("version", VERSIONS)
def test_every_store_version_has_elements(version):
    """The done-when, literally. A store version with no elements is the state D2 forbids."""
    committed = dispatch.elements_dir(REPO_ROOT, version)
    assert committed.is_dir(), f"skills/v{version} has no elements/ tree"
    manifest = json.loads((committed / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["skill_version"] == version
    assert manifest["element_count"] > 0


@pytest.mark.parametrize("version", VERSIONS)
def test_committed_tree_regenerates_byte_for_byte(version, tmp_path):
    """The property task 4 will gate on: the tree *is* a function of the store, still.

    A difference here means one of two things and the message says which: the store changed without
    the elements being regenerated, or an element was edited by hand — which §2 of the guideline
    forbids as squarely as hand-copying skill markdown.
    """
    dispatch.emit_all(STORE_DIR / f"v{version}", tmp_path)
    fresh = _tree(tmp_path)
    committed = _tree(dispatch.elements_dir(REPO_ROOT, version))

    missing = sorted(set(fresh) - set(committed))
    extra = sorted(set(committed) - set(fresh))
    assert missing == [], f"v{version}: regeneration produces files not committed: {missing[:5]}"
    assert extra == [], f"v{version}: committed files no longer regenerate: {extra[:5]}"
    differing = sorted(n for n in fresh if fresh[n] != committed[n])
    assert differing == [], f"v{version}: {len(differing)} committed files differ: {differing[:5]}"


@pytest.mark.parametrize("version", VERSIONS)
def test_families_match_what_the_archive_supports(version):
    """Both directions are hard failures: a policy present means its family must exist, a policy
    absent means its family must not. The expectation is read off ``assets/``, never off a table."""
    skill = STORE_DIR / f"v{version}"
    supported = dispatch.supported_families(skill)
    cps = dispatch.checkpoints(skill)
    roles = dispatch.role_loadouts(skill)
    sits = dispatch.situational_sets(skill)

    assert bool([c for c in cps if c.namespace == "halt"]) is supported["halt"]
    assert bool([c for c in cps if c.namespace == "autopilot"]) is supported["autopilot"]
    assert bool(roles) is supported["roles"]
    assert bool(sits) is supported["roles"]          # situational lives in the same shipped file


@pytest.mark.parametrize("version", VERSIONS)
def test_committed_tree_has_no_dangling_ids(version):
    assert dispatch.check_dangling(STORE_DIR / f"v{version}") == []


@pytest.mark.parametrize("version", VERSIONS)
def test_committed_elements_are_lf_only(version):
    """`.gitattributes` pins ``elements/** text eol=lf``. Without it these check out CRLF on Windows
    while the blob stays LF, and the regeneration comparison above fails on half the CI matrix for a
    tree nobody touched — the shape of the CHG-20260817-09 defects."""
    for path in dispatch.elements_dir(REPO_ROOT, version).rglob("*"):
        if path.is_file():
            assert b"\r" not in path.read_bytes(), path


def test_no_version_is_hard_coded_in_the_generators():
    """fable's binding reservation on the round-3 verdict: if a per-version expectation table ever
    appears — even a one-line one — the derivation has stopped being read off the archive."""
    for module in ("decompose.py", "dispatch.py"):
        source = (REPO_ROOT / "src" / "ai_sdlc_runner" / module).read_text(encoding="utf-8")
        code = source.split('"""', 2)[2]
        for version in VERSIONS:
            assert f'"{version}"' not in code and f"'{version}'" not in code, (
                f"{module} hard-codes store version {version}")


def test_elements_live_beside_the_store_not_inside_it():
    """KN-1: ``skills/<version>/`` is a verbatim archive. Derived files inside it would break the
    one property the vendoring rests on, and the regeneration comparison along with it."""
    for version in VERSIONS:
        assert dispatch.elements_dir(REPO_ROOT, version).resolve() not in (
            STORE_DIR / f"v{version}").resolve().parents
        assert not (STORE_DIR / f"v{version}" / "elements").exists()
