"""A tree per module build, so one module cannot see another's half-finished state
(CHG-20260827-21, step one).

Step one of that record is **isolation without concurrency**. Modules still build one at a time and
nothing about ordering or resume changes; what changes is that each build cycle runs in its own git
worktree instead of all of them sharing `agent_cwd`. The record says this is worth shipping alone,
and it is: a module that half-writes a file and fails no longer leaves that file where the next
module's engineer will read it.

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
from typing import Dict, List, Optional


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

    # ---------------------------------------------------------------- opening

    def top(self) -> Optional[str]:
        return available(self.root, run=self._run)

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

        if self._base is None:
            self._base = Path(tempfile.mkdtemp(prefix="ai-sdlc-worktrees-"))
        where = self._base / key
        done = self._run(["git", "worktree", "add", "--detach", str(where), "HEAD"],
                         cwd=top, capture_output=True, text=True, timeout=300)
        if done.returncode != 0:
            detail = ((done.stderr or "") + (done.stdout or "")).strip()[:400]
            if self.required:
                raise WorktreeError(
                    f"{REQUIRE_FLAG} was passed and `git worktree add` failed for {key!r}: "
                    f"{detail}")
            return None
        self._trees[key] = str(where)
        return self._trees[key]

    # ---------------------------------------------------------------- closing

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
