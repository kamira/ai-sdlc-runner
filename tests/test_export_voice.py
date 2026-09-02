"""The export filed a person's pre-authorisation under the machine's voice (CHG-20260828-03).

`RELAXATION` carries two different acts:

* `--store-remote allow` — the runner recording its own configuration;
* a change class — **a person** pre-authorising a type of change (CHG-20260827-20).

`_VOICES` mapped the *kind*, so both rendered as `runner relaxed`. The HTML export of a run
declaring `standard:alex@example.com:2026-12-31` produced:

    <article class="turn runner"><span class="who">runner</span><span class="verb">relaxed</span>

The summary text names the person, so nothing was lost — but the **voice column**, which is the
thing an export exists to make scannable, said the machine did it.

This repository's first claim is that governance is a person's judgement and never a model's. A
document that attributes an operator's judgement to the runner is wrong in the one dimension it
exists to keep straight, and it is wrong in the direction that flatters the machine.

## The rule

A turn naming `by` was done by that person. Everything else keeps the voice its kind implies, so no
existing turn changes meaning and no stored conversation is reinterpreted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import conversations as conv  # noqa: E402


# ── the resolver ────────────────────────────────────────────────────────────────────────────────

def test_a_relaxation_naming_a_person_is_the_operators():
    assert conv._voice_of({"kind": conv.RELAXATION, "text": "x", "by": "alex"}) == (
        "operator", "relaxed")


def test_a_relaxation_naming_nobody_is_still_the_runners():
    """`--store-remote allow` is the runner recording its own configuration, and stays that way.

    This is why the fix reads the turn rather than renaming the kind: one of the two acts really is
    the runner's, and calling both `operator` would be the same error pointing the other way.
    """
    assert conv._voice_of({"kind": conv.RELAXATION, "text": "--store-remote allow"}) == (
        "runner", "relaxed")


def test_an_empty_by_does_not_promote_the_voice():
    """A blank name is not a person. Attributing a turn to an operator nobody can name is worse
    than leaving it with the runner — it looks like accountability and carries none."""
    assert conv._voice_of({"kind": conv.RELAXATION, "text": "x", "by": ""})[0] == "runner"


@pytest.mark.parametrize("kind,who", [
    (conv.ASK, "runner"), (conv.ANSWER, "model"), (conv.INSTRUCTION, "operator"),
    (conv.DECISION, "operator"), (conv.NOTE, "runner"),
])
def test_every_other_kind_keeps_the_voice_it_had(kind, who):
    """`by` is only consulted for relaxations, so nothing else is reinterpreted."""
    assert conv._voice_of({"kind": kind})[0] == who
    assert conv._voice_of({"kind": kind, "by": "alex"})[0] == who


def test_an_unknown_kind_still_falls_back_to_the_runner():
    assert conv._voice_of({"kind": "invented"}) == ("runner", "invented")


# ── the writer ──────────────────────────────────────────────────────────────────────────────────

def test_the_turn_carries_by_only_when_given(tmp_path):
    """An absent `by` writes no key, so a stored conversation is byte-identical to one written
    before this change — the property that makes the fix safe to apply to an existing store."""
    store = conv.FileBackend(tmp_path / "conversations")
    c = conv.Conversation(store, "P").open()
    c.relaxation("--store-remote allow")
    c.relaxation("change class declared", by="alex@example.com")
    turns = [t for t in store.read(c.project["id"], c.id)["turns"]
             if t.get("kind") == conv.RELAXATION]
    assert "by" not in turns[0]
    assert turns[1]["by"] == "alex@example.com"


# ── end to end, through the real CLI ────────────────────────────────────────────────────────────

def test_a_declared_class_is_exported_as_the_operators_act(tmp_path):
    """The whole point, observed from outside: the run, the store, and the rendered document.

    Asserting on the rendered `who` rather than on `_voice_of` is deliberate. The defect was not in
    the mapping — it was that two renderers both read the kind directly, and a test of the resolver
    alone would have passed against the broken code.
    """
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}

    def run(argv):
        return subprocess.run([sys.executable, "-m", "ai_sdlc_runner.cli"] + argv,
                              cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=900)

    done = run(["--config", str(root / "examples/minimal/runner.yaml"),
                "run", "--plan", str(root / "examples/minimal/plan.json"), "--risk", "low",
                "--project", "voice", "--store-root", str(tmp_path),
                "--change-class", "standard:alex@example.com:2026-12-31"])
    assert "state:         finished" in (done.stdout or ""), (done.stdout or "")[-600:]

    listed = run(["conversations", "--project", "voice", "--store-root", str(tmp_path)])
    cid = (listed.stdout or "").strip().splitlines()[-1].split()[0]

    page = run(["export", "--project", "voice", "--store-root", str(tmp_path),
                "--conversation", cid, "--format", "html"]).stdout or ""
    relaxations = [line for line in page.split("<article") if 'class="verb">relaxed' in line]
    assert relaxations, "the export carries no relaxation at all, so nothing below is meaningful"

    # **The class's relaxation**, not every relaxation. `conversations.relaxation`'s own docstring
    # draws the line this assertion used to cross: *"Two different acts share this kind:
    # `--store-remote allow` is the runner recording its own configuration, and a change class is a
    # person pre-authorising a type. The first is the runner's voice; the second is not."*
    #
    # It asserted `all(...)` and so said every relaxation is a person's. CHG-20260903-23 added one
    # that is not — an unsandboxed run, which is the runner recording what this machine could do —
    # and this turned red on a correct change. The test is named for the class's act; it now checks
    # the class's act (CHG-20260903-23).
    declared = [line for line in relaxations if "alex@example.com" in line]
    assert declared, f"the class's own relaxation is not in the export: {[l[:120] for l in relaxations]}"
    assert all('class="who">operator' in line for line in declared), (
        "the export attributes a person's pre-authorisation to the runner: "
        f"{[l[:120] for l in declared]}")
    assert "alex@example.com" in page, "and it must still name who"

    # And the runner's own relaxations stay the runner's, or the distinction above is decoration.
    machine = [line for line in relaxations if "alex@example.com" not in line]
    assert all('class="who">runner' in line for line in machine), (
        f"a relaxation the runner recorded about itself is attributed to a person: "
        f"{[l[:120] for l in machine]}")


def test_no_renderer_reads_the_voice_table_directly():
    """The defect was two call sites reading `_VOICES`, not a wrong entry in it.

    A third export format added later could reintroduce it exactly, and the mutation on `_voice_of`
    would not notice — it only proves the resolver works for whoever calls it. So this asserts the
    structural property instead: **`_VOICES` is read in one place.**

    Done over the syntax tree rather than by searching the text, for the reason
    `test_nothing_is_unwired` gives: a docstring mentioning `_VOICES` is a string, and a comment is
    not code, and neither should count as a use.
    """
    import ast

    source = (Path(__file__).resolve().parents[1] / "src" / "ai_sdlc_runner" /
              "conversations.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    readers = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id == "_VOICES":
                readers.add(node.name)

    assert readers == {"_voice_of"}, (
        f"_VOICES is read by {sorted(readers)}. Every renderer must go through `_voice_of`, or a "
        f"turn's voice depends on which format you exported — which is the defect CHG-20260828-03 "
        f"fixed, reintroduced one function along.")
