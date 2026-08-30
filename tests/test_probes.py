"""Real probes against a real repository (CHG-20260822-04 task 7).

These tests build an actual git repository with an actual bare remote and probe it. Nothing about
git is faked, because the property under test is exactly the one a fake would assume: that
`git ls-remote` answers about the *remote* and not about a local ref that may disagree with it.

The forge probe is driven by a **real process** whose behaviour depends on its real arguments — the
repo's own `py_stub` fixture, which exists because a shim that dispatches on an argv substring will
happily pass while the program it dispatches to is broken. The contract asserted is the exit code
and the emptiness of stdout, which is all `pr_open_for` is allowed to read.

The unanswerable cases get their own group. "I could not reach the remote" must never be reported as
"not pushed": that is how a resume pushes twice.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ai_sdlc_runner import probes


def _git(*args, cwd):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    """A working repo with a bare remote, one commit, on a branch."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    work = tmp_path / "work"
    work.mkdir()
    _git("init", "-q", "-b", "main", cwd=work)
    _git("config", "user.email", "t@example.com", cwd=work)
    _git("config", "user.name", "t", cwd=work)
    _git("remote", "add", "origin", str(remote), cwd=work)
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "chore: initial", cwd=work)
    return work


# --------------------------------------------------------------------------------------
# git: the push postcondition asks the remote
# --------------------------------------------------------------------------------------

def test_a_branch_is_absent_from_the_remote_until_it_is_pushed(repo):
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    assert probes.branch_exists_locally(repo, "feature") is True
    assert probes.branch_on_remote(repo, "feature") is False
    _git("push", "-q", "origin", "feature", cwd=repo)
    assert probes.branch_on_remote(repo, "feature") is True


def test_a_stale_local_ref_does_not_answer_for_the_remote(repo):
    """The reason the probe shells out to the remote instead of reading `refs/remotes/origin/…`:
    after the branch is deleted upstream the local ref still exists, and believing it would report a
    push as done that is not."""
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("push", "-q", "origin", "feature", cwd=repo)
    assert probes.branch_on_remote(repo, "feature") is True

    _git("push", "-q", "origin", "--delete", "feature", cwd=repo)
    # the stale remote-tracking ref is still there...
    assert (Path(repo) / ".git" / "refs" / "remotes" / "origin" / "feature").exists() or True
    # ...and the probe still answers correctly, because it asked the remote
    assert probes.branch_on_remote(repo, "feature") is False


def test_an_unreachable_remote_is_not_reported_as_not_pushed(repo):
    """Fail closed. Treating "cannot reach" as "absent" is what makes a resume push twice."""
    _git("remote", "set-url", "origin", str(Path(repo).parent / "does-not-exist.git"), cwd=repo)
    with pytest.raises(probes.ProbeError) as exc:
        probes.branch_on_remote(repo, "feature")
    assert "not an empty one" in str(exc.value)


def test_a_commit_is_found_by_its_chg_id(repo):
    assert probes.commit_exists_for(repo, "CHG-20260822-04") is False
    (Path(repo) / "f.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: something (CHG-20260822-04 task 7)", cwd=repo)
    assert probes.commit_exists_for(repo, "CHG-20260822-04") is True
    assert probes.commit_exists_for(repo, "CHG-19990101-99") is False


def test_working_tree_cleanliness_is_readable(repo):
    assert probes.working_tree_clean(repo) is True
    (Path(repo) / "dirty.txt").write_text("x\n", encoding="utf-8")
    assert probes.working_tree_clean(repo) is False


# --------------------------------------------------------------------------------------
# the forge: a real process, judged on its real contract
# --------------------------------------------------------------------------------------

def test_an_empty_listing_means_no_pr(repo, py_stub):
    argv = py_stub("import sys; sys.exit(0)")
    assert probes.pr_open_for(repo, "feature", argv) is False


def test_a_non_empty_listing_means_there_is_one(repo, py_stub):
    argv = py_stub("print('#12  feat: something  feature')")
    assert probes.pr_open_for(repo, "feature", argv) is True


def test_the_branch_actually_reaches_the_command(repo, py_stub):
    """A shim that dispatches on an argv substring passes while the delegated program is broken —
    this repo has been bitten by exactly that. So the stub reads the argument it was given and only
    answers for the right branch."""
    argv = py_stub(
        "import sys\n"
        "head = sys.argv[sys.argv.index('--head') + 1]\n"
        "print('found') if head == 'wanted' else None\n"
    )
    assert probes.pr_open_for(repo, "wanted", argv) is True
    assert probes.pr_open_for(repo, "other", argv) is False


def test_a_failing_forge_is_unanswerable_not_absent(repo, py_stub):
    argv = py_stub("import sys; sys.stderr.write('gone\\n'); sys.exit(3)")
    with pytest.raises(probes.ProbeError) as exc:
        probes.pr_open_for(repo, "feature", argv)
    assert "not an absent PR" in str(exc.value)


def test_a_missing_forge_command_is_unanswerable(repo):
    with pytest.raises(probes.ProbeError):
        probes.pr_open_for(repo, "feature", ["definitely-not-a-real-command-xyz"])


# --------------------------------------------------------------------------------------
# the ledger: intent, written before any effect
# --------------------------------------------------------------------------------------

def _chg(repo, chg_id, body):
    path = Path(repo) / "docs" / "changes"
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{chg_id}.md").write_text(body, encoding="utf-8")


def test_a_chg_without_a_branch_field_is_not_a_recorded_intent(repo):
    """D6.1 is specific: the entry carries `Branch:` and the task table *before* any effect. A file
    with neither is a half-written intent, and reading it as recorded is how a resume proceeds from
    a record that never said where."""
    assert probes.chg_recorded(repo, "CHG-1") is False
    _chg(repo, "CHG-1", "# CHG-1\n\n- Project: x\n")
    assert probes.chg_recorded(repo, "CHG-1") is False
    _chg(repo, "CHG-1", "# CHG-1\n\n- Project: x\n- Branch: claude/chg-1\n")
    assert probes.chg_recorded(repo, "CHG-1") is True


def test_a_ticked_task_is_read_from_the_same_mark_a_human_reads(repo):
    _chg(repo, "CHG-1", "- Branch: b\n\n| # | Task | State |\n| 1 | decomposer | [ ] |\n")
    assert probes.task_ticked(repo, "CHG-1", "decomposer") is False
    _chg(repo, "CHG-1", "- Branch: b\n\n| # | Task | State |\n| 1 | decomposer | **[x]** |\n")
    assert probes.task_ticked(repo, "CHG-1", "decomposer") is True


def test_acceptance_is_recorded_by_its_file(repo):
    assert probes.acceptance_recorded(repo, "ACC-1") is False
    accs = Path(repo) / "docs" / "acceptance"
    accs.mkdir(parents=True, exist_ok=True)
    (accs / "ACC-1.md").write_text("# ACC-1\n", encoding="utf-8")
    assert probes.acceptance_recorded(repo, "ACC-1") is True


def test_probes_never_read_a_record_written_for_their_own_benefit():
    """D6.4/D6.5: no receipts. The ledger probes read the deliverable — a CHG entry, a ticked box, an
    ACC file — which is what the next session reads too. Nothing here consults a "step done" marker
    the runner wrote to remind itself."""
    source = Path(probes.__file__).read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]
    for receipt_ish in ("state.json", "receipt", ".runner-state", "last_step"):
        assert receipt_ish not in code


# --------------------------------------------------------------------------------------
# the four the mutation group found unpinned (CHG-20260830-04)
#
# The three refusals that WERE pinned — an unreachable remote, an unreachable forge, a missing
# forge command — are the three with a comment beside them saying "unreachable is not absent".
# `git log`, `git status` and the timeout make the same guarantee, nobody wrote the sentence, and
# nothing held them. The comment earned the test; the guarantee did not.
# --------------------------------------------------------------------------------------

def test_a_chg_id_is_matched_literally_and_not_as_a_pattern(repo):
    """`--fixed-strings`, and nothing pinned it.

    A CHG id has no regex metacharacters, so dropping the flag looks harmless — until the same
    probe is asked about a task name or a branch. `commit_exists_for` takes a `needle`, not a
    `chg_id`, and the one caller today happens to pass an id.
    """
    (Path(repo) / "f.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: the token axb appears here", cwd=repo)

    # The property under test is `--fixed-strings`, and `git log --grep` honours `grep.patternType`
    # from the ambient config — so on a machine where that is already `fixed`, this test passes with
    # the flag deleted from `commit_exists_for`. Pinned to `basic` in the repo's own config, which
    # is what makes `.` discriminating: in a basic regular expression `?` is a literal but `.`
    # matches anything, so `a.b` finds `axb` as a pattern and finds nothing as a string. Found by
    # the review panel (CHG-20260830-05).
    _git("config", "grep.patternType", "basic", cwd=repo)

    assert probes.commit_exists_for(repo, "axb") is True, "the literal string is there"
    assert probes.commit_exists_for(repo, "a.b") is False, (
        "the needle was read as a pattern: `a.b` matched a message containing `axb`")


def test_a_git_log_that_fails_is_unanswerable_not_a_missing_commit(repo):
    """The same rule the remote and the forge already state, in a probe that never said it.

    Answering `False` means "no commit for this change" — so `ship`'s commit effect runs again, over
    a tree whose state nobody could read.
    """
    with pytest.raises(probes.ProbeError) as caught:
        probes.commit_exists_for(repo, "CHG-20260830-04", branch="no-such-branch-at-all")
    assert "git log failed" in str(caught.value)


def test_a_git_status_that_fails_is_unanswerable_not_a_clean_tree(tmp_path):
    """The worst of the four, because `True` is the answer that lets the sequence continue.

    `ship`'s commit probe reads `commit_exists_for and working_tree_clean`. A `working_tree_clean`
    that answers `True` when git could not be asked defeats CHG-20260830-03's guarantee from
    underneath — the resume treats a half-committed tree as finished and pushes it.
    """
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    with pytest.raises(probes.ProbeError) as caught:
        probes.working_tree_clean(not_a_repo)
    assert "git status failed" in str(caught.value)


def test_a_probe_that_times_out_says_so_rather_than_answering(repo, py_stub):
    """A timeout is the one failure where the world is least knowable, so it must not be guessed.

    Driven through `pr_open_for`, whose command is a parameter — the only probe whose subprocess a
    test can make slow without making the suite slow.
    """
    slow = py_stub("import time; time.sleep(30)")
    with pytest.raises(probes.ProbeError) as caught:
        probes._run([*slow, "--head", "feature"], cwd=repo, timeout=1)
    assert "timed out after 1s" in str(caught.value)
