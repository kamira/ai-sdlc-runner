#!/usr/bin/env python3
"""Is this tree frozen, and at what commit? (CHG-20260827-13)

KN-14 says: **freeze the tree before verification, and do not touch it until every seat reports.**
It has been a paragraph in `README.md` and `docs/defect-log.md` since the round that learned it —
a verifier found the working tree changing under them mid-audit, and the change was to the safety
check they were auditing. An acceptance round whose subject moved has verified nothing, however good
its findings are.

Section 8 of `docs/ai-guideline.md` is explicit that **red lines always halt, and the check is code,
not a paragraph.** This one was a paragraph, and on 2026-08-27 the acceptance round that closed
forty-seven changes broke it: eleven verifiers against one shared worktree, several mutating `src/`
to prove tests bite, one of them finding another's uncommitted cut mid-audit. The tree was restored
and the evidence held. The method was still wrong, and the rule that would have stopped it was the
one with nothing behind it.

So: this reports the commit a round is verifying, and refuses when the tree is not that commit.

**Deliberately a tool a round runs, not a hook on every commit.** The rule is about verification
rounds. A check that fires on ordinary work is a check people switch off — KN-13's lesson, learned
from a red-line check with a 95% false-stop rate, and not worth learning twice.

Usage::

    python tools/frozen_tree.py                 # this repo
    python tools/frozen_tree.py --repo PATH

Exit 0 and print the sha when the tree is clean. Exit 1 and name the files when it is not. Exit 2
when the question cannot be answered at all — no git, or not a repository — because "I could not
tell" must not read the same as "it is clean".
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


class NotAnswerable(Exception):
    """The question could not be put. Distinct from a dirty tree, and exits differently."""


def _git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as exc:                                    # no git on PATH
        raise NotAnswerable(f"could not run git: {exc}") from None
    if done.returncode != 0:
        raise NotAnswerable((done.stderr or done.stdout or "git failed").strip())
    return done.stdout


def _porcelain_paths(raw: str) -> list:
    """The paths in `git status --porcelain -z` output, without inventing any.

    `-z` emits one NUL-terminated field per entry — except a rename or a copy, which emits **two**:
    the new path with its `XY ` status prefix, then the old path with **no prefix at all**. Both are
    returned: the old one is gone from the working tree and the new one is not in the commit, and a
    tree frozen at that commit matches neither.
    """
    fields = [field for field in raw.split("\0") if field]
    paths = []
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) <= 3:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path.strip())
        if "R" in status or "C" in status:
            if index < len(fields):
                paths.append(fields[index].strip())
                index += 1
    return paths


def state(repo: Path) -> Tuple[str, List[str]]:
    """The HEAD sha, and the paths that differ from it.

    `git status --porcelain` already leaves out anything `.gitignore` covers, so a build artefact
    does not fail a round. Untracked-and-not-ignored **does** count: a file nobody has committed is
    a file the next reader of this sha will not have, which is exactly the ambiguity a frozen tree
    exists to remove.
    """
    head = _git(repo, "rev-parse", "HEAD").strip()
    # **`-z`, and a rename is two fields** (CHG-20260903-36, conformance seat L-54).
    #
    # This read `line[3:]` over `--porcelain` without `-z`, and porcelain v1 renders a staged
    # rename on ONE line as `R  <old> -> <new>`. Driven here: `git mv LICENSE LICENCE.txt` made
    # `state()` return `['LICENSE -> LICENCE.txt']` — a single string that is not a filename,
    # and neither of the two real paths. This function's own docstring promises *"the paths
    # that differ from it"* and *"name the files when it is not"*, and it named a file that
    # exists nowhere, in the tool a verification round runs to decide whether it may proceed.
    #
    # `CHG-20260903-31` fixed this exact shape in `worktree.uncommitted()` and swept no further.
    # The sweep this time also checked `worktree.py`'s other `[3:]`, in `carry()`, and found it
    # **correct** — it is guarded by `entry.startswith("!! ")`, so an unprefixed old-path field
    # is skipped rather than sliced.
    #
    # `-z` also removes v1's path quoting, which returned non-ASCII names with their quotes and
    # octal escapes still attached.
    dirty = _porcelain_paths(_git(repo, "status", "--porcelain", "-z"))
    return head, sorted(dirty)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", metavar="PATH",
                        help="the repository to ask about (default: the current directory)")
    args = parser.parse_args(argv)

    try:
        head, dirty = state(Path(args.repo))
    except NotAnswerable as exc:
        print(f"cannot tell whether the tree is frozen: {exc}")
        return 2

    if dirty:
        print(f"the tree is NOT frozen at {head[:12]} — {len(dirty)} path(s) differ from it:")
        for path in dirty:
            print(f"  {path}")
        print("commit or stash them before a verification round reads this tree (KN-14).")
        return 1

    print(head)
    return 0


if __name__ == "__main__":
    sys.exit(main())
