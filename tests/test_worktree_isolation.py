"""A module is a commit, and each module builds in a tree cut from the last one
(CHG-20260827-21, step one).

The first attempt at this change shipped nothing, and the record says why: a tree per module
**deleted the run's output while reporting success**, and module N+1 could not see module N. Both
were reproduced rather than argued. Step one was marked blocked on a question only a person could
answer — *is a module a commit?* — and the operator answered **yes**.

That answer is the whole design:

* each module's tree is cut from `Trees.tip`, which starts at `HEAD`;
* when the loop moves on, the finished module is **committed** and the tip advances;
* so the next tree is cut from the previous module's work, and N+1 sees N.

## Source becomes commits; artifacts become files

`.gitignore` is the project saying which files are not repository content. A runner that force-added
them would be overriding that on the project's behalf, so `finish` commits **tracked content only**
and `carry` copies the ignored-but-created files into the working tree — which is where a build
normally leaves them. `examples/minimal/greet.py` is exactly that case, and the reason the first
attempt lost it.

## What decides that the last module is committed

Every module but the last is committed when the next asks for a tree: by then the loop is past
`record_module`, so it is finished by construction. The last has nothing after it, so it is
committed only if `report.visited` says `record_module` was reached — a build that halted at
`halt_second_fail` must not be committed as though it had passed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import worktree  # noqa: E402

pytestmark = pytest.mark.skipif(worktree.available(".") is None,
                                reason="needs git and a working tree; the isolation has none "
                                       "without one and says so rather than pretending")


def _repo(tmp_path: Path) -> Path:
    """A real repository, because every claim here is about what git actually does."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args):
        done = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
        assert done.returncode == 0, f"git {args}: {done.stderr}"

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (root / ".gitignore").write_text("*.artifact\n", encoding="utf-8")
    (root / "start.txt").write_text("one\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "start")
    return root


def _sha(root: Path, rev: str = "HEAD") -> str:
    return subprocess.run(["git", "rev-parse", rev], cwd=str(root),
                          capture_output=True, text=True).stdout.strip()


# ── the chain ───────────────────────────────────────────────────────────────────────────────────

def test_a_module_that_writes_source_becomes_a_commit(tmp_path):
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    where = trees.path_for(worktree.key_for(1))
    (Path(where) / "built.py").write_text("# one\n", encoding="utf-8")

    sha = trees.finish(worktree.key_for(1))
    assert sha, "a module that wrote tracked source must produce a commit"
    assert trees.tip == sha
    assert trees.commits == [(worktree.key_for(1), sha, "module-001: built.py")]


def test_the_next_module_is_cut_from_the_previous_ones_commit(tmp_path):
    """The defect that blocked this change, now the mechanism that fixes it."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)

    one = trees.path_for(worktree.key_for(1))
    (Path(one) / "built.py").write_text("# one\n", encoding="utf-8")

    two = trees.path_for(worktree.key_for(2))          # commits module 1, then cuts from it
    assert (Path(two) / "built.py").is_file(), "module 2 cannot see module 1's finished work"
    assert len(trees.commits) == 1, "module 1 should have been committed exactly once"


def test_a_module_still_cannot_see_the_next_ones_half_finished_state(tmp_path):
    """The property the isolation is *for*, which the commit chain must not undo.

    Module 1 sees nothing of module 2 — the chain only ever runs forwards.
    """
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    one = trees.path_for(worktree.key_for(1))
    (Path(one) / "built.py").write_text("# one\n", encoding="utf-8")
    two = trees.path_for(worktree.key_for(2))
    (Path(two) / "later.py").write_text("# two, mid-flight\n", encoding="utf-8")

    assert not (Path(one) / "later.py").exists()


def test_a_module_that_changed_nothing_is_not_a_commit(tmp_path):
    """Not an error, and not history either. An empty commit per idle module would make the log
    say work happened that did not."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    trees.path_for(worktree.key_for(1))
    before = trees.tip

    assert trees.finish(worktree.key_for(1)) is None
    assert trees.tip == before
    assert trees.commits == []


# ── source versus artifacts ─────────────────────────────────────────────────────────────────────

def test_an_ignored_file_is_not_committed(tmp_path):
    """`.gitignore` is the project saying what is not repository content, and the runner does not
    overrule it."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    where = trees.path_for(worktree.key_for(1))
    (Path(where) / "out.artifact").write_text("built\n", encoding="utf-8")

    assert trees.finish(worktree.key_for(1)) is None, "an ignored file is not a commit"
    assert trees.artifacts(worktree.key_for(1)) == ["out.artifact"]


def test_an_artifact_is_carried_into_the_working_tree(tmp_path):
    """Where a build normally leaves it — and the file the first attempt at this change deleted."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    where = trees.path_for(worktree.key_for(1))
    (Path(where) / "out.artifact").write_text("built\n", encoding="utf-8")

    assert trees.carry() == ["out.artifact"]
    assert (root / "out.artifact").read_text(encoding="utf-8") == "built\n"
    assert trees.not_carried == []


def test_a_later_modules_artifact_wins(tmp_path):
    """The same rule a later commit follows, so the two halves of a build agree about order."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    one = trees.path_for(worktree.key_for(1))
    (Path(one) / "out.artifact").write_text("first\n", encoding="utf-8")
    two = trees.path_for(worktree.key_for(2))
    (Path(two) / "out.artifact").write_text("second\n", encoding="utf-8")

    trees.carry()
    assert (root / "out.artifact").read_text(encoding="utf-8") == "second\n"


# ── landing ─────────────────────────────────────────────────────────────────────────────────────

def test_the_commits_fast_forward_the_operators_branch(tmp_path):
    root = _repo(tmp_path)
    started = _sha(root)
    trees = worktree.Trees(root)
    where = trees.path_for(worktree.key_for(1))
    (Path(where) / "built.py").write_text("# one\n", encoding="utf-8")
    trees.finish(worktree.key_for(1))

    said = trees.land("ai-sdlc/test")
    assert "fast-forwarded" in said, said
    assert _sha(root) != started
    assert (root / "built.py").is_file(), "a fast-forward must update the working tree too"


def test_a_branch_that_moved_gets_the_work_on_its_own_branch_instead(tmp_path):
    """The operator's branch is theirs. It moves only when moving it discards nothing, and `git`
    answers that question rather than this code guessing at it."""
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    where = trees.path_for(worktree.key_for(1))
    (Path(where) / "built.py").write_text("# one\n", encoding="utf-8")
    trees.finish(worktree.key_for(1))

    # the operator commits something of their own while the run was going
    (root / "theirs.txt").write_text("mine\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "theirs"], cwd=str(root), capture_output=True)
    theirs = _sha(root)

    said = trees.land("ai-sdlc/test")
    assert "ai-sdlc/test" in said, said
    assert "not fast-forwarded because" in said, "an operator must be told why, not just where"
    assert _sha(root) == theirs, "their branch must not move"
    assert _sha(root, "ai-sdlc/test") == trees.tip


def test_a_run_that_built_nothing_says_nothing(tmp_path):
    root = _repo(tmp_path)
    trees = worktree.Trees(root)
    trees.path_for(worktree.key_for(1))
    assert trees.land("ai-sdlc/test") == ""


# ── through the real CLI ────────────────────────────────────────────────────────────────────────

def test_the_shipped_example_still_finishes_and_leaves_its_output(tmp_path):
    """The regression the first attempt caused: `state: finished` with the work deleted."""
    repo = Path(__file__).resolve().parents[1]
    target = repo / "examples" / "minimal" / "greet.py"
    if target.exists():
        target.unlink()

    done = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(repo / "examples/minimal/runner.yaml"),
         "run", "--plan", str(repo / "examples/minimal/plan.json"),
         "--risk", "low", "--confirm", "merge",
         "--ask-journal", str(tmp_path / "asks")],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(repo / "src"), "PYTHONUTF8": "1"}, timeout=900)
    out = (done.stdout or "") + (done.stderr or "")

    assert "state:         finished" in out, out[-800:]
    assert target.is_file(), (
        "the run reported success and left no output — the exact defect that blocked this change:\n"
        + out[-800:])
    assert "artifact:      examples/minimal/greet.py" in out, (
        "the run must say where the work went, not leave it to be discovered")


def _example_repo(tmp_path: Path) -> Path:
    """The shipped example, copied into a repository that does **not** ignore its output.

    The same build, with `.gitignore` saying something different — which is the whole point of the
    source/artifact split. In this repository `greet.py` is ignored and lands as an artifact; here
    it is tracked, so it must land as a **commit**.
    """
    import shutil

    repo = _repo(tmp_path)
    src = Path(__file__).resolve().parents[1] / "examples" / "minimal"
    dst = repo / "minimal"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "greet.py"))
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "example"], cwd=str(repo), capture_output=True)
    return repo


def _run_example(repo: Path, journal: Path, *extra):
    root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(repo / "minimal" / "runner.yaml"),
         "run", "--plan", str(repo / "minimal" / "plan.json"),
         "--risk", "low", "--confirm", "merge", "--ask-journal", str(journal), *extra],
        cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=900)


def test_a_tracked_module_output_lands_as_a_commit_on_the_branch(tmp_path):
    """The last module is committed from `report.visited`, and this is the path that exercises it.

    In this repository the example's output is ignored, so the run makes no commit and the
    end-to-end test above can only prove the artifact half. Here the same build writes a **tracked**
    file, so the commit half is proved too — and by the real CLI, not by calling `finish` directly.
    """
    repo = _example_repo(tmp_path)
    before = _sha(repo)
    done = _run_example(repo, tmp_path / "asks")
    out = (done.stdout or "") + (done.stderr or "")

    assert "state:         finished" in out, out[-800:]
    assert "committed:     fast-forwarded" in out, (
        f"the module's tracked output did not become a commit:\n{out[-800:]}")
    assert _sha(repo) != before
    assert (repo / "minimal" / "greet.py").is_file(), "and the working tree has it"

    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(repo),
                         capture_output=True, text=True).stdout
    assert "module-001" in log and "greet.py" in log, log


#: An agent that fails one module twice, so the bounded retry ends at `halt_second_fail`.
#: `--rule` cannot do this: it breaks a panel's tie, it does not choose a branch — the first draft
#: of the test below assumed otherwise and the run finished normally, which is a better outcome
#: than a test that passes for the wrong reason.
FAILING_AGENT = """
import json, sys
order = json.load(sys.stdin)
node, seat = order["node_id"], order.get("seat")


def say(obj):
    print(json.dumps(obj))
    raise SystemExit(0)


if seat:
    if node == "intake_review":
        say({"missing": [], "problems": [], "unsafe": []})
    # BOTH reviews, which is what reaches `halt_second_fail`. The first draft failed only
    # `lead_task_review`; `re_review` then passed, the module was recorded, and the loop went round
    # again — 39 times, until the step guard stopped it. A test that fails to reach the halt it is
    # named for is worth more than one that passes for another reason, and this is why it is here.
    fails = node in ("lead_task_review", "re_review")
    say({"verdict": "fail" if fails else "pass", "why": "as instructed"})
if node == "pm_plan":
    say({"modules": ["alpha"]})
if node == "lead_assess":
    say({"risk": "low"})
if node == "engineer_build":
    open("built_by_a_module_that_failed.py", "w").write("# should never be committed")
    say({"module": "alpha"})
branch = {"pm_confirm": "yes", "pm_signoff": "yes", "qa_accept": "pass",
          "lead_task_review": "fail", "re_review": "fail"}.get(node)
say({"verdict": branch} if branch else {"summary": (node or "?") + " done"})
"""


def test_a_module_that_never_recorded_is_not_committed(tmp_path):
    """A build that halted must not enter history as though it had passed.

    The module writes a tracked file and then fails twice, so `record_module` is never visited.
    Committing on "the walk ended" instead of on the run's own record would have committed this.
    """
    repo = _example_repo(tmp_path)
    (repo / "minimal" / "agent.py").write_text(FAILING_AGENT, encoding="utf-8")
    # Committed, and that is not a formality: a module tree is cut from a COMMIT, so an
    # uncommitted change — including to the agent itself — is invisible to the build. The first
    # draft of this test left the edit in the working tree, the build ran the *original* agent, and
    # the module loop went round 39 times instead of halting. See CHG-20260827-21's note on what a
    # build can see.
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "a failing agent"], cwd=str(repo),
                   capture_output=True)
    before = _sha(repo)

    done = _run_example(repo, tmp_path / "asks")
    out = (done.stdout or "") + (done.stderr or "")

    assert "halt_second_fail" in out, (
        f"the run did not reach the halt this test is about:\n{out[-900:]}")
    assert _sha(repo) == before, "a halted module was committed"
    assert "committed:" not in out
    assert not (repo / "built_by_a_module_that_failed.py").exists(), (
        "the failed module's work reached the working tree")


def test_the_run_says_when_uncommitted_edits_will_not_be_seen(tmp_path):
    """Inherent to isolation, and a surprise — so it is said out loud.

    This is the finding that cost thirty-nine cycles to notice: a module tree is cut from a commit,
    so an edit sitting in the working tree is not what the build reads. The run now says so before
    it starts rather than leaving it to be worked out from the output.
    """
    repo = _example_repo(tmp_path)
    (repo / "start.txt").write_text("edited, not committed\n", encoding="utf-8")

    done = _run_example(repo, tmp_path / "asks")
    out = (done.stdout or "") + (done.stderr or "")

    assert "uncommitted:   start.txt" in out, out[-700:]
    assert "not what it will see" in out


def test_a_clean_tree_says_nothing_about_uncommitted_edits(tmp_path):
    """The line must not appear on every run, or it stops being read."""
    repo = _example_repo(tmp_path)
    done = _run_example(repo, tmp_path / "asks")
    assert "uncommitted:" not in ((done.stdout or "") + (done.stderr or ""))


# ── the case no test drove, and it was broken on main ───────────────────────────────────────────

def test_a_multi_module_run_whose_agent_reads_the_filesystem_still_advances(tmp_path):
    """The regression step one shipped, and the shape of test that was missing.

    `examples/weather-spa` decides which module to build by **looking at the filesystem** — the
    first file under `site/` whose content does not match the brief — and `site/` is gitignored.

    Under isolation each tree is cut from a commit, an ignored file is never in a commit, and the
    artifacts were only carried at the **end** of the run. So every tree saw an empty `site/`, the
    agent built `markup` again, nothing tracked changed, the tip never advanced, and the step guard
    stopped the run after thirty-nine cycles.

    Two causes, both fixed: artifacts are now carried **forward into each new tree**, and
    `git status --ignored` collapses an ignored directory to one entry — the first fix checked
    `is_file()` and therefore copied nothing at all for `site/`.

    The reason this reached `main`: `test_example_weather_spa.py` drives the console and the server
    and never the CLI, and every other example has one module. **No test ran a multi-module build
    through the real command.** This one does.
    """
    root = Path(__file__).resolve().parents[1]
    site = root / "examples" / "weather-spa" / "site"
    if site.exists():
        import shutil as _shutil
        _shutil.rmtree(site)

    done = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(root / "examples/weather-spa/runner.yaml"),
         "run", "--plan", str(root / "examples/weather-spa/plan.json"),
         "--risk", "low", "--confirm", "merge",
         "--ask-journal", str(tmp_path / "asks")],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=1800)
    out = (done.stdout or "") + (done.stderr or "")

    assert "walk exceeded" not in out, (
        "the module loop did not advance — a fresh tree shows the agent an empty output "
        f"directory and it rebuilds the same module:\n{out[-900:]}")
    assert "state:         finished" in out, out[-900:]

    built = sorted(p.name for p in site.iterdir()) if site.exists() else []
    assert built == ["app.js", "index.html", "styles.css", "weather.js"], (
        f"the run finished with {built} instead of all four modules' output")


def test_an_ignored_directory_is_carried_whole(tmp_path):
    """The narrower half, without the forty-second example run.

    `git status --porcelain --ignored` reports an ignored **directory** as a single entry with a
    trailing slash, not as the files inside it. Checking `is_file()` on that entry copies nothing,
    which is how the whole of `site/` was dropped.
    """
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("*.artifact\nout/\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(root), capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "ignore out"], cwd=str(root), capture_output=True)

    trees = worktree.Trees(root)
    one = trees.path_for(worktree.key_for(1))
    (Path(one) / "out").mkdir()
    (Path(one) / "out" / "made.txt").write_text("built\n", encoding="utf-8")

    assert trees.artifacts(worktree.key_for(1)) == ["out/"], "git collapses the directory"

    # forward into the next module's tree...
    two = trees.path_for(worktree.key_for(2))
    assert (Path(two) / "out" / "made.txt").is_file(), (
        "the next module cannot see what the previous one built into an ignored directory")

    # ...and out into the working tree at the end.
    trees.carry()
    assert (root / "out" / "made.txt").read_text(encoding="utf-8") == "built\n"


def _registrations(root: Path):
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=str(root),
                            capture_output=True, text=True).stdout.strip()
    where = (root / common) / "worktrees"
    return sorted(p.name for p in where.iterdir()) if where.is_dir() else []


def test_a_kept_tree_keeps_its_files_and_not_its_registration(tmp_path):
    """The evidence is the **files**. The git registration is not, and it is what grows without
    bound.

    Every kept tree used to leave an entry in the repository's `worktrees/` directory, and every
    later `git status` and `git worktree add` walks all of them. Measured rather than feared: after
    a session of halting runs this repository held **156**, an ordinary `git status` took minutes,
    and `git worktree list` did not return at all.

    So a kept tree is unregistered and left on disk. An operator inspecting a halt reads the files;
    losing `git diff` inside a temp directory is a far smaller cost than a repository nobody can
    use.
    """
    root = _repo(tmp_path)
    before = _registrations(root)

    trees = worktree.Trees(root)
    one = trees.path_for(worktree.key_for(1))
    (Path(one) / "evidence.txt").write_text("what the halt left\n", encoding="utf-8")
    trees.path_for(worktree.key_for(2))
    assert len(_registrations(root)) == len(before) + 2, "the premise: they are registered"

    kept = trees.close(keep=True)

    assert _registrations(root) == before, "a kept tree must not leave git metadata behind"
    assert all(Path(k).is_dir() for k in kept), "but the files are the evidence and must remain"
    assert (Path(one) / "evidence.txt").read_text(encoding="utf-8") == "what the halt left\n"


def test_removing_trees_normally_also_leaves_no_registration(tmp_path):
    """The ordinary path, so the two ways a run can end agree about cleanliness."""
    root = _repo(tmp_path)
    before = _registrations(root)
    trees = worktree.Trees(root)
    trees.path_for(worktree.key_for(1))
    trees.close(keep=False)
    assert _registrations(root) == before
