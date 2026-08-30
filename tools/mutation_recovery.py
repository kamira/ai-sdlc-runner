"""Put back a source file a killed mutation run left mutated (CHG-20260828-18).

`mutation_check.run()` restores in a `finally`, on the argument that *"leaving a mutated tree behind
is a worse outcome than any result this function can report"*. That is right, and `finally` does not
run when the process is **killed** — which is the one case where nobody is reading the output.

It happened: a run stopped at a timeout left `src/ai_sdlc_runner/worktree.py` holding `if False:` in
`_copy_artifact`, and only a glance at `git status` caught it before it was committed. That was the
loud version. The quiet one is a mutation **no test catches** — it leaves a tree whose suite is
still green, so nothing goes red and nothing in a diff review looks alarming except one line nobody
put there.

So the record of what is in flight lives on disk, outside the process, where nothing a signal can do
to the program can reach it. It holds the original **and** the mutated text, so recovery can tell
*still mutated* from *already restored* from *somebody has edited this since* — and refuse the third
rather than overwrite work it cannot account for.

## Why this is its own file

Not tidiness. `mutation_check.py` mutates by exact text, and a mutation's `before` string sits in
that same file — so **any anchor into `mutation_check.py` appears twice**, once in the code and once
in the definition that names it, and the uniqueness guard from CHG-20260828-01 correctly refuses it.
A file cannot pin guarantees about itself this way. Moving the recovery here is what makes the
harness's own safety net something the harness can break on purpose and watch a test notice.
"""
from __future__ import annotations

import io
import json
import signal
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent

#: Written before a file is mutated, removed after it is put back. Also the lock — see `begin`.
IN_FLIGHT = REPO / "tools" / ".mutation-in-flight.json"


class MutationInFlight(Exception):
    """Another run holds this worktree, or a killed one left its file mutated."""


def write(path: Path, text: str) -> None:
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def begin(path: Path, original: str, mutated: str) -> None:
    """Record what is about to be broken, before breaking it.

    Order is the whole guarantee: a record written *after* the mutation misses exactly the window it
    exists to cover.

    ## And it is the lock

    Created exclusively (`"x"`), so a second run in the same worktree is refused rather than
    overwriting the first one's record — which would strand the first file with nothing left saying
    how to put it back.

    This is not hypothetical. A review panel of four agents was run in one worktree while one of
    them was running the harness: two seats read a half-mutated tree, one got a false positive from
    it, and a third measured a 252-test run against source that was changing underneath it. Nothing
    was lost, because the runs happened not to overlap on the same file — the lock is what makes
    that a guarantee rather than luck (CHG-20260830-05, risk seat).
    """
    record = json.dumps({"path": str(path), "original": original, "mutated": mutated},
                        ensure_ascii=False)
    try:
        with io.open(IN_FLIGHT, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(record)
    except FileExistsError:
        raise MutationInFlight(
            f"{IN_FLIGHT.name} already exists, so another mutation run holds this worktree — or a "
            f"previous one was killed and its file is still mutated. Run this tool again on its own "
            f"to recover, or read that file and restore by hand. Two runs at once would overwrite "
            f"the record the first one needs to put its file back.") from None


def end() -> None:
    IN_FLIGHT.unlink(missing_ok=True)


def apply(path: Path, original: str, mutated: str) -> None:
    """Record, then break. Both halves live here so the **order** is something a mutation can
    invert and a test can notice — in `mutation_check.py` it would be unpinnable, for the reason in
    this module's docstring."""
    begin(path, original, mutated)
    write(path, mutated)


def restore(path: Path, original: str) -> None:
    """Put it back, then forget it. A record that outlives its run makes every later run announce a
    recovery that already happened."""
    write(path, original)
    end()


def recover(quiet: bool = False) -> Optional[str]:
    """Put back a file a killed run left mutated. Returns what it did, or `None` if there was
    nothing to do.

    Called at startup, and from the signal handler so an interrupted run cleans up immediately
    rather than leaving the tree wrong until somebody happens to run this again.
    """
    if not IN_FLIGHT.exists():
        return None
    try:
        record = json.loads(io.open(IN_FLIGHT, encoding="utf-8").read())
        path = Path(record["path"])
        original, mutated = record["original"], record["mutated"]
    except (OSError, ValueError, KeyError):
        end()
        return "the in-flight record was unreadable and has been discarded; check `git status`"

    now = io.open(path, encoding="utf-8").read() if path.exists() else None
    if now == mutated:
        write(path, original)
        said = f"restored {path.name}, which a killed run left mutated"
    elif now == original:
        said = f"{path.name} was already back as it should be"
    else:
        # The one case worth refusing. Somebody edited this file after the run died, and the
        # original on record is no longer the thing to write over it. The record is kept, because a
        # refusal that also throws away the original strands the file for good.
        said = (f"REFUSING to touch {path.name}: it matches neither the text a killed run mutated "
                f"nor the text that was there before, so somebody has edited it since. The original "
                f"is kept in {IN_FLIGHT.name} — reconcile it by hand, then delete that file.")
        if not quiet:
            print(f"  {said}")
        return said
    end()
    if not quiet:
        print(f"  {said}")
    return said


def restore_on_signal() -> None:
    """A nicety, and **not** the guarantee. Read this before relying on it.

    `finally` already covers Ctrl-C: SIGINT becomes `KeyboardInterrupt`, which unwinds normally. What
    it does not cover is SIGTERM, which is what a timeout sends — so this handler exists for that,
    on POSIX, where it makes the cleanup immediate instead of waiting for the next run.

    **It does not fire on Windows.** Measured, not assumed: killing a real run from Git Bash left
    `worktree.py` mutated with the handler installed, because `kill -TERM` there becomes
    `TerminateProcess`, which no handler can catch — the same as SIGKILL anywhere. `recover()` at
    startup is what put the file back, and `recover()` is therefore the guarantee. This is the part
    that is allowed to fail.
    """
    def handler(signum, frame):                       # pragma: no cover - needs a real signal
        recover()
        raise SystemExit(128 + signum)

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, handler)
        except (OSError, ValueError):                  # pragma: no cover - not the main thread
            pass
