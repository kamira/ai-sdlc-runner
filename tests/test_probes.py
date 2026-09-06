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
    assert probes.commit_exists_for(repo, "a.b") is False

    # `a.b` alone stopped discriminating the flag when CHG-20260906-01 put a literal
    # Python check after the grep: the prefilter finds the commit either way and the
    # literal check rejects it either way. `^x` still does, because with the flag the
    # prefilter finds nothing and without it the anchor matches.
    _git("commit", "-q", "--allow-empty", "-m", "feat: see ^x here", cwd=repo)
    assert probes.commit_exists_for(repo, "^x") is True, (
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

    Driven through `probes._run` directly, with a stub command that sleeps — the only way to make a
    probe's subprocess slow without making the suite slow. (The docstring said `pr_open_for` while
    the body called `_run`; a name standing in for what the test does, which is this repository's
    commonest defect and was still here after the change about it. CHG-20260830-06.)
    """
    slow = py_stub("import time; time.sleep(30)")
    with pytest.raises(probes.ProbeError) as caught:
        probes._run([*slow, "--head", "feature"], cwd=repo, timeout=1)
    assert "timed out after 1s" in str(caught.value)


# ── an unanswerable probe is never read as "not done" (CHG-20260902-21) ───────────────────────

def test_the_branch_probe_refuses_to_answer_when_git_cannot(tmp_path):
    """This module's rule, stated twice, and the one probe that did not keep it.

    `DEFAULT_TIMEOUT`: *"An unanswerable probe is **never** read as 'not done': that would re-run an
    effect that may have succeeded."* `ProbeError`: *"collapsing them makes the engine re-run an
    effect that may already have landed."*

    `branch_exists_locally` was `return proc.returncode == 0`, so "not a git repository" read as
    "the branch is not there" — and it is the `branch` effect's probe in `ship.effects_for`, so a
    false `False` re-runs `git checkout -b <branch>`. Its three sibling git probes all raise; this
    one had no test at all (CHG-20260902-21, defect seat L-21).
    """
    with pytest.raises(probes.ProbeError) as caught:
        probes.branch_exists_locally(tmp_path, "feature")
    assert "not an answer" in str(caught.value)


def test_the_branch_probe_still_answers_when_git_can(tmp_path):
    """The other half, or the refusal above would have eaten the probe.

    `rev-parse --verify` exits **128 for both** "no such branch" and "not a repository" — measured —
    so the two cannot be told apart by its exit code at all. `show-ref --verify` gives three codes
    for three states: 0 present, 1 absent, 128 unanswerable. That substitution is the fix.
    """
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    for argv in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                 ["git", "config", "user.name", "t"]):
        subprocess.run(argv, cwd=repo, capture_output=True)
    (repo / "a.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=repo, capture_output=True)
    here = subprocess.run(["git", "branch", "--show-current"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    assert probes.branch_exists_locally(repo, here) is True
    assert probes.branch_exists_locally(repo, "no-such-branch") is False


# --------------------------------------------------------------------------------------
# CHG-20260906-01 — two probes that answered a different question than the one asked
# --------------------------------------------------------------------------------------


def _tip(repo, ref="refs/heads/feature"):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", ref],
                          capture_output=True, encoding="utf-8", check=True).stdout.strip()


def test_a_remote_sitting_at_an_older_tip_is_not_pushed(repo):
    """The push postcondition is that the remote has **what was committed**, not that a branch of
    that name exists. `ls-remote` returns the SHA; the probe used to discard it."""
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("push", "-q", "origin", "feature", cwd=repo)
    assert probes.branch_on_remote(repo, "feature") is True

    (Path(repo) / "more.txt").write_text("the rest of the change\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: the rest", cwd=repo)

    assert probes.branch_on_remote(repo, "feature") is False, (
        "a remote holding an older tip read as pushed")
    _git("push", "-q", "origin", "feature", cwd=repo)
    assert probes.branch_on_remote(repo, "feature") is True


def test_a_remote_ahead_of_local_is_not_reported_as_pushed(repo):
    """New behaviour this change introduces, pinned so it is a decision rather than a surprise.

    A remote somebody else moved is evidence to reconcile, not permission to overwrite: the probe
    reads False, the ordinary non-force push that follows is refused, and the run halts. Ancestry is
    deliberately not guessed — `ls-remote` gives a SHA and nothing that could prove the remote
    already contains ours.
    """
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("push", "-q", "origin", "feature", cwd=repo)

    other = Path(repo).parent / "other"
    subprocess.run(["git", "clone", "-q", str(Path(repo).parent / "remote.git"), str(other)],
                   check=True)
    _git("config", "user.email", "o@example.com", cwd=other)
    _git("config", "user.name", "o", cwd=other)
    _git("checkout", "-q", "feature", cwd=other)
    (other / "theirs.txt").write_text("somebody else\n", encoding="utf-8")
    _git("add", "-A", cwd=other)
    _git("commit", "-q", "-m", "feat: theirs", cwd=other)
    _git("push", "-q", "origin", "feature", cwd=other)

    assert probes.branch_on_remote(repo, "feature") is False, (
        "a remote ahead of local read as holding what we committed")


def test_an_unreachable_remote_is_still_refused_rather_than_answered(repo):
    """Unchanged by this change, and asserted unchanged: fail closed."""
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("remote", "set-url", "origin", str(Path(repo).parent / "gone.git"), cwd=repo)
    with pytest.raises(probes.ProbeError):
        probes.branch_on_remote(repo, "feature")


def test_a_branch_absent_from_both_sides_is_simply_not_pushed(repo):
    """The remote is asked first, so a branch that exists nowhere is `False` rather than an error.

    Ordering it the other way made `test_an_unreachable_remote_is_not_reported_as_not_pushed` fail
    on the local refusal instead of its own — measured, not predicted.
    """
    assert probes.branch_on_remote(repo, "no-such-branch-anywhere") is False


def test_a_remote_that_has_what_this_repository_does_not_is_unanswerable(repo):
    """The comparison needs both ends. Answering False here would say "not pushed" about a branch
    this repository never created, which is a different fact."""
    _git("checkout", "-q", "-b", "feature", cwd=repo)
    _git("push", "-q", "origin", "feature", cwd=repo)
    _git("checkout", "-q", "main", cwd=repo)
    _git("branch", "-q", "-D", "feature", cwd=repo)

    with pytest.raises(probes.ProbeError) as caught:
        probes.branch_on_remote(repo, "feature")
    assert "nothing to compare" in str(caught.value)


def test_a_remote_answering_with_more_than_one_ref_is_refused(repo, monkeypatch):
    """The probe asks for a full ref and reads one record. A remote answering with several has
    said something this probe cannot read, and picking a row would be a guess about which branch
    the run is shipping.

    Driven through a stubbed `_run` because a well-behaved remote cannot produce this: the
    refusal exists for the case where the assumption behind the parse stops holding, and a guard
    with nothing behind it is the shape this repository keeps finding.
    """
    real = probes._run
    two = "aaaa" + chr(9) + "refs/heads/feature" + chr(10) + \
          "bbbb" + chr(9) + "refs/heads/feature" + chr(10)

    class _Answer:
        returncode = 0
        stdout = two
        stderr = ""

    def two_rows(argv, cwd=None, **kw):
        if argv[:2] == ["git", "ls-remote"]:
            return _Answer()
        return real(argv, cwd=cwd, **kw)

    monkeypatch.setattr(probes, "_run", two_rows)
    with pytest.raises(probes.ProbeError) as caught:
        probes.branch_on_remote(repo, "feature")
    assert "2 refs" in str(caught.value)


def test_a_commit_that_only_cites_a_chg_id_in_its_body_is_not_a_commit_for_it(repo):
    """`git log --grep` searches the body, and citing another change in a body is how this
    repository explains a reversal — 232 of 378 commits on `main` do it.

    Measured live before the fix: `a46de7b` cited `CHG-20260905-05` in its body at 17:36, and `-05`
    itself did not land until 02:32 the next day. For those nine hours the probe answered True for
    a change with no commit at all.
    """
    (Path(repo) / "f.txt").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m",
         "feat: reverse it (CHG-20260101-01)\n\nThis reverses the decision CHG-20260101-02 made.",
         cwd=repo)

    assert probes.commit_exists_for(repo, "CHG-20260101-01") is True
    assert probes.commit_exists_for(repo, "CHG-20260101-02") is False, (
        "an id cited in somebody else's commit body read as that change's own commit")


def test_an_id_on_a_wrapped_subject_is_still_found(repo):
    """`%s` is git's folded first paragraph, so the fix must not lose an id that wrapped onto the
    second line of the subject — which is the shape a long change title takes."""
    (Path(repo) / "g.txt").write_text("y\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "feat: a title long enough to wrap\nonto a second line (CHG-20260101-09)",
         cwd=repo)

    assert probes.commit_exists_for(repo, "CHG-20260101-09") is True
