"""The guideline says what the runner actually holds (CHG-20260822-04 task 8).

Task 8's done-when is "guideline is truthful about what the runner now holds", and a document is a
poor place to keep a promise: it is exactly the artifact that goes stale silently while everything
around it moves. So the claims are checked here instead of re-read by hand.

Two kinds of claim are checked. **Structural** ones — the override exists, is narrow, names its fork
points, and CI really does regenerate and compare — are asserted against the files that would have to
change for them to stop being true. **Measured** ones are recomputed from the store: if a future
vendoring changes the corpus, the number in the guideline fails here rather than quietly becoming a
number nobody re-derived.

The fork-point index gets the same treatment as the count itself: an index that lists eight and a
codebase that names seven is the failure this file exists to catch.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDELINE = REPO_ROOT / "docs" / "ai-guideline.md"
STORE = REPO_ROOT / "skills" / "v1.64.0"

pytestmark = pytest.mark.skipif(
    not (STORE / "references").is_dir(),
    reason="vendored store not present in this checkout",
)


@pytest.fixture(scope="module")
def guideline() -> str:
    return GUIDELINE.read_text(encoding="utf-8")


def _real_headings(paths):
    """Headings outside fenced blocks, and the ones inside — the split fork point 1 rests on."""
    outside = inside = 0
    heading = re.compile(r"^###? ")
    for path in paths:
        fence = False
        for line in path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
            if line.lstrip().startswith("```"):
                fence = not fence
                continue
            if heading.match(line):
                if fence:
                    inside += 1
                else:
                    outside += 1
    return outside, inside


# --------------------------------------------------------------------------------------
# the override is present, and it is narrow
# --------------------------------------------------------------------------------------

def test_the_prohibition_still_stands_for_hand_written_text(guideline):
    """The override must not read as a repeal. §2 still forbids copying; what it now permits is
    deterministic derivation, and only that."""
    assert "Copying any skill markdown into the runner." in guideline
    assert "Narrowly overridden, CHG-20260822-04" in guideline
    assert "deterministically derived" in guideline
    assert "hand" in guideline.split("Narrowly overridden")[1][:400]


def test_the_derived_artifact_baseline_exists_and_names_its_scope(guideline):
    # the *last* mention is §6's entry; the first is §2's pointer at it
    section = guideline.split("Derived-artifact baseline")[-1][:2000]
    assert "elements/v<version>/" in section
    assert "deterministically derived artifacts only" in section


def test_stale_success_criteria_were_swept_not_left_standing(guideline):
    """§1 claimed the runner "references — never copies — the skill via a pinned submodule" and that
    it runs the four stages. Both stopped being the whole truth; a struck line with the reason is
    the honest form, an unmarked one is a document quietly lying."""
    intro = guideline.split("## 2. Scope")[0]
    assert "~~references — never copies — the skill via a pinned submodule~~" in intro
    assert "--engine" in intro
    assert "the runner now *holds* skill text" in intro


def test_the_maintainability_claim_distinguishes_logic_from_text(guideline):
    row = next(line for line in guideline.splitlines() if line.startswith("| Maintainability |"))
    assert "logic" in row and "text" in row
    assert "regenerates and byte-compares" in row


# --------------------------------------------------------------------------------------
# the fork-point index is complete and matches the code
# --------------------------------------------------------------------------------------

def _index_rows(guideline):
    block = guideline.split("the full\n  index.")[1].split("Fork points 1–5")[0]
    return [ln for ln in block.splitlines() if re.match(r"\s*\| \d+ \|", ln)]


def test_the_index_lists_every_fork_point_exactly_once(guideline):
    rows = _index_rows(guideline)
    numbers = [int(re.match(r"\s*\| (\d+) \|", r).group(1)) for r in rows]
    assert numbers == list(range(1, len(numbers) + 1)), "the index is not a contiguous list"
    assert len(numbers) == 8


def test_every_fork_point_that_claims_a_location_has_one(guideline):
    """A fork point pointing at a file that does not name one is an index describing a codebase that
    no longer exists."""
    for row in _index_rows(guideline):
        for module in ("decompose.py", "dispatch.py", "graph.py"):
            if f"`{module}`" in row:
                source = (REPO_ROOT / "src" / "ai_sdlc_runner" / module).read_text(encoding="utf-8")
                assert "fork point" in source.lower(), f"{module} claims a fork point but names none"


def test_the_open_fork_point_is_still_open(guideline):
    """Number 6 is deliberately undecided. If a future change resolves it, this fails and the index
    gets updated rather than keeping a stale 'deferred'."""
    row = next(r for r in _index_rows(guideline) if r.strip().startswith("| 6 |"))
    assert "*deferred*" in row
    proc = subprocess.run([sys.executable, str(STORE / "scripts" / "autopilot_runner.py"), "--help"],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "lib" in proc.stderr, "the shipped resolver imports now — fork point 6 can be closed"


# --------------------------------------------------------------------------------------
# the measured claims, recomputed
# --------------------------------------------------------------------------------------

def test_the_fenced_heading_measurement_still_holds(guideline):
    english = [p for p in sorted((STORE / "references").glob("*.md"))
               if not p.name.endswith(".zh-tw.md")]
    outside, inside = _real_headings(english)
    assert f"{inside} of {outside + inside}" in guideline, (
        f"the guideline's fenced-heading count is stale: measured {inside} of {outside + inside}")


def test_the_corpus_heading_count_still_holds(guideline):
    outside, _ = _real_headings(sorted((STORE / "references").glob("*.md")))
    assert f"{outside} real headings" in guideline, (
        f"the guideline's heading count is stale: measured {outside}")


def test_the_line_ending_claim_matches_gitattributes(guideline):
    attrs = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto" in attrs
    assert "elements/** text eol=lf" in attrs
    assert "`* text=auto`" in guideline


def test_ci_really_regenerates_and_compares(guideline):
    """§8 says derived artifacts are regenerated and byte-compared in CI. The job has to exist for
    that sentence to be true."""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "elements (regeneration gate)" in workflow
    assert "runner elements" in workflow
    assert "byte-compared in CI" in guideline


def test_the_element_tree_exists_for_every_store_version():
    """The guideline describes `elements/v<version>/` as a thing the runner holds. It has to be one."""
    versions = [d.name for d in (REPO_ROOT / "skills").glob("v*") if d.is_dir()]
    assert versions
    for version in versions:
        assert (REPO_ROOT / "elements" / version / "manifest.json").is_file(), version
