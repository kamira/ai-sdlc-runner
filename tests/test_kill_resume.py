"""Kill a run mid-sequence and resume it (CHG-20260822-04 task 7).

The done-when, and the one test the whole idempotence design was written for: interrupt between two
ordered effects and prove the engine resumes at the right frontier.

Nothing here is simulated at the point that matters. A **real subprocess** runs the real
`ship.effects_for` sequence against a **real git repository** with a real bare remote, and is killed
with `os._exit`, which runs no cleanup at all — no `finally`, no `atexit`, no flush. That is what a
crash is, and it is why an in-process exception is not an adequate stand-in: an exception unwinds,
and unwinding is exactly the courtesy a killed process does not extend.

The forge is a real process too, holding its PR list in a file, so "is there a PR" is answered by
something outside the run. A stub that answered from memory would be answering from the very state
the kill is supposed to destroy.

The window under test is the one that decided the design: killed **between `git push` and
`gh pr create`**. The branch is on the remote, the PR is not, so the frontier is exactly "PR not
created" — and the resume must create the PR *and nothing else*.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ai_sdlc_runner import probes

REPO_ROOT = Path(__file__).resolve().parents[1]

#: A forge that keeps its PRs in a file, so the answer survives the process being killed.
FORGE = '''
import json, sys
from pathlib import Path

store = Path(sys.argv[1])
args = sys.argv[2:]
prs = json.loads(store.read_text()) if store.is_file() else []
head = args[args.index("--head") + 1] if "--head" in args else None
if "create" in args:
    prs.append(head)
    store.write_text(json.dumps(prs))
    print(f"created PR for {head}")
else:
    for pr in prs:
        if pr == head:
            print(f"#1 {pr}")
'''

#: The run under test: the real ship sequence, optionally dying immediately after a named effect.
RUNNER = '''
import json, os, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from ai_sdlc_runner import effects, ship

repo, chg, branch, forge, store, die_after = sys.argv[2:8]
py = sys.executable

def write_chg():
    d = Path(repo) / "docs" / "changes"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{chg}.md").write_text(f"# {chg}\\n\\n- Branch: {branch}\\n", encoding="utf-8")

seq = ship.effects_for(
    repo, chg, branch, f"feat: the thing ({chg})", write_chg,
    gh_list=[py, forge, store, "list"], gh_create=[py, forge, store, "create"],
)

if die_after:
    # Run by hand up to and including `die_after`, then vanish. os._exit runs no cleanup: no
    # finally, no atexit, no flush — which is the point.
    for effect in seq:
        if not effect.probe():
            effect.apply()
        if effect.name == die_after:
            os._exit(9)

outcome = effects.run(seq)
print(json.dumps(outcome.as_dict()))
'''


def _git(*args, cwd):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)}: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def scene(tmp_path):
    """A repo with a bare remote, a file-backed forge, and the two scripts."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    repo = tmp_path / "work"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    _git("remote", "add", "origin", str(remote), cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "chore: initial", cwd=repo)

    forge = tmp_path / "forge.py"
    forge.write_text(FORGE, encoding="utf-8")
    runner = tmp_path / "runner_script.py"
    runner.write_text(RUNNER, encoding="utf-8")
    return {"repo": repo, "forge": forge, "runner": runner,
            "store": tmp_path / "prs.json", "remote": remote}


def _run(scene, die_after=""):
    return subprocess.run(
        [sys.executable, str(scene["runner"]), str(REPO_ROOT / "src"), str(scene["repo"]),
         "CHG-20260822-04", "feature", str(scene["forge"]), str(scene["store"]), die_after],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
    )


def _gh(scene):
    return [sys.executable, str(scene["forge"]), str(scene["store"]), "list"]


# --------------------------------------------------------------------------------------
# the window the design was written for
# --------------------------------------------------------------------------------------

def test_killed_between_push_and_pr_the_resume_creates_only_the_pr(scene):
    killed = _run(scene, die_after="push")
    assert killed.returncode == 9, killed.stderr

    repo = scene["repo"]
    assert probes.branch_on_remote(repo, "feature") is True      # push landed
    assert probes.pr_open_for(repo, "feature", _gh(scene)) is False   # PR did not

    resumed = _run(scene)
    assert resumed.returncode == 0, resumed.stderr
    outcome = json.loads(resumed.stdout.strip().splitlines()[-1])

    assert outcome["frontier"] == "pr"
    assert outcome["applied"] == ["pr"]
    assert outcome["already_met"] == ["record-intent", "branch", "commit", "push"]
    assert probes.pr_open_for(repo, "feature", _gh(scene)) is True


@pytest.mark.parametrize("die_after,expected_frontier,expected_applied", [
    ("record-intent", "branch", ["branch", "commit", "push", "pr"]),
    ("branch", "commit", ["commit", "push", "pr"]),
    ("commit", "push", ["push", "pr"]),
    ("push", "pr", ["pr"]),
])
def test_a_kill_after_any_effect_resumes_at_the_next_one(scene, die_after, expected_frontier,
                                                         expected_applied):
    """Not just the push/PR window: every boundary in the sequence, so the property is the
    sequence's and not one hand-tuned case."""
    assert _run(scene, die_after=die_after).returncode == 9

    resumed = _run(scene)
    assert resumed.returncode == 0, resumed.stderr
    outcome = json.loads(resumed.stdout.strip().splitlines()[-1])
    assert outcome["frontier"] == expected_frontier
    assert outcome["applied"] == expected_applied


def test_a_completed_run_is_a_no_op_when_run_again(scene):
    """Running the whole thing twice must not open a second PR. The forge holds its list in a file,
    so a duplicate would be visible rather than swallowed by an idempotent test double."""
    first = _run(scene)
    assert first.returncode == 0, first.stderr

    second = _run(scene)
    assert second.returncode == 0, second.stderr
    outcome = json.loads(second.stdout.strip().splitlines()[-1])
    assert outcome["frontier"] is None
    assert outcome["applied"] == []

    assert json.loads(scene["store"].read_text()) == ["feature"]   # exactly one PR


def test_the_kill_leaves_no_partial_intent_unrecorded(scene):
    """D6.1: intent lands before any effect. Killing right after the first effect must still leave a
    CHG that names its branch — otherwise the resume would proceed from a record that never said
    where the work was going."""
    assert _run(scene, die_after="record-intent").returncode == 9
    assert probes.chg_recorded(scene["repo"], "CHG-20260822-04") is True
    assert probes.branch_exists_locally(scene["repo"], "feature") is False


def test_the_forge_answers_from_outside_the_killed_process(scene):
    """The stub is a separate process with file-backed state on purpose: an in-memory double would
    be answering from the very state the kill is meant to destroy."""
    assert _run(scene, die_after="push").returncode == 9
    assert not scene["store"].is_file() or json.loads(scene["store"].read_text()) == []
    assert _run(scene).returncode == 0
    assert json.loads(scene["store"].read_text()) == ["feature"]
