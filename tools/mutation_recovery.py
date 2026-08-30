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
import os
import signal
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent

#: Written before a file is mutated, removed after it is put back. Also the lock — see `begin`.
IN_FLIGHT = REPO / "tools" / ".mutation-in-flight.json"


class MutationInFlight(Exception):
    """Another run holds this worktree, or a killed one left its file mutated."""


def _alive(pid: Optional[int]) -> bool:
    """Is that process still running? A record whose owner is alive must not be recovered over.

    `os.kill(pid, 0)` is the usual spelling and is **wrong here**: on Windows, Python's `os.kill`
    calls `TerminateProcess` for every signal but the two console events, so the liveness probe
    would kill the run it is asking about. Hence the explicit branch.

    Three ways to answer this wrongly, all of them shipped once and all of them measured out:

    - `OpenProcess` denied is **alive**, not dead. The first version returned `False`, which put the
      silent failure straight back: recovery over a live run owned by another user.
    - `GetExitCodeProcess == STILL_ACTIVE` cannot tell a running process from one that exited with
      code 259. `WaitForSingleObject` can.
    - `WaitForSingleObject` needs `SYNCHRONIZE`; without it every live process reads as dead.

    What remains: a pid reused after the owner exits reads as alive, so recovery refuses a file a
    killed run left mutated. That leaves the tree wrong but says so loudly, and the refusal names the
    way out. It is the direction to fail in, not a direction that is safe.
    """
    if pid is None:
        return False
    if os.name == "nt":
        import ctypes

        #: Both rights are needed, and asking for only the first is a silent wrong answer:
        #: `WaitForSingleObject` requires `SYNCHRONIZE`, and without it the wait returns WAIT_FAILED
        #: rather than WAIT_TIMEOUT, so every live process reads as dead. Measured while writing
        #: this — the first version of the fix broke the case it was not about.
        PROCESS_QUERY_LIMITED_INFORMATION, SYNCHRONIZE = 0x1000, 0x00100000
        #: What `OpenProcess` sets when the pid exists but this process may not look at it — another
        #: user, or a higher integrity level. Distinct from ERROR_INVALID_PARAMETER (87), which is
        #: what a pid that does not exist gives, so the two are separable and must be separated.
        ERROR_ACCESS_DENIED = 5
        #: `WaitForSingleObject` on a process handle: still running.
        WAIT_TIMEOUT = 0x102

        kernel32 = ctypes.windll.kernel32
        # Typed deliberately, all three. A HANDLE is pointer-sized and ctypes defaults every foreign
        # function to `c_int`, so an untyped handle is truncated on 64-bit — and an untyped handle
        # *argument* raises `ArgumentError: int too long to convert`, which escapes `_alive` as an
        # exception rather than an answer.
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            # Alive, and not ours to inspect. Reading this as dead is the silent failure this whole
            # mechanism exists to remove: recovery would write the original over a live run's
            # mutated file. The POSIX branch below has always answered this correctly; the first
            # version of this branch did not (CHG-20260830-07, three seats).
            return kernel32.GetLastError() == ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                                    # alive, and owned by somebody else
    return True


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

    Exclusive creation alone was **not** enough, and CHG-20260830-05 shipped it claiming it was.
    `mutation_check.main()` calls `recover()` before its first `apply()`, so the second run deleted
    the first one's record on the way in and then took the lock uncontended — measured: the second
    run wrote the original over the first run's *live* mutated file, and the first run went on to
    report `NOT CAUGHT` for a mutation its tests do catch. The record therefore carries `owner`, and
    recovery refuses while that pid is alive (CHG-20260830-06, three seats).

    This is not hypothetical. A review panel of four agents was run in one worktree while one of
    them was running the harness: two seats read a half-mutated tree, one got a false positive from
    it, and a third measured a 252-test run against source that was changing underneath it. Nothing
    was lost, because the runs happened not to overlap on the same file — the lock is what makes
    that a guarantee rather than luck (CHG-20260830-05, risk seat).
    """
    record = json.dumps({"path": str(path), "original": original, "mutated": mutated,
                         "owner": os.getpid()}, ensure_ascii=False)
    try:
        with io.open(IN_FLIGHT, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(record)
    except FileExistsError:
        raise MutationInFlight(
            f"{IN_FLIGHT.name} already exists, so another mutation run holds this worktree — or a "
            f"previous one was killed and its file is still mutated. Wait for that run, or if none "
            f"is running, `python tools/mutation_check.py --recover` puts the file back. Two runs "
            f"at once would overwrite the record the first one needs to put its file back.") from None


def _owner() -> Optional[int]:
    """The pid in the record on disk, or `None` if there is no readable record."""
    try:
        return json.loads(io.open(IN_FLIGHT, encoding="utf-8").read()).get("owner")
    except (OSError, ValueError, AttributeError):
        return None


def end() -> None:
    """Drop the record — but only our own.

    A run that ends does not get to clear a record it did not write. Without this check the first
    run's `finally: restore()` unlinks the *second* run's record, so a kill of the second one
    afterwards strands its file with nothing saying how to put it back (CHG-20260830-06, defect
    seat).
    """
    owner = _owner()
    if owner is not None and owner != os.getpid():
        return
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

    Called at startup — before the first `apply()`, which is why this is also the code a *second*
    run reaches while the first is still mutating — and from the signal handler, so an interrupted
    run cleans up immediately rather than leaving the tree wrong until somebody runs this again.
    """
    if not IN_FLIGHT.exists():
        return None
    try:
        record = json.loads(io.open(IN_FLIGHT, encoding="utf-8").read())
        path = Path(record["path"])
        original, mutated = record["original"], record["mutated"]
    except (OSError, ValueError, KeyError):
        IN_FLIGHT.unlink(missing_ok=True)
        return "the in-flight record was unreadable and has been discarded; check `git status`"

    owner = record.get("owner")
    if owner != os.getpid() and _alive(owner):
        # The whole reason the record carries an owner. "A killed run left this mutated" and
        # "another run is mutating this right now" look identical on disk, and the recovery that is
        # right for the first is a corruption of the second: it writes the original over a live
        # mutated file, so that run's tests measure unmutated source and it reports NOT CAUGHT.
        said = (f"REFUSING to recover {path.name}: pid {owner} is still running and holds this "
                f"worktree, so {path.name} is mutated on purpose and must be left alone. Wait for "
                f"that run.\n"
                f"  If no such run exists, the pid has been reused. {path.name} is then still "
                f"mutated and {IN_FLIGHT.name} holds the text to put back — read the original out "
                f"of it, or `git checkout -- {path}`, and only then delete the record. Deleting it "
                f"first throws away the only copy.")
        if not quiet:
            print(f"  {said}")
        return said

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
    # Not `end()`. That one refuses to drop a record it does not own, which is right for a run
    # clearing up after itself and wrong here: recovery's whole job is clearing up after a run that
    # is *gone*, and the liveness check above has already established that it is.
    IN_FLIGHT.unlink(missing_ok=True)
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
