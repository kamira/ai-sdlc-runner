"""ship.py — the ordered effects that carry a change out (CHG-20260822-04 task 7).

The sequence this repo already runs by hand — record the intent, branch, commit, push, open the PR —
expressed as `effects.Effect`s so it survives being killed anywhere along it. Each one is paired with
the probe from `probes.py` that reads its postcondition out of the world, which is what makes
"resume at the first unmet" mean something concrete.

The window that decides the design, and the one the kill-and-resume test drives: **killed between
`git push` and `gh pr create`**. `git ls-remote origin <branch>` reads met, `gh pr list --head
<branch>` reads empty, so the frontier is exactly "PR not created" and the next run creates the PR
and nothing else. Not the branch again, not the commit again — and, since the panel's finding, not
the PR again either if it turns out to be there.

Every effect here satisfies D6.2 by construction: if a step could not be probed it would not be in
this list. Ordering is causal, so it is also the resume order.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from . import effects, probes


class ShipError(Exception):
    """Raised when an effect cannot be carried out."""


def _git(repo: str | Path, *args: str) -> None:
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)
    if proc.returncode != 0:
        raise ShipError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")


def effects_for(
    repo: str | Path,
    chg_id: str,
    branch: str,
    message: str,
    write_chg,
    remote: str = "origin",
    gh_list: Sequence[str] = ("gh", "pr", "list"),
    gh_create: Sequence[str] = ("gh", "pr", "create"),
    pr_title: Optional[str] = None,
) -> List[effects.Effect]:
    """The ordered ship sequence for one change.

    ``write_chg`` is supplied by the caller and writes the CHG entry — intent first (D6.1), before
    anything else happens, because a record written afterwards is a record that a crash can lose
    while the effects it describes have already landed.
    """
    repo = Path(repo)
    title = pr_title or message.splitlines()[0]

    def _commit() -> None:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", message)

    return [
        effects.Effect(
            name="record-intent",
            probe=lambda: probes.chg_recorded(repo, chg_id),
            apply=write_chg,
            postcondition=f"docs/changes/{chg_id}.md exists and names its Branch",
        ),
        effects.Effect(
            name="branch",
            probe=lambda: probes.branch_exists_locally(repo, branch),
            apply=lambda: _git(repo, "checkout", "-b", branch),
            postcondition=f"refs/heads/{branch} exists",
        ),
        effects.Effect(
            name="commit",
            probe=lambda: probes.commit_exists_for(repo, chg_id),
            apply=_commit,
            postcondition=f"a commit whose message contains {chg_id}",
        ),
        effects.Effect(
            name="push",
            probe=lambda: probes.branch_on_remote(repo, branch, remote),
            apply=lambda: _git(repo, "push", "-q", remote, branch),
            postcondition=f"{remote} has {branch}",
        ),
        effects.Effect(
            name="pr",
            probe=lambda: probes.pr_open_for(repo, branch, gh_list),
            apply=lambda: _create_pr(repo, branch, title, gh_create),
            postcondition=f"the forge lists a PR for {branch}",
        ),
    ]


def _create_pr(repo: Path, branch: str, title: str, argv: Sequence[str]) -> None:
    proc = subprocess.run([*argv, "--head", branch, "--title", title],
                          cwd=str(repo), capture_output=True, text=True)
    if proc.returncode != 0:
        raise ShipError(f"could not open a PR for {branch}: {proc.stderr.strip()}")
