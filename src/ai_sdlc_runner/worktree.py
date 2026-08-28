"""A tree per module build, so one module cannot see another's half-finished state
(CHG-20260827-21, step one).

Step one of that record is **isolation without concurrency**. Modules still build one at a time and
nothing about ordering or resume changes; what changes is that each build cycle runs in its own git
worktree instead of all of them sharing `agent_cwd`. A module that half-writes a file and fails no
longer leaves that file where the next module's engineer will read it.

## A module is a commit

The record said step one was *"worth shipping by itself"*. It was not, and building it proved why:
a tree cut from `HEAD` **deleted the run's output** — the engineer wrote into the tree and the tree
was removed with the work in it — and module N+1 could not see module N's finished work. Both were
reproduced, the change was marked blocked, and the question went to a person: *is a module a
commit?*

The operator answered **yes**, and that answer is the design:

* a tree is cut from `Trees.tip`, which starts at `HEAD`;
* when the loop moves on, the finished module is **committed** and the tip advances;
* the next tree is cut from that commit, so N+1 sees N.

## Source becomes commits; artifacts become files

`.gitignore` is the project saying which files are not repository content. A runner that
force-added them would be overriding that on the project's behalf. So `finish` commits **tracked
content only**, and `carry` copies the ignored-but-created files into the working tree — which is
where a build normally leaves them. `examples/minimal/greet.py` is exactly that case.

## What a build can see

A tree is cut from a **commit**, so uncommitted edits in the operator's working tree are invisible
to it. That is inherent to isolation rather than a defect, and it is a surprise, so `uncommitted`
exists and the run says so before it starts. It was found the hard way: an edited agent left
uncommitted meant the build ran the *previous* agent for thirty-nine cycles.

## The unit of isolation is the build **cycle**, not the module name

This is the design fact that the proposal did not anticipate, and it comes from
`engine._frontier`'s own comment:

    the work order does not name a module, so the runner never tells it which one to build

The engineer decides what to build and reports the name in its **answer**. So at the moment a
session is opened — which is when a working directory has to exist — the module's name is not
known and cannot be. Keying a tree on it is impossible without inverting that protocol, and that
protocol is load-bearing: CHG-20260823-50 is the record of what happened when the runner tried to
reason about modules the engineer had not reported.

So a tree is keyed on the **cycle**: the nth pass through `graph.module_cycle()`. One pass builds
one module, so "a tree per cycle" delivers the property task 1 asks for — *two modules cannot see
each other's tree* — without needing a name that does not exist yet.

## Which nodes share a tree

Every node in `graph.module_cycle()`, derived from the edges rather than listed. `engineer_build`
writes the code and `engineer_selfverify`, `lead_task_review`, `fix_pass` and `re_review` all have
to see what it wrote, so they share one tree per cycle. `lead_review`, `qa_verify` and everything
after run in the main tree, because they review the whole change and not one module.

## Nothing is silent, and only one case is a refusal

The same rule `sandbox.py` arrived at, for the same reason. A worktree that quietly is not created
would leave every run claiming isolation it does not have. So:

* no git, or not a repository → the run proceeds in `agent_cwd` and **says so** in its report;
* `--worktree` passed and no tree can be made → refuse, naming why.

"Nobody asked and it is written down" and "somebody asked and it cannot be done" are different
things, and only the second stops a run.

## What this does not isolate

The tree. Two modules writing the same database, port, cache or remote still collide — the record
says so under *Not claimed*, and nothing here changes it. This is a filesystem boundary and should
not be read as more.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import paths


class WorktreeError(Exception):
    """A tree was asked for and could not be made."""


#: The flag that turns "recorded as unisolated" into a refusal. Default off, for the reason in the
#: module docstring: a runner that refuses on every machine without git is a runner nobody runs, and
#: a check that gets switched off is worse than one scoped honestly.
REQUIRE_FLAG = "--worktree"


def available(root: str | Path | None = None, run=subprocess.run) -> Optional[str]:
    """The repository's top level, or `None` when this is not a git working tree.

    Being *in* a git repository is the whole precondition, and it is checked by asking git rather
    than by looking for a `.git` directory: a worktree's `.git` is a file, a submodule's points
    elsewhere, and `git rev-parse` is the only thing that gets every case right.
    """
    if shutil.which("git") is None:
        return None
    try:
        done = run(["git", "rev-parse", "--show-toplevel"],
                   cwd=str(root) if root else None,
                   capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):       # pragma: no cover - exotic environments
        return None
    if done.returncode != 0:
        return None
    return (done.stdout or "").strip() or None


def describe(root: str | Path | None = None, run=subprocess.run) -> str:
    """One line for the run report: the tree in use, or why there is none."""
    top = available(root, run=run)
    if top is None:
        if shutil.which("git") is None:
            return "no isolation: git is not on PATH"
        return f"no isolation: {root or '.'} is not a git working tree"
    return f"a worktree per module build, from {top}"


class Trees:
    """The worktrees one run made, and the promise to take them away again.

    Held by the caller rather than created per ask, because the five nodes of one cycle must land in
    the **same** tree and only the caller sees more than one ask.
    """

    def __init__(self, root: str | Path | None = None, *, required: bool = False,
                 run=subprocess.run, base: str | Path | None = None) -> None:
        self.root = str(root) if root else None
        self.required = required
        self._run = run
        self._base = Path(base) if base else None
        self._trees: Dict[str, str] = {}
        #: Trees that outlived the run because removing them failed. Reported, never swallowed: a
        #: directory left behind is the operator's disk, and they get told rather than discovering
        #: it later.
        self.left_behind: List[str] = []

        # ── the commit chain (CHG-20260827-21, step one) ────────────────────────────────────────
        #
        # **A module is a commit.** That is the operator's answer to the question the first attempt
        # at this change stopped on, and it is what makes worktree isolation work at all: a tree cut
        # from `HEAD` cannot see the previous module's work, so each module has to end at a commit
        # the next one is cut from.
        #
        #: What the next tree is cut from. Starts at `HEAD` and advances by one commit per module.
        self.tip: Optional[str] = None
        #: The cycle whose tree is open. Committed when the next one is asked for — by then the
        #: module loop has moved on, so it is finished by construction.
        self._live: Optional[str] = None
        #: `[(cycle, sha, subject)]`, in order. The run's own account of what it built.
        self.commits: List[Tuple[str, str, str]] = []
        #: Artifacts that could not be copied into the working tree, with why. Reported for the
        #: same reason as `left_behind`: work the operator does not have must not look like work
        #: that was never produced.
        self.not_carried: List[str] = []

    # ---------------------------------------------------------------- opening

    def top(self) -> Optional[str]:
        return available(self.root, run=self._run)

    def _git(self, args: Sequence[str], cwd: str, timeout: int = 300):
        return self._run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)

    def _head(self, top: str) -> Optional[str]:
        done = self._git(["rev-parse", "HEAD"], top)
        return (done.stdout or "").strip() if done.returncode == 0 else None

    def path_for(self, key: str) -> Optional[str]:
        """The tree for this build cycle, made on first use and reused after.

        Returns `None` when this machine cannot make one and `required` is off — the caller then
        runs in `agent_cwd` and records that it did.
        """
        if key in self._trees:
            return self._trees[key]

        top = self.top()
        if top is None:
            if self.required:
                raise WorktreeError(
                    f"{REQUIRE_FLAG} was passed, so every module must build in its own tree, and "
                    f"none can be made here: {describe(self.root, run=self._run)}. Run from inside "
                    f"a git working tree, or drop {REQUIRE_FLAG} to record the run as unisolated "
                    f"instead of stopping it.")
            return None

        # The previous module is finished: the loop only asks for a new tree after `record_module`,
        # so by the time this is called the one before it is done. Commit it, and cut this one from
        # the result — which is the whole mechanism by which module N+1 can see module N.
        if self._live is not None and self._live != key:
            self.finish(self._live)

        if self.tip is None:
            self.tip = self._head(top)
            if self.tip is None:
                if self.required:
                    raise WorktreeError(
                        f"{REQUIRE_FLAG} was passed and this repository has no commit to build "
                        f"from. A module is a commit, so there has to be one to start from.")
                return None

        if self._base is None:
            self._base = Path(tempfile.mkdtemp(prefix="ai-sdlc-worktrees-"))
        where = self._base / key
        done = self._run(["git", "worktree", "add", "--detach", str(where), self.tip],
                         cwd=top, capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            detail = ((done.stderr or "") + (done.stdout or "")).strip()[:400]
            if self.required:
                raise WorktreeError(
                    f"{REQUIRE_FLAG} was passed and `git worktree add` failed for {key!r}: "
                    f"{detail}")
            return None
        self._trees[key] = str(where)
        self._live = key
        return self._trees[key]

    # ---------------------------------------------------------------- committing

    #: The commits are the runner's, and saying so is the point. Passed explicitly rather than read
    #: from the operator's git config: a machine-made commit wearing a person's name is the same
    #: misattribution CHG-20260828-03 fixed in the export, and it would be durable here.
    AUTHOR = ("ai-sdlc-runner", "runner@ai-sdlc.invalid")

    def finish(self, key: str) -> Optional[str]:
        """Commit what this module built, and advance the tip. `None` if it built nothing.

        **Tracked content only.** `.gitignore` is the project saying which files are not repository
        content, and a runner that force-added them would be overriding that statement on the
        project's behalf. Build artifacts are carried back to the working tree by `artifacts` at the
        end instead, which is where a build normally leaves them.

        A module that changed nothing is not an error and not a commit — it leaves the tip where it
        was, and `commits` says so by omission.
        """
        where = self._trees.get(key)
        top = self.top()
        if where is None or top is None:
            return None
        if self._live == key:
            self._live = None

        staged = self._git(["add", "-A"], where)
        if staged.returncode != 0:
            raise WorktreeError(
                f"could not stage {key!r}'s work: "
                f"{((staged.stderr or '') + (staged.stdout or '')).strip()[:300]}")

        named = self._git(["diff", "--cached", "--name-only"], where)
        files = [f for f in (named.stdout or "").splitlines() if f.strip()]
        if not files:
            return None

        # The subject names what changed, which is more use to a reader than the cycle number and
        # costs nothing: the module's own name never reaches this object — the engineer reports it
        # in an answer the trees never see (see the module docstring).
        shown = ", ".join(files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else "")
        subject = f"{key}: {shown}"
        done = self._git(
            ["-c", f"user.name={self.AUTHOR[0]}", "-c", f"user.email={self.AUTHOR[1]}",
             "commit", "-m", subject], where)
        if done.returncode != 0:
            raise WorktreeError(
                f"could not commit {key!r}: "
                f"{((done.stderr or '') + (done.stdout or '')).strip()[:300]}")

        sha = (self._git(["rev-parse", "HEAD"], where).stdout or "").strip()
        self.tip = sha or self.tip
        self.commits.append((key, sha, subject))
        return sha

    def artifacts(self, key: str) -> List[str]:
        """Files this module's tree holds that git is told to ignore — the build's artifacts.

        A worktree starts as a clean checkout, so anything ignored-and-present in it was made by
        this build. They are not commits (see `finish`), and they are not nothing either: this is
        where `examples/minimal/greet.py` lives, and a run that produced it and then deleted the
        tree would have thrown the work away — which is exactly what the first attempt at this
        change did.
        """
        where = self._trees.get(key)
        if where is None:
            return []
        done = self._git(["status", "--porcelain", "--ignored", "-z"], where)
        if done.returncode != 0:
            return []
        out = []
        for entry in (done.stdout or "").split("\0"):
            if entry.startswith("!! "):
                out.append(entry[3:])
        return sorted(out)

    # ---------------------------------------------------------------- closing

    def uncommitted(self) -> List[str]:
        """Tracked files changed in the working tree but not committed — which a build cannot see.

        A module tree is cut from a **commit**, so an edit sitting in the operator's working tree is
        invisible to the build. That is inherent to isolation and it is not a defect, but it is a
        surprise, and this repository's rule is that a surprise gets said out loud rather than
        discovered.

        Found the hard way: a test edited the agent, left it uncommitted, and the build ran the
        *previous* agent for thirty-nine cycles.
        """
        top = self.top()
        if top is None:
            return []
        done = self._git(["status", "--porcelain", "--untracked-files=no", "-z"], top)
        if done.returncode != 0:
            return []
        return sorted(entry[3:] for entry in (done.stdout or "").split("\0") if len(entry) > 3)

    def carry(self) -> List[str]:
        """Copy each module's build artifacts into the working tree, and say what was copied.

        The commits carry the source. These are the files `.gitignore` says are **not** repository
        content — `examples/minimal/greet.py` is one — and a build normally leaves them in your
        working directory rather than in history. So that is where they are put.

        Copied rather than moved, because the trees are still evidence until `close` removes them,
        and copied per tree in order, so a later module's artifact wins over an earlier one's the
        same way a later commit does.
        """
        top = self.top()
        if top is None:
            return []
        carried: List[str] = []
        for key, where in sorted(self._trees.items()):
            for rel in self.artifacts(key):
                source = Path(where) / rel
                if not source.is_file():
                    continue            # a directory entry; its files are listed separately
                target = Path(top) / rel
                try:
                    # Through `paths` (CHG-20260827-21): these land in the operator's repository at
                    # paths git chose, which on Windows can be deeper than the plain API accepts.
                    paths.makedirs(target.parent)
                    shutil.copy2(paths.real(source), paths.real(target))
                except OSError as exc:
                    # Recorded, not swallowed. An artifact that failed to arrive is work the
                    # operator does not have, and a `continue` here would make it indistinguishable
                    # from a build that produced nothing.
                    self.not_carried.append(f"{rel}: {exc.__class__.__name__}: {exc}")
                    continue
                if rel not in carried:
                    carried.append(rel)
        return carried

    def land(self, fallback_branch: str) -> str:
        """Put the run's commits where the operator can see them, and say which way it went.

        **Fast-forward if it is a fast-forward, a branch if it is not.** The operator's branch is
        theirs; this moves it only when moving it discards nothing — `--ff-only` is what makes that
        a question git answers rather than one this code guesses at. Anything else (they committed
        during the run, they have local changes in the way) leaves the work on a named branch and
        reports where.

        A run that built nothing returns an empty string: there is no commit and nothing to say.
        """
        top = self.top()
        if top is None or not self.commits or self.tip is None:
            return ""

        done = self._git(["merge", "--ff-only", self.tip], top)
        if done.returncode == 0:
            return f"fast-forwarded to {self.tip[:12]} ({len(self.commits)} commit(s))"

        made = self._git(["branch", "-f", fallback_branch, self.tip], top)
        why = ((done.stderr or "") + (done.stdout or "")).strip().splitlines()
        because = why[0][:140] if why else "the branch has moved"
        if made.returncode != 0:
            return (f"{len(self.commits)} commit(s) are at {self.tip[:12]} and could not be put on "
                    f"a branch — recover them with `git branch <name> {self.tip[:12]}` before the "
                    f"next `git gc`. Not fast-forwarded because: {because}")
        return (f"{len(self.commits)} commit(s) on {fallback_branch} at {self.tip[:12]} — not "
                f"fast-forwarded because: {because}")

    def close(self, keep: bool = False) -> List[str]:
        """Remove every tree this run made, and return what could not be removed.

        `keep=True` leaves them, which is what an operator debugging a halt wants: the tree is the
        evidence. Nothing is removed that this object did not create.
        """
        if keep:
            self.left_behind = sorted(self._trees.values())
            self._trees = {}
            return list(self.left_behind)

        top = self.top()
        for key, where in sorted(self._trees.items()):
            removed = False
            if top is not None:
                done = self._run(["git", "worktree", "remove", "--force", where],
                                 cwd=top, capture_output=True, text=True, timeout=300)
                removed = done.returncode == 0
            if not removed:
                # `git worktree remove` refuses a tree git has lost track of; the directory is still
                # the operator's to reclaim, so try, and say so if even that fails.
                try:
                    shutil.rmtree(where, ignore_errors=False)
                    removed = True
                except OSError:
                    removed = False
            if not removed:
                self.left_behind.append(where)
        self._trees = {}
        return list(self.left_behind)

    # ---------------------------------------------------------------- reporting

    def report(self) -> str:
        """What actually happened, for the run report — never what was intended."""
        made = len(self._trees)
        top = self.top()
        if top is None:
            return describe(self.root, run=self._run) + (
                f" ({REQUIRE_FLAG} not passed, so the run continued)" if not self.required else "")
        return f"{made} module tree(s) under {self._base}" if made else describe(
            self.root, run=self._run)


def key_for(nth: int) -> str:
    """The tree name for the nth build cycle, counting from one.

    A cycle number rather than a module name, for the reason in the module docstring. Zero-padded so
    a directory listing sorts the way the run ran.
    """
    return f"module-{nth:03d}"


def within(tree: str, top: str, where: Optional[str]) -> Optional[str]:
    """`where`, relocated to the same position inside an isolated tree.

    A worktree is a checkout of the repository **top**, and `agent_cwd` is usually deeper than that
    — `examples/minimal`, say. Handing the tree's root to a command that runs `python3 agent.py`
    would look isolated and resolve nothing, so the offset has to be carried across.

    `None` when `where` is outside the repository, because there is no corresponding place inside
    the tree and inventing one would put the work somewhere nobody asked for. The caller reports
    that rather than silently running unisolated.
    """
    if where is None:
        return tree
    try:
        rel = os.path.relpath(os.path.abspath(where), os.path.abspath(top))
    except ValueError:                      # different drives on Windows: no relative path exists
        return None
    if rel == os.curdir:
        return tree
    if rel.startswith(os.pardir + os.sep) or rel == os.pardir:
        return None
    return os.path.join(tree, rel)
