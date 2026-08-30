"""The harness's own safety net, which `finally` could not provide (CHG-20260828-18).

`mutation_check.run()` restores in a `finally`, on the argument that *"leaving a mutated tree behind
is a worse outcome than any result this function can report"*. `finally` does not run when the
process is **killed**, and a timeout sends SIGTERM. A run stopped that way left
`src/ai_sdlc_runner/worktree.py` holding `if False:` in `_copy_artifact`; only `git status` caught it
before it was committed.

## Why these are not in `test_mutation_check.py`

They were, and all four mutations came back CAUGHT **for the wrong reason**. That file also holds
`test_no_shipped_mutation_has_a_stale_anchor`, which walks every shipped mutation — so breaking
`mutation_recovery.py` on purpose made the *other* stranded mutations' anchors stale, and the
meta-test went red before any recovery test ran. `1 failed, 7 passed`, stopping at test eight, with
nothing about recovery exercised at all.

That is the exact failure this harness's own docstring warns about: a red that proves something, but
not the thing named. Splitting the file is what makes the red mean what the label says.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import mutation_check  # noqa: E402
import mutation_recovery  # noqa: E402

GREEN = {"tests/fake.py": True}


def _mutation(path: Path, before: str, after: str = "REPLACED", tests: str = "tests/fake.py"):
    return mutation_check.Mutation(
        group="fake", says="a guarantee returns", path=path, before=before, after=after,
        tests=tests)


@pytest.fixture
def source(tmp_path):
    def write(text):
        p = tmp_path / "subject.py"
        p.write_text(text, encoding="utf-8")
        return p
    return write

# ── the window, and what closes it ──────────────────────────────
#
# `run()` restores in a `finally`, on the argument that "leaving a mutated tree behind is a worse
# outcome than any result this function can report". `finally` does not run when the process is
# KILLED, and a timeout sends SIGTERM. A run stopped that way left `worktree.py` holding
# `if False:` in `_copy_artifact`; only `git status` caught it before it was committed.
#
# The dangerous version is quieter than that one was. A mutation that no test catches leaves a tree
# whose suite is still green, so nothing in `git status` looks alarming and nothing goes red.


@pytest.fixture
def sentinel(tmp_path, monkeypatch):
    """Point the harness's in-flight record at a temporary file, never the repository's own."""
    path = tmp_path / "in-flight.json"
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", path)
    return path


def _stranded(sentinel, source, original="ORIGINAL\n", mutated="MUTATED\n", on_disk=None):
    """The state a killed run leaves behind: a sentinel, and a file still holding the mutation."""
    subject = source(original)
    subject.write_text(mutated if on_disk is None else on_disk, encoding="utf-8")
    mutation_recovery.begin(subject, original, mutated)
    return subject


def test_a_file_a_killed_run_left_mutated_is_put_back(sentinel, source):
    subject = _stranded(sentinel, source)
    said = mutation_recovery.recover(quiet=True)

    assert subject.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert "restored" in said
    assert not sentinel.exists(), "the record outlived the thing it recorded"


def test_recovery_with_nothing_in_flight_does_nothing(sentinel, source):
    subject = source("ORIGINAL\n")
    assert mutation_recovery.recover(quiet=True) is None
    assert subject.read_text(encoding="utf-8") == "ORIGINAL\n"


def test_a_file_already_back_as_it_should_be_is_left_alone(sentinel, source):
    """A run killed *after* the restore but *before* the record was cleared."""
    subject = _stranded(sentinel, source, on_disk="ORIGINAL\n")
    said = mutation_recovery.recover(quiet=True)

    assert "already back" in said
    assert subject.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert not sentinel.exists()


def test_a_file_edited_since_the_run_died_is_refused_not_overwritten(sentinel, source):
    """The case worth refusing, and the reason the record holds both texts rather than one.

    Somebody fixed the file by hand — or moved on to real work in it — after the run died. Writing
    the recorded original over that would destroy work this tool cannot account for.
    """
    subject = _stranded(sentinel, source, on_disk="SOMETHING SOMEBODY ELSE WROTE\n")
    said = mutation_recovery.recover(quiet=True)

    assert subject.read_text(encoding="utf-8") == "SOMETHING SOMEBODY ELSE WROTE\n"
    assert "REFUSING" in said
    assert sentinel.exists(), "the original must survive, or the refusal strands the file for good"
    assert "reconcile it by hand" in said, "a refusal has to say what to do next"


def test_a_file_that_vanished_is_refused_rather_than_recreated(sentinel, source):
    subject = _stranded(sentinel, source)
    subject.unlink()
    assert "REFUSING" in mutation_recovery.recover(quiet=True)


def test_an_unreadable_record_is_discarded_and_said_so(sentinel, source):
    source("ORIGINAL\n")
    sentinel.write_text("{not json", encoding="utf-8")
    said = mutation_recovery.recover(quiet=True)

    assert "unreadable" in said and "git status" in said
    assert not sentinel.exists(), "an unparseable record must not block every later run"


def test_the_record_is_written_before_the_mutation_not_after(sentinel, source, monkeypatch):
    """The window this covers is between the two writes, so the order is the whole guarantee.

    `_pytest` is replaced with something that inspects the world at the moment the mutated file is
    on disk — which is exactly when a kill does the damage.
    """
    subject = source("keep ANCHOR keep\n")
    seen = {}

    def spy(tests):
        seen["file"] = subject.read_text(encoding="utf-8")
        seen["record"] = sentinel.read_text(encoding="utf-8") if sentinel.exists() else None
        raise KeyboardInterrupt("killed mid-run")

    monkeypatch.setattr(mutation_check, "_pytest", spy)
    with pytest.raises(KeyboardInterrupt):
        mutation_check.run(_mutation(subject, "ANCHOR"), GREEN)

    assert "REPLACED" in seen["file"], "the test did not observe the mutated state"
    assert seen["record"] is not None, "the mutation was applied before it was recorded"
    assert "keep ANCHOR keep" in seen["record"], "the record must hold the text to put back"


def test_the_record_exists_before_the_file_is_touched(sentinel, source, monkeypatch):
    """The ordering guarantee, observed *between* the two writes rather than after both.

    `test_the_record_is_written_before_the_mutation_not_after` above looks at the world when
    `_pytest` runs, by which point `begin` and `write` have both happened — in either order. So it
    passes against the inverted body it exists to reject: swapping the two lines in `apply` left the
    whole file green, while the harness reported `CAUGHT` because of a red the sentinel's own
    presence produced (CHG-20260830-07, defect seat).

    This one intercepts the write of the subject itself and asks what was true at that instant,
    which is the only moment the guarantee is about: a kill between the two leaves a mutated file
    with no record of what it used to be.
    """
    subject = source("ORIGINAL\n")
    seen = {}
    write = mutation_recovery.write

    def spy(path, text):
        if path == subject:
            seen["record_was_already_there"] = sentinel.exists()
        write(path, text)

    monkeypatch.setattr(mutation_recovery, "write", spy)
    mutation_recovery.apply(subject, "ORIGINAL\n", "MUTATED\n")

    assert seen.get("record_was_already_there") is True, (
        "the file was mutated before anything recorded how to put it back, so a kill in that window "
        "strands it")


def test_a_run_that_finishes_leaves_no_record_behind(sentinel, source, monkeypatch):
    subject = source("keep ANCHOR keep\n")
    monkeypatch.setattr(mutation_check, "_pytest",
                        lambda tests: type("P", (), {"returncode": 1, "stdout": "1 failed"})())
    mutation_check.run(_mutation(subject, "ANCHOR"), GREEN)

    assert subject.read_text(encoding="utf-8") == "keep ANCHOR keep\n"
    assert not sentinel.exists()


def test_this_repository_has_no_mutation_in_flight():
    """The guard that would have caught the incident, in the place a person actually looks.

    A mutation no test catches leaves a green suite over a mutated tree, so neither the suite nor a
    glance at `git status` says anything is wrong. This does.

    ## Why a live owner is skipped rather than failed

    It guards against a **killed** run's leftover. A run that is alive and holding the record is not
    that, and failing on it made this test fire during every mutation of the `stranded` group —
    which `_pytest` runs with `-x`, so the run stopped here, at test nine of fifteen, and the four
    tests that pin the lock never executed. The harness then reported `CAUGHT` for a red that the
    sentinel's own presence produced. Measured: with a record on disk, pristine source and mutated
    source both gave `1 failed, 8 passed` with the same single failure, for every mutation in the
    group (CHG-20260830-07, defect seat).

    So the guarantee is unchanged and the trigger is narrowed to the case it names. A record whose
    owner is gone still fails, which is the incident this exists for.
    """
    if mutation_recovery.IN_FLIGHT.exists():
        owner = mutation_recovery._owner()
        if mutation_recovery._alive(owner):
            pytest.skip(f"a mutation run (pid {owner}) is holding this worktree right now, which is "
                        f"not the killed-run leftover this guards against")

    assert not mutation_recovery.IN_FLIGHT.exists(), (
        f"{mutation_recovery.IN_FLIGHT} exists and the run that wrote it is gone, so a source file "
        f"may still be mutated. `python3 tools/mutation_check.py --recover` puts it back. If that "
        f"refuses, read that file: it holds the original text, so restore by hand from there rather "
        f"than deleting it.")


def test_begin_refuses_when_a_record_is_already_there(sentinel, source):
    """Exclusive creation, on its own — and on its own it is **not** the lock.

    This reaches `begin` directly, which is not the path a second run takes: `mutation_check.main()`
    calls `recover()` first. Under its old name (`..._a_second_run_in_the_same_worktree_is_refused`)
    this test was cited as evidence that two runs could not collide, and it could not see that
    `recover()` was deleting the first run's record on the way in. The scenario it claimed is now
    driven, through that sequence and against a live owner, by the test below (CHG-20260830-06).
    """
    subject = source("ORIGINAL\n")
    mutation_recovery.begin(subject, "ORIGINAL\n", "MUTATED\n")

    with pytest.raises(mutation_recovery.MutationInFlight) as caught:
        mutation_recovery.begin(subject, "SOMETHING ELSE\n", "ALSO ELSE\n")

    said = str(caught.value)
    assert "another mutation run" in said or "already exists" in said
    assert "recover" in said, "the refusal has to say how to get out of it"
    # And the first run's way back is intact, which is the thing the lock protects.
    assert json.loads(sentinel.read_text(encoding="utf-8"))["original"] == "ORIGINAL\n"


#: What a first run does and then keeps doing: take the lock, mutate the file, stay alive. Run as a
#: real child process because both halves of "another run" have to be true — a *different* pid, and
#: one that is genuinely running. A pid invented by hand is either dead or this process, and those
#: are the two cases where recovery is supposed to proceed.
_HOLDER = (
    "import sys, time, pathlib;"
    "sys.path.insert(0, sys.argv[1]);"
    "import mutation_recovery as mr;"
    "mr.IN_FLIGHT = pathlib.Path(sys.argv[2]);"
    "mr.apply(pathlib.Path(sys.argv[3]), sys.argv[4], sys.argv[5]);"
    "print('holding', flush=True);"
    "time.sleep(60)")


@pytest.fixture
def live_pids():
    """One pid that is running and one that certainly is not, both real.

    The dead one is a process that has actually exited rather than a number chosen for looking
    unused: a made-up pid can be reused, and a test that depends on it is a test that fails on a
    busy machine for a reason that has nothing to do with the code.
    """
    alive = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    yield alive.pid, dead.pid
    alive.kill()
    alive.wait()


@pytest.fixture
def holder(sentinel, source):
    """A first run holding the lock, through `apply` — not a record written by hand.

    Writing the record directly was enough to make every assertion below pass while `begin` had
    stopped recording an owner at all: the fixture supplied the field the code under test was no
    longer producing. Measured, on the first version of these tests (CHG-20260830-06).
    """
    started = []

    def start(original="ORIGINAL\n", mutated="MUTATED\n"):
        subject = source(original)
        handle = subprocess.Popen(
            [sys.executable, "-c", _HOLDER, str(TOOLS), str(sentinel), str(subject),
             original, mutated],
            stdout=subprocess.PIPE, text=True)
        started.append(handle)
        assert handle.stdout.readline().strip() == "holding", "the holder never took the lock"
        assert subject.read_text(encoding="utf-8") == mutated
        return handle, subject

    yield start
    for handle in started:
        handle.kill()
        handle.wait()


def test_a_live_process_reads_as_alive_and_a_dead_one_as_dead(live_pids):
    """The floor under every refusal in this module. It had none.

    `ACC-20260830-06` row 16 checked only that `_alive` does not *kill* what it asks about. Nothing
    checked whether it answers correctly, and it did not: three seats of the round-3 panel found
    three separate wrong answers in it (CHG-20260830-07).
    """
    alive, dead = live_pids

    assert mutation_recovery._alive(alive) is True
    assert mutation_recovery._alive(dead) is False
    assert mutation_recovery._alive(os.getpid()) is True
    assert mutation_recovery._alive(None) is False


def test_a_process_this_one_may_not_inspect_reads_as_alive():
    """Denied is not dead, and reading it as dead is the silent failure this module exists to close.

    Concrete: pid 4 on Windows is the System process. It is certainly running, and `OpenProcess`
    returns NULL with `ERROR_ACCESS_DENIED` (5) rather than `ERROR_INVALID_PARAMETER` (87), which is
    what a pid that does not exist gives. The first version collapsed both to `False`, so recovery
    would have written the original over the live mutated file of any run owned by another user —
    exactly the failure the owner check was added to prevent.

    The POSIX branch has always had this right (`except PermissionError: return True`); it was the
    Windows branch, on the platform this module exists for, that did not.
    """
    if os.name != "nt":
        pytest.skip("pid 4 is a Windows thing; the POSIX branch is covered by its own except clause")

    assert mutation_recovery._alive(4) is True, (
        "a running process this one may not open was reported dead, which lets recovery write over "
        "a live run's mutated file")


def test_a_process_that_exited_with_259_is_not_mistaken_for_a_running_one():
    """259 is `STILL_ACTIVE`. A process may exit with it, and then it is not still active.

    This is why liveness is asked with `WaitForSingleObject` rather than by comparing
    `GetExitCodeProcess` against that constant. Wrong, it deadlocks the worktree: `recover` refuses
    for ever, `main` exits 1 before reaching `--recover`, and the file can only be freed by hand.
    """
    exited = subprocess.Popen([sys.executable, "-c", "raise SystemExit(259)"])
    exited.wait()
    assert exited.returncode == 259, "the fixture did not produce the code this test is about"

    assert mutation_recovery._alive(exited.pid) is False


def test_a_second_run_does_not_recover_over_a_live_run(sentinel, holder):
    """The sequence every real second run takes, which no test reached before.

    `main()` calls `recover()` before its first `apply()`. A record left by a killed run and a record
    held by a run that is mutating that file *right now* are identical on disk, so recovery took the
    second for the first: it wrote the original over a live mutated file, and that run's tests then
    measured unmutated source and reported `NOT CAUGHT` for a mutation they do catch. Three seats of
    the CHG-20260830-05 panel found this independently, one of them by veto.

    So the assertion is on the first run's state, not on the second run's return value: its file must
    still be mutated and its way back must still be on disk.
    """
    first, subject = holder()

    said = mutation_recovery.recover(quiet=True)

    assert subject.read_text(encoding="utf-8") == "MUTATED\n", (
        "recovery wrote over a file a live run was measuring; that run now reports on the wrong "
        "source")
    assert sentinel.exists(), "recovery deleted the live run's only way back"
    assert json.loads(sentinel.read_text(encoding="utf-8"))["owner"] == first.pid
    assert said and said.startswith("REFUSING"), said
    assert str(first.pid) in said, "the refusal has to name the run being waited for"
    # And the lock still holds against the second run, which is what it could not do before.
    with pytest.raises(mutation_recovery.MutationInFlight):
        mutation_recovery.begin(subject, "ORIGINAL\n", "MUTATED\n")


def test_a_killed_run_is_still_recovered_automatically(sentinel, holder):
    """The property the owner check must not cost.

    Recovery at startup is the *guarantee* on Windows, where `kill` becomes `TerminateProcess` and no
    handler fires. Putting recovery behind an explicit flag would have closed the hole above by
    giving up this — so the owner is checked for liveness rather than for existence, and a dead owner
    recovers exactly as it did before.
    """
    killed, subject = holder()
    killed.kill()
    killed.wait()

    said = mutation_recovery.recover(quiet=True)

    assert subject.read_text(encoding="utf-8") == "ORIGINAL\n"
    assert not sentinel.exists(), "a record that outlives its run makes every later run announce it"
    assert said == f"restored {subject.name}, which a killed run left mutated"


def test_a_run_does_not_drop_a_record_it_does_not_own(sentinel, holder):
    """The other half of the same collision, and the one that strands a file for good.

    The first run finishes and calls `restore`, whose `end()` cleared whatever record was on disk —
    by then the *second* run's. A kill of the second run afterwards leaves its file mutated with
    nothing saying what the original was (CHG-20260830-06, defect seat).
    """
    first, subject = holder()

    mutation_recovery.restore(subject, "ORIGINAL\n")

    assert sentinel.exists(), "a finishing run deleted another run's way back"
    assert json.loads(sentinel.read_text(encoding="utf-8"))["owner"] == first.pid


def test_a_run_still_drops_its_own_record(sentinel, source):
    """Or the refusal above becomes permanent after the first run in any worktree."""
    subject = source("ORIGINAL\n")
    mutation_recovery.begin(subject, "ORIGINAL\n", "MUTATED\n")

    mutation_recovery.restore(subject, "ORIGINAL\n")

    assert not sentinel.exists()


def test_the_lock_is_released_when_the_run_puts_the_file_back(sentinel, source):
    """Otherwise the first refusal above would be permanent."""
    subject = source("ORIGINAL\n")
    mutation_recovery.apply(subject, "ORIGINAL\n", "MUTATED\n")
    mutation_recovery.restore(subject, "ORIGINAL\n")

    assert not sentinel.exists()
    mutation_recovery.begin(subject, "ORIGINAL\n", "MUTATED\n")      # no refusal
    mutation_recovery.end()
