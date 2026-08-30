"""What `ship.py` does when a step **fails** (CHG-20260830-03).

`ship` is the only module whose effects reach outside this machine, and the only one whose steps
are irreversible in the ordinary case. Measured with the harness: seven guarantees, and **four were
unpinned** — the worst ratio of the five modules measured.

All four are the same shape. The success paths were pinned by `test_kill_resume`, which drives the
sequence end to end and asserts what landed. Nothing drove a step that goes wrong, so every
guarantee about *refusing* was a sentence:

* a git command that returns non-zero
* a commit sitting over a dirty tree
* an effect asked for with no way to write its record
* a PR creation the forge rejected

A sequence that carries a change out and reports success on a failed push is worse than one that
does not run: the operator believes it landed.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import probes, ship  # noqa: E402


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    """A real repository, because these guarantees are about what git actually returned."""
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@example.com", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "chore: initial", cwd=work)
    return work


# ── a git command that failed ──────────────────────────────────────────────────────────────────


def test_a_git_command_that_fails_raises_rather_than_passing(repo):
    """`_git` checks the return code, and nothing pinned that it does.

    Removing the check left every test green — and the step that would then report success is
    `push`. An operator told a change shipped, whose branch never left the machine, is the failure
    this whole sequence exists to make impossible.
    """
    with pytest.raises(ship.ShipError) as caught:
        ship._git(repo, "checkout", "no-such-branch-anywhere")

    said = str(caught.value)
    assert "git checkout" in said, "the refusal must name the command that failed"
    assert said.strip() != "git checkout no-such-branch-anywhere failed:", (
        "the refusal dropped git's own reason, which is the only actionable part")
def test_a_commit_over_a_dirty_tree_is_not_finished(repo):
    """Both halves of the probe, deliberately — the comment says why and nothing held it.

    *"A commit that exists while the tree is still dirty did not finish recording the change, and a
    resume that treats it as done pushes half of it."* Dropping `working_tree_clean` from the probe
    left every test green.
    """
    (repo / "one.txt").write_text("a", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: CHG-20260830-03 the first half", cwd=repo)
    (repo / "two.txt").write_text("b", encoding="utf-8")          # left uncommitted

    sequence = ship.effects_for(repo, "CHG-20260830-03", "feature", "feat: x", write_chg=lambda: None)
    commit = next(e for e in sequence if e.name == "commit")

    assert probes.commit_exists_for(repo, "CHG-20260830-03") is True
    assert probes.working_tree_clean(repo) is False
    assert commit.probe() is False, "a dirty tree read as a finished commit"


def test_a_commit_with_a_clean_tree_is_finished(repo):
    (repo / "one.txt").write_text("a", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: CHG-20260830-03 all of it", cwd=repo)

    sequence = ship.effects_for(repo, "CHG-20260830-03", "feature", "feat: x", write_chg=lambda: None)
    assert next(e for e in sequence if e.name == "commit").probe() is True


# ── the runner does not invent a governance record ─────────────────────────────────────────────


def test_an_effect_with_no_writer_refuses_instead_of_doing_nothing(repo):
    """*"This runner will not invent the content of a governance record."*

    `_refuse` returns a function that raises. Replacing it with one that does nothing left every
    test green — and the effect would then report success having written no record at all, which is
    the shape CHG-20260828-15 found at `record_module`: a run claiming work it never did.
    """
    sequence = ship.record_effects(repo, "CHG-20260830-03", task="3", tick=None)
    tick = next(e for e in sequence if e.name == "tick")

    with pytest.raises(ship.ShipError) as caught:
        tick.apply()

    said = str(caught.value)
    assert "will not invent" in said
    assert "CHG-20260830-03" in said, "the refusal must say which record it was asked to write"


def test_an_acceptance_with_no_writer_refuses_too(repo):
    """The second caller of `_refuse`, so the guarantee is not pinned at one site only."""
    sequence = ship.record_effects(repo, "CHG-20260830-03", task="3",
                                   acc_id="ACC-20260830-03", tick=lambda: None, write_acc=None)
    acceptance = next(e for e in sequence if e.name == "acceptance")

    with pytest.raises(ship.ShipError, match="will not invent"):
        acceptance.apply()


def test_a_supplied_writer_is_used_and_not_refused(repo):
    """The over-refusal direction: a refusal that fires when a writer *was* supplied is worse."""
    written = []
    sequence = ship.record_effects(repo, "CHG-20260830-03", task="3",
                                   tick=lambda: written.append("ticked"))
    next(e for e in sequence if e.name == "tick").apply()
    assert written == ["ticked"]


# ── a PR the forge refused ─────────────────────────────────────────────────────────────────────


def test_a_pr_the_forge_rejects_is_not_reported_as_opened(repo, tmp_path):
    """`_create_pr` checks the return code. Dropping the check left every test green.

    The forge is a script that exits non-zero, which is what `gh` does when the PR cannot be made —
    no remote, no auth, a branch it cannot see. Reporting that as opened ends the sequence with the
    operator believing a review is waiting for somebody.
    """
    forge = tmp_path / "forge.py"
    forge.write_text("import sys\nsys.stderr.write('the forge said no\\n')\nsys.exit(1)\n",
                     encoding="utf-8")

    with pytest.raises(ship.ShipError) as caught:
        ship._create_pr(repo, "feature", "a title", [sys.executable, str(forge)])

    said = str(caught.value)
    assert "could not open a PR for feature" in said
    assert "the forge said no" in said, "the forge's own reason is the actionable part"
