"""The mutation runner had a guard for a stale anchor and none for an ambiguous one
(CHG-20260828-01).

`run()` refuses a mutation whose `before` text is **gone**, with a message saying why in the right
words: *"the mutation is stale, which is not the same as caught."* The symmetric case was missing.
The write is `original.replace(before, after, 1)`, so an anchor appearing **twice** reverts
whichever comes first — which need not be the guarantee `says` names. The run then reports about a
different line, and `CAUGHT` is the dangerous reading: it looks exactly like coverage.

This mattered twice in one day. Writing CHG-20260827-22, `if name not in workstreams:` matched both
the `node_workstream` guard and the `interfaces` guard; writing CHG-20260827-20,
`interfaces=plan.get(...)` matched both `cmd_run` and `cmd_serve` — and mutating the console path
would have left the tested path working while the run printed `CAUGHT`.

Both were caught by a uniqueness check in a throwaway generator script. **A guard that lives only in
the thing that produces the input is a guard the next author does not have**, which is why it is in
the tool now, and why this file exists — the tool had no tests at all.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import mutation_check  # noqa: E402


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


GREEN = {"tests/fake.py": True}


def test_an_anchor_appearing_twice_is_refused(source, capsys):
    """The defect. Without this, the run mutates the first occurrence and reports on that."""
    p = source("if guard_one:\n    pass\nif guard_one:\n    pass\n")
    assert mutation_check.run(_mutation(p, "if guard_one:"), GREEN) is False
    said = capsys.readouterr().out
    assert "AMBIGUOUS" in said
    assert "2 times" in said, "the count is what tells an author how bad the ambiguity is"


def test_the_refusal_says_how_to_fix_it(source, capsys):
    """A refusal that does not say what to do is a refusal an author works around."""
    p = source("x = 1\nx = 1\n")
    mutation_check.run(_mutation(p, "x = 1"), GREEN)
    said = capsys.readouterr().out
    assert "surrounding context" in said


def test_an_ambiguous_anchor_leaves_the_file_untouched(source):
    """Refusing before writing, not after. A tool that mutates and then complains has already put
    the tree in a state its own `finally` is responsible for undoing."""
    text = "if guard_one:\n    pass\nif guard_one:\n    pass\n"
    p = source(text)
    mutation_check.run(_mutation(p, "if guard_one:"), GREEN)
    assert p.read_text(encoding="utf-8") == text


def test_a_unique_anchor_is_not_refused_as_ambiguous(source, capsys):
    """The check must not fire on the normal case — it would refuse every real mutation.

    The run itself fails here because `tests/fake.py` does not exist, which is fine: what this
    asserts is that it got **past** the anchor checks to try.
    """
    p = source("if guard_one:\n    pass\nif guard_two:\n    pass\n")
    mutation_check.run(_mutation(p, "if guard_one:"), GREEN)
    said = capsys.readouterr().out
    assert "AMBIGUOUS" not in said
    assert "ANCHOR GONE" not in said


def test_a_missing_anchor_is_still_refused_as_stale(source, capsys):
    """The guard that already existed, kept working by the one added beside it."""
    p = source("nothing to see\n")
    assert mutation_check.run(_mutation(p, "if guard_one:"), GREEN) is False
    said = capsys.readouterr().out
    assert "ANCHOR GONE" in said
    assert "not the same as caught" in said


def test_stale_and_ambiguous_are_different_messages(source, capsys):
    """They are different defects and an author fixes them differently: one is deleted code, the
    other is an anchor that needs narrowing."""
    mutation_check.run(_mutation(source("nothing\n"), "missing"), GREEN)
    gone = capsys.readouterr().out
    mutation_check.run(_mutation(source("dup\ndup\n"), "dup"), GREEN)
    ambiguous = capsys.readouterr().out
    assert gone != ambiguous
    assert "ANCHOR GONE" in gone and "AMBIGUOUS" not in gone
    assert "AMBIGUOUS" in ambiguous and "ANCHOR GONE" not in ambiguous


def test_a_red_baseline_still_beats_both_checks(source, capsys):
    """Order matters: `NO BASELINE` is checked first, because a red file makes every other verdict
    meaningless. Pinning it so a later edit cannot reorder them silently."""
    p = source("dup\ndup\n")
    assert mutation_check.run(_mutation(p, "dup"), {"tests/fake.py": False}) is False
    said = capsys.readouterr().out
    assert "NO BASELINE" in said
    assert "AMBIGUOUS" not in said


# ── the shipped mutations obey their own rule ───────────────────────────────────────────────────

def test_no_shipped_mutation_has_a_stale_anchor():
    """`ANCHOR GONE` is reported correctly — and only to whoever runs that group (CHG-20260828-02).

    A stale anchor pins nothing, and the suite said nothing about it, so a guarantee could go
    unpinned for as long as nobody ran `--only <that group>`. Two were stale when this was written:

    * `examples/a --seat-model command…` — CHG-20260827-23 added `risk` and `can_write` to the
      `_Process` call it anchored on;
    * `planning/the declared interfaces never reach the run` — CHG-20260827-20 inserted
      `change_class=` between its two lines, **the same day the mutation was written**.

    Neither author did anything careless. That is the point, and it is the same argument as the
    ambiguity check beside this one: anchors rot because other changes move, so the rot has to be
    checked rather than remembered.
    """
    stale = []
    for m in mutation_check.MUTATIONS:
        if not m.path.is_file():
            stale.append(f"{m.group}/{m.says}: {m.path.name} does not exist")
        elif m.before not in m.path.read_text(encoding="utf-8"):
            stale.append(f"{m.group}/{m.says}: not found in {m.path.name}")
    assert not stale, (
        "these mutations no longer match the code they name, so they pin nothing. Re-anchor each "
        f"one, or delete it if the guarantee is gone: {stale}")


def test_every_shipped_mutation_has_a_unique_anchor():
    """The check applied to the real list, so an ambiguous anchor cannot be committed and then
    discovered later by a run that reported `CAUGHT` about the wrong line."""
    ambiguous = []
    for m in mutation_check.MUTATIONS:
        if not m.path.is_file():
            continue                    # `ANCHOR GONE` is a different finding and reports itself
        found = m.path.read_text(encoding="utf-8").count(m.before)
        if found > 1:
            ambiguous.append(f"{m.group}/{m.says}: {found} matches in {m.path.name}")
    assert not ambiguous, (
        "these mutations would revert whichever occurrence comes first rather than the one they "
        f"name: {ambiguous}")
