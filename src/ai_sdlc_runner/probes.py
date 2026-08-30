"""probes.py — the postconditions that make a killed run resumable (CHG-20260822-04 task 7).

`effects.py` says an operation may be an effect only if it leaves a **probeable postcondition**
(D6.2), and that resume means finding the first unmet one (D6.3). This is where those probes stop
being an abstraction: each one reads the **world** — the ledger on disk, git, or the forge — and
answers a single yes/no about whether the effect's result is already there.

The distinction that decides whether any of this works: **a probe describes the postcondition, not
the action.** "Did we run push?" is a receipt question — it needs a record we wrote, and a record we
wrote is exactly what a crash destroys or, worse, leaves stale. "Does the remote have this branch?"
is a postcondition; it survives anything, because it asks the thing itself. Every probe here is
written in the second form, and none of them consults a file the runner produced for its own
benefit (D6.4/D6.5: there are no receipts).

The ledger probes are the exception that proves the rule. They *do* read files the runner wrote —
but those files are the deliverable, not a receipt: a CHG entry with its `Branch:` field is the
governed record of intent (D6.1), and it is what the next session reads to know what was intended.
A receipt says "I did the thing"; the ledger *is* the thing.

## Cost

Probes shell out. That is deliberate — `git ls-remote` asks the remote rather than a local cache, so
a branch deleted behind our back reads as absent, which is the truth. D6.5 says ship without
receipts and add them only if probe latency is *measured* to be a real cost; nothing here caches.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from . import paths

#: How long any single probe may take before it is treated as unanswerable. An unanswerable probe is
#: never read as "not done": that would re-run an effect that may have succeeded.
DEFAULT_TIMEOUT = 60


class ProbeError(Exception):
    """Raised when a probe cannot determine the answer.

    Deliberately not a ``False``. "I could not reach the forge" and "the PR does not exist" are
    different facts, and collapsing them makes the engine re-run an effect that may already have
    landed — the duplicate side effect D6 exists to avoid. Fail closed, like the shipped merge gate.
    """


def _run(argv: Sequence[str], cwd: Optional[str | Path] = None,
         timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(argv), cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError as exc:
        raise ProbeError(f"{argv[0]!r} is not available: {paths.plain_in(str(exc))}") from None
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{' '.join(argv)} timed out after {timeout}s: {exc}") from None


# --------------------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------------------

def branch_exists_locally(repo: str | Path, branch: str) -> bool:
    proc = _run(["git", "rev-parse", "--verify", f"refs/heads/{branch}"], cwd=repo)
    return proc.returncode == 0


def branch_on_remote(repo: str | Path, branch: str, remote: str = "origin") -> bool:
    """Does the remote have this branch? The push postcondition.

    Asks the remote, not a local ref: `refs/remotes/origin/<branch>` can be stale in both directions
    — present after the branch was deleted upstream, absent until someone fetches. The question is
    about the remote's state, so the probe asks the remote.
    """
    proc = _run(["git", "ls-remote", "--heads", remote, branch], cwd=repo)
    if proc.returncode != 0:
        raise ProbeError(
            f"could not reach {remote} to check for {branch!r}: {proc.stderr.strip()}. Refusing to "
            f"report 'not pushed' — an unreachable remote is not an empty one, and treating it as "
            f"one would push again over something that may already be there.")
    return bool(proc.stdout.strip())


def commit_exists_for(repo: str | Path, needle: str, branch: Optional[str] = None) -> bool:
    """Is there a commit whose message contains ``needle`` (usually the CHG id)?

    The commit postcondition, and it is one this repo already relies on: every commit message
    carries its CHG id, which is what makes a commit findable by intent rather than by hash.
    """
    argv = ["git", "log", "--fixed-strings", f"--grep={needle}", "--format=%H"]
    if branch:
        argv.append(branch)
    proc = _run(argv, cwd=repo)
    if proc.returncode != 0:
        raise ProbeError(f"git log failed in {repo}: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def working_tree_clean(repo: str | Path) -> bool:
    proc = _run(["git", "status", "--porcelain"], cwd=repo)
    if proc.returncode != 0:
        raise ProbeError(f"git status failed in {repo}: {proc.stderr.strip()}")
    return not proc.stdout.strip()


# --------------------------------------------------------------------------------------
# the forge
# --------------------------------------------------------------------------------------

def pr_open_for(repo: str | Path, branch: str,
                argv: Sequence[str] = ("gh", "pr", "list")) -> bool:
    """Is there a PR for this branch? The PR-created postcondition.

    The command is a parameter because the forge CLI is a harness detail, and because a test needs to
    drive it without a network. Its **contract** is what matters and is asserted: exit 0 with a
    non-empty listing means yes, exit 0 with nothing means no, and any other exit is unanswerable —
    never "no".
    """
    proc = _run([*argv, "--head", branch], cwd=repo)
    if proc.returncode != 0:
        raise ProbeError(
            f"could not ask the forge about {branch!r}: exit {proc.returncode}, "
            f"{proc.stderr.strip()}. An unreachable forge is not an absent PR.")
    return bool(proc.stdout.strip())


# --------------------------------------------------------------------------------------
# the ledger — the record of intent, written before any effect (D6.1)
# --------------------------------------------------------------------------------------

def _chg_path(repo: str | Path, chg_id: str) -> Path:
    return Path(repo) / "docs" / "changes" / f"{chg_id}.md"


def chg_recorded(repo: str | Path, chg_id: str) -> bool:
    """Does the CHG exist **and** name its branch?

    Both halves, because D6.1 is specific: a node writes its CHG entry *with* `Branch:` and the task
    table before taking any effect. A file with no `Branch:` is a half-written intent, and reading it
    as "intent recorded" is how a resume would proceed from a record that never said where.
    """
    path = _chg_path(repo, chg_id)
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    return bool(re.search(r"^\s*-?\s*Branch\s*[:：]", text, re.MULTILINE))


def task_ticked(repo: str | Path, chg_id: str, task: str) -> bool:
    """Is this task's box ticked in the CHG's table? The per-task postcondition.

    Ticked boxes are what the shipped flow itself uses as the resume point — "interruption at any
    point is safe: ticked checkboxes are the resume point" — so the probe reads the same mark a human
    reads, rather than a parallel record that could disagree with it.
    """
    path = _chg_path(repo, chg_id)
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if task in line and re.search(r"\[\s*[xX]\s*\]|\*\*\[\s*[xX]\s*\]\*\*", line):
            return True
    return False


def acceptance_recorded(repo: str | Path, acc_id: str) -> bool:
    """Does the ACC file exist? Acceptance's postcondition, on the same terms as the CHG's."""
    return (Path(repo) / "docs" / "acceptance" / f"{acc_id}.md").is_file()
