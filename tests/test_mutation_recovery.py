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
    """
    assert not mutation_recovery.IN_FLIGHT.exists(), (
        f"{mutation_recovery.IN_FLIGHT} exists, so a mutation run was killed and a source file may "
        f"still be mutated. Run `python3 tools/mutation_check.py` to put it back, or read that "
        f"file and restore it by hand.")
