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
from _pytest.outcomes import Skipped

NEWLINE = chr(10)

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

    ## Why the harness announces itself instead of being inferred

    It guards against a **killed** run's leftover. A run in progress legitimately holds the record,
    so it has to be excused — and CHG-20260830-07 excused it by asking whether the record's owner
    was still *alive*. That was wrong in both directions, and round 4 measured both:

    - a mutation that broke `_alive` made the owner read dead, so this test **failed** rather than
      skipping. `_pytest` runs with `-x`, so the run stopped here and the tests written for `_alive`
      never executed — 2 of 11 `stranded` mutations were reported `CAUGHT` by this test's red rather
      than by the test that names them.
    - a genuinely stranded tree whose dead owner's pid had been reused, or whose owner this process
      may not open, read as **alive** — so the guard skipped, the suite returned `rc=0` over a
      mutated `src/` file, and the record is gitignored so `git status` said nothing either. That is
      the *quiet* failure this module's docstring exists to describe, with the detector disarmed.

    `MUTATION_RUN` is set by `mutation_check._pytest` and read here. Being *set* is not enough — see
    the comment on the check itself: one stray `export MUTATION_RUN=1` would otherwise disarm this
    repository's detector everywhere. It must also **own the record**, which is an identity between
    two things the harness wrote. No inference, and no coupling to `_alive`.

    (The first version of this paragraph ended at *"everything else is a leftover and fails"*,
    which is the argument for the weaker check the inline comment exists to reject — two
    contradictory arguments in one test. Corrected in CHG-20260831-01, idiom seat.)
    """
    # **Both** paths, and that is the point. `MUTATION_IN_FLIGHT` moves `IN_FLIGHT`, so checking
    # only that one made a leaked value a single-`export` off switch for this guard: with a real
    # stranded record at the default location, an ordinary `pytest tests/` passed. Measured, and
    # vetoed (CHG-20260831-01, conformance seat). Moving the record can hide nothing if the default
    # is still read.
    records = {mutation_recovery.DEFAULT_IN_FLIGHT, mutation_recovery.IN_FLIGHT}
    present = sorted(p for p in records if p.exists())

    # Ownership **per path**, not across all of them at once. Comparing a set of owners against the
    # announced pid meant one unowned record made every record look unowned — and during a real
    # mutation run there are two: the harness's, at the default, and one planted at the override by
    # the test below. The guard then failed in the harness's own state with nothing mutated, `-x`
    # stopped the run there, and every mutation in the group returned non-zero whatever it did. The
    # instrument went constant again (CHG-20260831-02, risk seat).
    announced = os.environ.get("MUTATION_RUN")
    owned = int(announced) if announced and announced.isdigit() else None

    # `owned is None` first, and it is the whole fix. `_owner` also returns `None` for a record it
    # cannot read — no `owner` key, `null`, truncated JSON, an empty file — so comparing them made
    # "nobody announced a run" and "this record will not say who owns it" the same answer, and the
    # guard excused the second. Measured on the CI path, where `MUTATION_RUN` is unset: four record
    # states went from red to **green**, including the truncated file a kill mid-write leaves, which
    # is the leftover this guard exists for (CHG-20260831-03, risk and idiom seats).
    #
    # Unreadable is not owned. Only a record that names the announced pid is excused.
    excused = [p for p in present
               if owned is not None and mutation_recovery._owner(p) == owned]
    present = [p for p in present if p not in excused]

    if excused and not present:
        # `excused`, not `announced`. Skipping on the variable meant one stray `export
        # MUTATION_RUN=1` in a shell — or the name appearing in any CI environment — disarmed this
        # repository's stranded-tree detector everywhere, permanently and silently: with no record
        # on disk at all the guard skipped, reporting that a run "owns the record" over a tree that
        # held none (CHG-20260831-03, defect and idiom seats). A skip now requires a record that
        # exists **and** names the announced pid. `_pytest` sets `MUTATION_RUN` to `os.getpid()` and
        # `begin` writes that same pid as the owner, so that is an identity between two things the
        # harness wrote, not an inference about a process (CHG-20260830-09, risk seat).
        pytest.skip(f"mutation run {announced} started this pytest and owns "
                    f"{', '.join(str(p) for p in excused)}; that is not the killed-run leftover "
                    f"this guards against")

    assert not present, (
        f"{', '.join(str(p) for p in present)} exists and no mutation run started this pytest, so a "
        f"source file may still be mutated. Start with `python3 tools/mutation_check.py --recover`: "
        f"it puts the file back when the recorded owner is gone, and refuses without touching "
        f"anything when it cannot tell.\n"
        f"  If it refuses, open the record. It may still hold the only copy of some original \n"
        f"text even when it is truncated — that is why `--recover` keeps it rather than \n"
        f"discarding it. Put back whatever it names; use `git status` and `git diff` for \n"
        f"whatever it does not. Delete it only once the tree is reconciled: it is what keeps \n"
        f"this red until somebody has looked.")


def _guard_says(tmp_path, record, env):
    """Run the in-flight guard as its own pytest, against a record and an environment we choose.

    In-process would test nothing: the guard reads the environment and the record on disk, and that
    is the whole point of it. So it is driven the way it actually runs — but pointed at a record of
    its own.

    ## Why not the real record

    The first version wrote and then unlinked `mutation_recovery.IN_FLIGHT` itself. Every one of the
    twelve `stranded` mutations runs this file, so during a mutation run this helper deleted the
    harness's own record — the thing that is both the way back and the lock — while a source file
    sat mutated on disk. Measured by the round-5 risk seat: absent for 2.1s of a 9.8s window, with
    `all 12 caught` printed and nothing reporting it. A kill in that window leaves a mutated file
    with no record of what it was, `--recover` then says *nothing in flight*, and a second run takes
    the lock uncontended. That is the incident this whole module exists for, opened by the test
    written to prove the guard against it (CHG-20260830-09).
    """
    theirs = tmp_path / "in-flight.json"
    if record is None:
        # Not a leftover from the previous call: the "clean tree" case has to run against no record,
        # and these calls share one `tmp_path`. The first version counted calls with
        # `len(list(tmp_path.iterdir()))` and made a directory each time — a shape used nowhere
        # else in this suite, to solve what one `else` solves. Unlinking is safe here, unlike in the
        # version this replaced, because `theirs` is a temporary path and never the live record
        # (CHG-20260831-01, idiom seat).
        theirs.unlink(missing_ok=True)
    else:
        mutation_recovery.write(theirs, record)
    return subprocess.run(
        [sys.executable, "-m", "pytest",
         f"{Path(__file__).name}::test_this_repository_has_no_mutation_in_flight",
         "-q", "-p", "no:randomly", "--no-header", "--tb=no"],
        cwd=Path(__file__).resolve().parent, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
             "MUTATION_IN_FLIGHT": str(theirs), **env})


def test_the_harness_tells_the_child_it_is_a_mutation_run(monkeypatch):
    """The writer half of the contract the guard reads. Nothing pinned it.

    Deleting `MUTATION_RUN` from `_pytest`'s environment left 30 tests green — and then every
    `stranded` mutation went back to being credited to the guard at test 10 under `-x` instead of
    the test that names it, which is the exact failure CHG-20260830-08 was written to remove. The
    reader half was pinned; this end was asserted in a record and by nothing else
    (CHG-20260830-09, defect seat).
    """
    seen = {}

    def spy(argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(mutation_check.subprocess, "run", spy)
    mutation_check._pytest("tests/fake.py")

    assert seen.get("MUTATION_RUN") == str(os.getpid()), (
        "the harness did not tell its own pytest that a mutation run is in progress, so the "
        "in-flight guard will fail during every mutation and mask the test that should have failed")


def test_the_guard_reads_the_default_path_even_when_the_override_moves_it(tmp_path, monkeypatch):
    """The half of CHG-20260831-01 that nothing held.

    That change made the guard read both the default record path and wherever `MUTATION_IN_FLIGHT`
    points, because reading only the override made a leaked value a one-`export` off switch. It
    recorded the fix as pinned. It was not: reverting `records` to `{IN_FLIGHT}` left the whole file
    green — 23 passed, nothing red (CHG-20260831-02, conformance seat).

    Driven in-process against two temporary paths. The child-process helper cannot do this one: the
    state it needs is a record at the *default* location, and that location is the repository's own.
    Writing there is what the round-5 veto was about.
    """
    default, moved = tmp_path / "default.json", tmp_path / "moved.json"
    monkeypatch.setattr(mutation_recovery, "DEFAULT_IN_FLIGHT", default)
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", moved)
    monkeypatch.delenv("MUTATION_RUN", raising=False)
    mutation_recovery.write(default, json.dumps(
        {"path": "x", "original": "a", "mutated": "b", "owner": 999999}))

    _guard_must_fail("a record at the default path, override elsewhere")


def test_the_harness_refuses_to_run_with_the_record_moved(tmp_path):
    """The override is for the guard's own test, and for nothing else.

    A mutation run that honoured it would mutate source while the default record stayed absent —
    so `--recover` from an ordinary shell prints *"nothing in flight; the tree is as it should be"*
    and exits **0** over a mutated file, and the record is also the lock, so a second run takes it
    uncontended. Measured before this refusal existed (CHG-20260831-01, risk seat).

    CHG-20260830-09 claimed a leaked value "points the harness at a file it will not find, which
    fails loudly". It does not — `begin()` *creates* the record, so every writable value is the
    silent case. This is what makes that sentence true.
    """
    moved = tmp_path / "somewhere-else.json"
    result = subprocess.run(
        [sys.executable, str(TOOLS / "mutation_check.py"), "--recover"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=TOOLS.parent,
        env={**os.environ, "PYTHONPATH": "src", "MUTATION_IN_FLIGHT": str(moved)})

    assert result.returncode == 1, (
        f"the harness ran with its record moved out from under the guard: {result.stdout[-300:]}")
    assert "MUTATION_IN_FLIGHT" in result.stdout + result.stderr
    assert "Unset the variable" in result.stdout + result.stderr, (
        "a refusal has to say what to do next")


@pytest.mark.skipif(bool(os.environ.get("MUTATION_RUN")),
                    reason="a mutation run holds the real record at the default path; this test "
                           "drives the guard against records it plants itself, and cannot control "
                           "that one")
def test_the_guard_fails_on_a_leftover_record_and_skips_only_for_a_running_harness(tmp_path):
    """The branch that decides whether this repository's stranded-tree detector is armed.

    Nothing drove it. CHG-20260830-07 changed the condition and recorded the change as verified;
    round 4 measured the result as a green suite over a genuinely mutated `src/` file, because the
    condition it chose — *is the recorded owner alive* — read `True` for a reused pid. The branch is
    the guard, so the branch needs a test (CHG-20260830-08, defect seat).

    Both directions, through a real pytest, because the guard reads the real environment.
    """
    owner = 4242
    held = json.dumps({"path": "x", "original": "a", "mutated": "b", "owner": owner})

    leftover = _guard_says(tmp_path, held, {"MUTATION_RUN": ""})
    running = _guard_says(tmp_path, held, {"MUTATION_RUN": str(owner)})
    stray = _guard_says(tmp_path, held, {"MUTATION_RUN": "1"})
    clean = _guard_says(tmp_path, None, {"MUTATION_RUN": ""})

    assert leftover.returncode != 0, (
        "a record left behind with no mutation run in progress did not fail the guard, so a killed "
        f"run's mutated file would ship silently: {leftover.stdout[-400:]}")
    assert "1 skipped" in running.stdout, (
        f"the guard did not excuse the run that owns the record: {running.stdout[-400:]}")
    assert stray.returncode != 0, (
        "a `MUTATION_RUN` that does not own the record still excused the guard, so one stray "
        f"`export` disarms this repository's stranded-tree detector: {stray.stdout[-400:]}")
    assert clean.returncode == 0, f"the guard failed on a clean tree: {clean.stdout[-400:]}"


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


@pytest.mark.skipif(os.name != "nt", reason="259 is a Windows constant, and POSIX masks exit codes "
                                            "to 8 bits (259 & 0xFF == 3), so the ambiguity this is "
                                            "about cannot be constructed there")
def test_a_process_that_exited_with_259_is_not_mistaken_for_a_running_one():
    """259 is `STILL_ACTIVE`. A process may exit with it, and then it is not still active.

    This is why liveness is asked with `WaitForSingleObject` rather than by comparing
    `GetExitCodeProcess` against that constant. Wrong, it deadlocks the worktree: `recover` refuses
    for ever, `main` exits 1 before reaching `--recover`, and the file can only be freed by hand.

    Windows-only, and the first version was not. CI caught it: `SystemExit(259)` on Linux gives a
    return code of **3**, because POSIX keeps the low eight bits. The assertion below is what
    reported that rather than letting the test pass against a process which had not done the thing
    the test is named for — a platform truth written as a universal one, which is the same shape as
    `test_a_cjk_name_is_judged_by_the_platform_that_will_store_it` in `test_paths.py`.
    """
    exited = subprocess.Popen([sys.executable, "-c", "raise SystemExit(259)"])
    exited.wait()
    assert exited.returncode == 259, "the fixture did not produce the code this test is about"

    assert mutation_recovery._alive(exited.pid) is False


def test_the_posix_branch_reads_a_process_it_may_not_signal_as_alive(monkeypatch):
    """The same denied-is-alive rule, on the other branch — and nothing was driving it.

    `except PermissionError: return True` is the POSIX half of the answer the Windows half got wrong,
    and both this module's docstring and the skip reason on the 259 test above cited it as the
    already-correct precedent. Round 4 enumerated every `_alive` call in the suite and found none
    that raises `PermissionError`: the clause the argument rested on was executed by nothing, on any
    platform (CHG-20260830-08, defect seat).

    `_alive_posix` is called directly, which is why it is its own function. Reaching it through
    `_alive` would mean standing in for `os.name` — and `mutation_recovery.os` *is* the `os` module,
    so that patches it for the whole process and `pathlib` stops being able to make a `Path`.
    Measured, while writing this: `NotImplementedError: cannot instantiate 'PosixPath' on your
    system`, from a test that had nothing to do with paths.
    """
    def denied(pid, sig):
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(mutation_recovery.os, "kill", denied)
    assert mutation_recovery._alive_posix(4321) is True, (
        "a process this one may not signal was read as dead, so recovery would overwrite its file")

    def gone(pid, sig):
        raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(mutation_recovery.os, "kill", gone)
    assert mutation_recovery._alive_posix(4321) is False

    monkeypatch.setattr(mutation_recovery.os, "kill", lambda pid, sig: None)
    assert mutation_recovery._alive_posix(4321) is True


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
    # The advice, not just the shape. `git checkout --` restores from the *index*, so it writes a
    # staged mutation back — and the sentence after it used to say to delete the record that proves
    # it. Removing that was the whole of CHG-20260830-08 task 9, and nothing held a word of it: the
    # 451 characters could be cut with the file still green. Its sibling refusal is pinned the same
    # way, at `test_a_file_edited_since_the_run_died_is_refused_not_overwritten`
    # (CHG-20260830-09, idiom seat).
    assert "Not `git checkout --`" in said, (
        "the refusal has to warn against `git checkout --` by name: it restores from the index, so "
        "a staged mutation gets written back over the file it is telling the operator to rescue")
    assert sentinel.name in said, "the refusal has to name the record, which is the only way back"
    assert "only copy" in said, "the operator has to be told not to delete it first"
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


#: Record bodies a killed run can leave, and what each says about who owns it. Every one of these
#: went from red to **green** when the guard compared `_owner(p)` against the announced pid without
#: checking whether anything had been announced: `_owner` returns `None` for a record it cannot
#: read, so "nobody is running" and "this record will not say" became the same answer
#: (CHG-20260831-03, risk and idiom seats).
def _guard_must_fail(why):
    """Run the in-flight guard and require it to **fail** — a skip is not an acquittal.

    Written because the first draft of these tests could not tell the two apart. Both halves of
    the guard fix were reverted and the suite reported `31 passed, 4 skipped` and `34 passed,
    1 skipped` — green both times, because `pytest.skip` raises `Skipped` and `pytest.raises(
    AssertionError)` lets it straight through. Tests written to close a silent-disarm defect,
    disarmed silently (CHG-20260831-03, found by reverting the fix rather than by a seat).
    """
    try:
        test_this_repository_has_no_mutation_in_flight()
    except Skipped as skipped:
        pytest.fail(f"{why}: the guard skipped instead of failing — {skipped}")
    except AssertionError as failed:
        assert "may still be mutated" in str(failed), failed
        return
    pytest.fail(f"{why}: the guard passed")


UNOWNED_RECORDS = [
    ('{"path": "x", "original": "a", "mutated": "b", "owner": 999999}', "a pid that is gone"),
    ('{"path": "x", "original": "a", "mutated": "b"}', "no owner key at all"),
    ('{"path": "x", "original": "a", "mutated": "b", "owner": null}', "an owner of null"),
    ('{not json', "truncated, which is what a kill mid-write leaves"),
    ("", "an empty file"),
    # Valid JSON that is not an object. `record["path"]` raised `TypeError`, which the except tuple
    # did not catch, so the branch whose refusal tells an operator to open the file and edit it by
    # hand answered a half-finished hand edit with a traceback (CHG-20260831-05, defect seat).
    ("[]", "a JSON list"),
    ("null", "a JSON null"),
    ('"just a string"', "a bare JSON string"),
    ('{"path": 5, "original": "a", "mutated": "b"}', "a path that is not a path"),
]


@pytest.mark.parametrize("body,shape", UNOWNED_RECORDS, ids=[c[1] for c in UNOWNED_RECORDS])
def test_a_record_nobody_owns_fails_the_guard(tmp_path, monkeypatch, body, shape):
    """With no run announced, every record present is a leftover — however unreadable it is.

    The unreadable ones matter most: `recover`'s own refusal tells an operator to *"reconcile it by
    hand, then delete that file"*, so a half-edited record is a state this module expects. Excusing
    it means going quiet over a worktree that may still hold a mutated source file whose only copy
    of the original is the record just excused.
    """
    record = tmp_path / "in-flight.json"
    record.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "DEFAULT_IN_FLIGHT", record)
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)
    monkeypatch.delenv("MUTATION_RUN", raising=False)

    _guard_must_fail(shape)


@pytest.mark.parametrize("body,shape", UNOWNED_RECORDS, ids=[c[1] for c in UNOWNED_RECORDS])
def test_a_record_nobody_owns_fails_even_while_a_run_is_announced(tmp_path, monkeypatch,
                                                                  body, shape):
    """Announcing a run excuses the record that run owns. It does not excuse the others.

    Same five shapes, `MUTATION_RUN` set this time — and that is a **different** guarantee from the
    twin above, not more evidence for the same one. Under the pre-fix guard every row here has
    `_owner(p) != 999998`, so all five were already kept and all five already failed: this test
    goes green against the defect the round was about, and its docstring used to claim otherwise
    (CHG-20260831-04, defect seat).

    What it does hold is that a run announcing itself gets no blanket excuse — only the record that
    names its pid. That is worth a test; it is just not the one the round's veto was about.
    """
    record = tmp_path / "in-flight.json"
    record.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "DEFAULT_IN_FLIGHT", record)
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)
    monkeypatch.setenv("MUTATION_RUN", "999998")

    _guard_must_fail(shape)


def test_the_guard_does_not_skip_over_a_tree_that_holds_no_record(tmp_path, monkeypatch):
    """A skip has to be about a record. It was about a variable.

    `if not present and announced` read "a run announced itself" as "a run owns the record", so
    one stray `export MUTATION_RUN=1` — or the name appearing in any CI environment — turned the
    stranded-tree detector into a skip forever, over a tree it had not looked at. Measured: with
    the variable set and nothing on disk the guard skipped, reporting that run "owns the record"
    (CHG-20260831-03, defect and idiom seats).
    """
    absent = tmp_path / "nothing-here.json"
    monkeypatch.setattr(mutation_recovery, "DEFAULT_IN_FLIGHT", absent)
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", absent)
    monkeypatch.setenv("MUTATION_RUN", "999998")

    # Passes, and does not skip. A clean tree is an answer, not an abstention.
    try:
        test_this_repository_has_no_mutation_in_flight()
    except Skipped as skipped:
        pytest.fail(f"nothing is on disk and the guard abstained anyway — {skipped}")


#: The two shapes a kill mid-write leaves. `--recover` used to delete both, print nothing, and
#: exit 0 (CHG-20260831-04, risk seat).
UNREADABLE_RECORDS = [
    ('{"path": "src/ai_sdlc_runner/models.py", "original": "THE ONLY COPY OF', "truncated"),
    ("", "an empty file"),
]


@pytest.mark.parametrize("body,shape", UNREADABLE_RECORDS,
                         ids=[c[1] for c in UNREADABLE_RECORDS])
def test_recover_keeps_a_record_it_cannot_read(tmp_path, monkeypatch, body, shape):
    """The remedy must not destroy the thing the refusal calls the only copy.

    The in-flight guard tells whoever trips it: *"it holds the original text, and is the only
    copy ... `python3 tools/mutation_check.py --recover` puts it back ... if it refuses, restore
    from the record by hand rather than deleting it."* For a truncated record and an empty one,
    that command unlinked the file, printed nothing and exited 0 — it deleted the only copy and
    reported success. Measured on both shapes (CHG-20260831-04, risk seat).

    The rule was already written in this function, twenty lines further down, about the
    edited-file case: *"a refusal that also throws away the original strands the file for good."*
    These are the two shapes that most needed it.
    """
    record = tmp_path / "in-flight.json"
    record.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert record.exists(), f"{shape}: the record was discarded, and it is the only copy"
    assert record.read_text(encoding="utf-8") == body, f"{shape}: the record was rewritten"
    assert said and said.startswith("REFUSING"), f"{shape}: {said!r}"
    assert "kept" in said, f"{shape}: the refusal has to say the file is still there"
    assert "git status" in said, (
        f"{shape}: for an empty or truncated record there is no original to put back, "
        f"so the working tree is the only thing that shows what a killed run left")


def test_recover_reports_an_unreadable_record_to_the_operator(sentinel, source, capsys,
                                                             monkeypatch):
    """Silence and exit 0 read as "nothing was wrong". `recover` returned a string nobody printed.

    Driven through `mutation_check.main(["--recover"])`, because the defect was in the wiring
    between `recover()`'s return value and what `--recover` does with it, not in either alone. Not
    through a subprocess with `MUTATION_IN_FLIGHT` set: the harness refuses on that variable before
    it reaches this branch, so a subprocess driven that way passes whatever `--recover` does — the
    first draft of this test did exactly that (CHG-20260831-04).
    """
    source("ORIGINAL")
    sentinel.write_text("", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["mutation_check.py", "--recover"])
    code = mutation_check.main()
    printed = capsys.readouterr().out

    assert sentinel.exists(), "the command that refuses to touch it deleted it"
    assert code != 0, f"exit 0 says the tree is fine; it is not: {printed!r}"
    assert "REFUSING" in printed, f"it said nothing at all: {printed!r}"


#: Record shapes a hand edit produces, and what `recover` must do with each. Every one of these
#: guards shipped unpinned: reverting any of the four left `45 passed` (CHG-20260831-07, defect
#: seat), and one of them — a non-integer `owner` — had turned a traceback into a silent overwrite.
#: A sentinel, because `None` is itself a shape worth testing.
REMOVE_KEY = object()

DESTRUCTIVE_SHAPES = [
    ({"original": None}, "an original that is null"),
    ({"original": 123}, "an original that is a number"),
    ({"mutated": []}, "a mutated that is a list"),
    ({"path": ""}, "an empty path"),
    ({"owner": "nope"}, "an owner that is a string"),
    ({"owner": [1]}, "an owner that is a list"),
    ({"owner": 1.5}, "an owner that is a float"),
    # `isinstance(True, int)` is True, so a bool owner passes an `isinstance(v, int)` gate and then
    # answers `_alive` as False — which is what lets `recover` act. The clause that stops it was
    # unpinned: deleting it left `54 passed` while a bool owner destroyed the file again, which is
    # byte-for-byte the defect the round before closed (CHG-20260901-01, defect seat).
    ({"owner": True}, "an owner that is a bool"),
    # And **absence**. `record.items()` cannot see a key that is not there, so deleting the `owner`
    # line — the hand edit this refusal invites — was not refused at all: the file was overwritten
    # and the record unlinked. If the owning run is alive, that is the corruption CHG-20260830-06
    # closed, reached through absence instead of through a type.
    ({"owner": REMOVE_KEY}, "no owner key at all"),
    ({"original": REMOVE_KEY}, "no original key at all"),
    ({"path": REMOVE_KEY}, "no path key at all"),
    # Two faults at once. The empty-`path` clause was gated on nothing else being wrong, so a
    # record that was both missing `original` and carrying a blank `path` was refused for one of
    # them and told about the other never — a diagnosis that is a strict subset of what the gate
    # decided, and the remedy beside it then said "the other fields were read and are intact"
    # about a `path` of `""` (CHG-20260901-04, conformance seat).
    ({"path": "", "original": REMOVE_KEY}, "an empty path and no original"),
    ({"path": "", "owner": "nope"}, "an empty path and an owner that is a string"),
    ({"original": REMOVE_KEY, "owner": REMOVE_KEY}, "neither an original nor an owner"),
]


@pytest.mark.parametrize("override,shape", DESTRUCTIVE_SHAPES,
                         ids=[c[1] for c in DESTRUCTIVE_SHAPES])
def test_recover_destroys_nothing_it_cannot_account_for(tmp_path, monkeypatch, override, shape):
    """Every one of these was reachable by the hand edit `--recover`'s own refusal invites.

    `"original": null` truncated the source file to `''` and left no copy anywhere; `"owner":
    "nope"` **restored the file and deleted the record**, because answering "not a process" for a
    pid it could not read is what lets `recover` act. The module's one rule is that a refusal must
    not throw away the original, and both broke it (CHG-20260831-07, conformance and defect seats).
    """
    victim = tmp_path / "target.py"
    victim.write_text("MUTATED SOURCE" + NEWLINE, encoding="utf-8")
    record = tmp_path / "in-flight.json"
    body = {"path": str(victim), "original": "ORIGINAL SOURCE" + NEWLINE,
            "mutated": "MUTATED SOURCE" + NEWLINE, "owner": 999999}
    body.update(override)
    for key in [k for k, v in override.items() if v is REMOVE_KEY]:
        del body[key]
    record.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert said and said.startswith("REFUSING"), f"{shape}: {said!r}"
    assert record.exists(), f"{shape}: the record was discarded"
    assert victim.read_text(encoding="utf-8") == "MUTATED SOURCE" + NEWLINE, (
        f"{shape}: the victim was written over on a record that could not be read")

    # The **message**, because that is what separates the shape gate from the `KeyError` arm above
    # it. Asserting only "REFUSING" let two of the three absence rows pass through the older arm and
    # pin nothing: `path`, `original` and `mutated` were subscripted before the gate, so `missing`
    # could only ever be `['owner']` (CHG-20260901-02, defect and risk seats).
    # The **diagnosis line**, not anywhere in the message. `field in said` was satisfied by the
    # remedy paragraph, which named `owner` unconditionally: sabotaging the diagnosis to say
    # "something is not there" left nine of eleven rows green (CHG-20260901-03, risk seat).
    # **Every** field the shape breaks, not the first one. `next(iter(override))` passed a record
    # broken two ways on the strength of one of them (CHG-20260901-04, conformance seat).
    diagnosis = said.split(NEWLINE)[0]
    for field in override:
        assert field in diagnosis, (
            f"{shape}: the first line has to name {field!r} — {diagnosis!r}")
    assert "cannot be read" not in said, (
        f"{shape}: this record reads as JSON; saying it does not sends the operator to the wrong "
        f"thing — {said!r}")

    # A remedy that says *delete* before it says *restore* destroys the only copy. Measured in a
    # scratch repo with the mutation staged: `git status` shows `M  target.py`, `git diff` is
    # **empty**, the file is still mutated and the record is gone. That was the advice this gate
    # gave for a missing `owner`, twelve lines above the rule it breaks — *"a refusal that also
    # throws away the original strands the file for good"* (CHG-20260901-04, risk seat).
    if "delete" in said:
        assert "back by hand" in said, (
            f"{shape}: it says to delete the record and never says to put the original back "
            f"first — {said!r}")
        assert said.index("delete") > said.index("back by hand"), (
            f"{shape}: delete comes before restore — {said!r}")


def test_write_refuses_a_non_string_before_it_truncates(tmp_path):
    """`io.open(path, "w")` truncates, then the write fails. The order is the whole defect."""
    target = tmp_path / "target.py"
    target.write_text("KEEP ME" + NEWLINE, encoding="utf-8")

    with pytest.raises(TypeError, match="destroy"):
        mutation_recovery.write(target, None)

    assert target.read_text(encoding="utf-8") == "KEEP ME" + NEWLINE


def test_recover_refuses_a_record_naming_something_that_is_not_a_file(tmp_path, monkeypatch):
    """`exists()` is true of a directory and opening one is a `PermissionError`, out of an
    unguarded read. The refusal has to name what it is refusing, which the first fix did not:
    `Path(".").name` is `""`, so it printed `REFUSING to touch :` (CHG-20260831-07, risk seat).
    """
    record = tmp_path / "in-flight.json"
    record.write_text(json.dumps(
        {"path": str(tmp_path), "original": "a", "mutated": "b", "owner": 999999}),
        encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert said.startswith("REFUSING"), said
    assert str(tmp_path) in said, f"the refusal must name what it will not touch: {said!r}"
    assert "edited it since" not in said, f"nobody edited a directory: {said!r}"
    assert record.exists()


def test_recover_refuses_a_record_naming_a_file_that_is_gone(tmp_path, monkeypatch):
    """Moved, or a record from another worktree. Nobody edited it, and that is what it used to say.

    The round that added a branch for a directory left `not path.exists()` falling into the
    edited-since arm, so the refusal named an edit that did not happen (CHG-20260901-01, defect).
    """
    record = tmp_path / "in-flight.json"
    record.write_text(json.dumps(
        {"path": str(tmp_path / "gone.py"), "original": "a", "mutated": "b", "owner": 999999}),
        encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert said.startswith("REFUSING"), said
    assert "does not exist" in said, f"the diagnosis has to be the real one: {said!r}"
    assert "edited it since" not in said, f"nobody edited a file that is gone: {said!r}"
    assert record.exists()


def test_recover_refuses_a_file_it_cannot_decode(tmp_path, monkeypatch):
    """`recover` is called unguarded from `main()` and from the signal handler, so a raise here
    leaves the operator with a traceback at the moment a killed run needs putting back."""
    victim = tmp_path / "target.py"
    victim.write_bytes(b"MUTATED " + bytes([0xFF, 0xFE]) + b" SOURCE")
    record = tmp_path / "in-flight.json"
    record.write_text(json.dumps(
        {"path": str(victim), "original": "a", "mutated": "b", "owner": 999999}),
        encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert said.startswith("REFUSING"), said
    assert "UTF-8" in said, said
    assert record.exists() and victim.read_bytes().startswith(b"MUTATED ")


def test_recover_reads_four_fields_and_ignores_the_rest(tmp_path, monkeypatch):
    """A gate that iterated every key present refused a record carrying a spare one.

    Recovery was then unreachable until the operator guessed which field the tool did not read was
    the problem — on a record whose `path`, `original`, `mutated` and `owner` were all good
    (CHG-20260901-01, risk seat).
    """
    victim = tmp_path / "target.py"
    victim.write_text("MUTATED SOURCE" + NEWLINE, encoding="utf-8")
    record = tmp_path / "in-flight.json"
    record.write_text(json.dumps(
        {"path": str(victim), "original": "ORIGINAL SOURCE" + NEWLINE,
         "mutated": "MUTATED SOURCE" + NEWLINE, "owner": 999999,
         "note": 3, "started": ["not", "a", "string"]}), encoding="utf-8")
    monkeypatch.setattr(mutation_recovery, "IN_FLIGHT", record)

    said = mutation_recovery.recover(quiet=True)

    assert said and said.startswith("restored"), said
    assert victim.read_text(encoding="utf-8") == "ORIGINAL SOURCE" + NEWLINE
