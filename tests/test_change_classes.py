"""`merge = confirm` on every change makes throughput a function of one person's availability
(CHG-20260827-20).

That reasoning is correct — merging is a one-way door — and at a mid-to-large scale a policy that
stops every change is not a strict policy, it is a policy that gets bypassed. This repository
already documented that failure once, about the red-line word list.

## This is the only change here that can make a gate stop LESS often

So every test below is about a guard rather than a feature. The record lists five, and the ones that
carry the weight are:

* a class is declared by a **person**, never inferred and never by a model;
* the six permanent halts are never available to any class, at any grade;
* a class **expires**, because a type does not stay safe merely because it was safe once.

## The rule the record left open, decided here

*What may a class relax?* **`confirm` → `auto`, and nothing else.**

`confirm` means *a person is asked and may say yes*, and pre-authorising a type is exactly saying
yes in advance about every instance of it. `halt` and `halt_independent` say something stronger:
stop, and put this in front of somebody. A pre-authorisation is a person's **approval**; it is not
a person's **attention**, and dissolving a halt would trade the second for the first without
anybody noticing.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import cli, engine, graph, plan, policy  # noqa: E402

SIGNED = {"class": "standard", "authorised_by": "alex@example.com", "review_by": "2026-12-31"}
TODAY = "2026-08-28"


# ── the classes are data ────────────────────────────────────────────────────────────────────────

def test_there_are_three_classes_and_normal_is_one_of_them():
    """`normal` is not a new state: it is what every change already was, named."""
    assert [c.name for c in policy.CLASSES] == ["standard", "normal", "emergency"]
    assert policy.DEFAULT_CLASS == "normal"
    assert policy.BY_CLASS["normal"].relaxes is False


def test_only_emergency_is_reviewed_afterwards():
    """What separates emergency from standard is *when* a person looks, not how loud it is."""
    assert policy.BY_CLASS["emergency"].reviewed_after is True
    assert policy.BY_CLASS["standard"].reviewed_after is False
    assert policy.BY_CLASS["normal"].reviewed_after is False


def test_an_unknown_class_is_refused_by_name():
    with pytest.raises(policy.PolicyError) as exc:
        policy.relax(policy.CONFIRM, "pre-approved")
    assert "pre-approved" in str(exc.value)


# ── what a class may and may not relax ──────────────────────────────────────────────────────────

def test_a_class_turns_confirm_into_auto():
    """The whole point: a question somebody already answered is not asked again."""
    assert policy.relax(policy.CONFIRM, "standard")[0] == policy.AUTO
    assert policy.relax(policy.CONFIRM, "emergency")[0] == policy.AUTO


@pytest.mark.parametrize("stopping", [policy.HALT, policy.HALT_INDEPENDENT])
@pytest.mark.parametrize("klass", ["standard", "emergency"])
def test_no_class_dissolves_a_halt(stopping, klass):
    """A pre-authorisation is a person's approval; a halt asks for a person's attention.

    If this ever passes `auto`, a class has quietly turned "somebody must look at this" into
    "somebody once said this kind of thing is fine".
    """
    verdict, why = policy.relax(stopping, klass)
    assert verdict == stopping
    assert "not relax" in why, "a refusal nobody can see is a refusal that may as well not exist"


def test_normal_changes_nothing_at_all():
    for graded in (policy.AUTO, policy.CONFIRM, policy.HALT, policy.HALT_INDEPENDENT):
        assert policy.relax(graded, "normal") == (graded, "")
        assert policy.relax(graded, None) == (graded, "")


def test_merge_relaxes_at_low_and_still_halts_at_high():
    """The gate the record is actually about, at both ends.

    `low` is the case it exists for. `high` is the case that must survive it: `merge` at high is a
    halt, and a class pre-authorising the type does not make a high-risk merge unattended.
    """
    assert policy.verdict("merge", "low", change_class="standard")["verdict"] == policy.AUTO
    assert policy.verdict("merge", "high", change_class="standard")["verdict"] == policy.HALT


def test_the_verdict_says_the_class_relaxed_it():
    said = policy.verdict("merge", "low", change_class="standard")["source"]
    assert "standard" in said and "relaxed" in said


def test_a_class_cannot_undo_a_tightening_the_change_asked_for_itself():
    """`autonomy` is about THIS instance; a class is about the TYPE, and the instance is more
    specific. A change that declared itself dangerous is not overruled by a standing decision about
    its kind."""
    tightened = policy.verdict("self_verify", "low", autonomy=policy.HALT,
                               change_class="standard")
    assert tightened["verdict"] == policy.HALT


def test_the_verdict_shape_stays_closed():
    """`workorder.render` refuses fields outside the contract, and the first draft of this change
    added two — in the function whose own comment says why not to."""
    keys = set(policy.verdict("merge", "low", change_class="standard"))
    assert keys == set(policy.verdict("merge", "low"))


# ── the declaration, and who signed it ──────────────────────────────────────────────────────────

def test_a_class_in_force_names_the_class_and_the_person():
    name, why = policy.class_in_force(SIGNED, TODAY)
    assert name == "standard"
    assert "alex@example.com" in why and "2026-12-31" in why


def test_nothing_declared_is_normal_and_says_so():
    name, why = policy.class_in_force(None, TODAY)
    assert name == policy.DEFAULT_CLASS
    assert why, "a run with no class and a run that relaxed one must not read the same"


def test_a_class_nobody_signed_is_refused():
    """A pre-authorisation on nobody's authority is the thing this class exists to avoid."""
    with pytest.raises(policy.PolicyError) as exc:
        policy.class_in_force({"class": "standard", "review_by": "2026-12-31"}, TODAY)
    assert "authorised" in str(exc.value)


def test_a_class_with_no_review_date_is_refused():
    with pytest.raises(policy.PolicyError) as exc:
        policy.class_in_force({"class": "standard", "authorised_by": "alex"}, TODAY)
    assert "review date" in str(exc.value)


# ── expiry ──────────────────────────────────────────────────────────────────────────────────────

def test_a_class_past_its_review_date_expires_to_normal():
    """Task 5. A type does not stay safe because it was safe, and the expiry is the floor under
    that — the record says plainly it is not a fix for it."""
    name, why = policy.class_in_force(dict(SIGNED, review_by="2026-08-01"), TODAY)
    assert name == policy.DEFAULT_CLASS
    assert "expired" in why and "2026-08-01" in why


def test_a_class_expires_the_day_after_its_review_date_not_on_it():
    """The review date is the last day it holds, which is what "due for review on" means to the
    person who wrote it."""
    assert policy.class_in_force(dict(SIGNED, review_by=TODAY), TODAY)[0] == "standard"
    assert policy.class_in_force(dict(SIGNED, review_by="2026-08-27"), TODAY)[0] == "normal"


# ── nothing may class itself ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["change_class", "class", "pre_authorised"])
def test_a_plan_cannot_declare_its_own_class(tmp_path, key):
    """Task 2, and the guard that matters most.

    A plan is written by the PM — a model. A plan that could class itself would be a model granting
    itself an exemption from the gate that exists to put a person in front of it.
    """
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({key: "standard"}), encoding="utf-8")
    with pytest.raises(plan.PlanError) as exc:
        plan.load(p)
    assert "only a person may declare one" in str(exc.value)
    assert "autonomy" in str(exc.value), "the refusal should point at the thing that IS allowed"


def test_a_plan_may_still_tighten_itself(tmp_path):
    """The mirror image, and the reason the refusal above is about direction rather than about
    plans: tightening costs nothing when it is wrong."""
    p = tmp_path / "plan.json"
    p.write_text(json.dumps({"autonomy": "halt"}), encoding="utf-8")
    assert plan.load(p)["autonomy"] == "halt"


@pytest.mark.parametrize("raw", ["standard", "standard:alex", "standard::2026-12-31",
                                 "standard:alex:", ":alex:2026-12-31"])
def test_the_flag_refuses_a_declaration_missing_any_part(raw):
    """All three parts or none. A mistyped `--rule` changes one branch; a mistyped class relaxes a
    gate for a whole run."""
    with pytest.raises(SystemExit):
        cli._change_class(raw)


def test_the_flag_refuses_an_unknown_class_rather_than_guessing():
    with pytest.raises(SystemExit) as exc:
        cli._change_class("pre-approved:alex:2026-12-31")
    assert "pre-approved" in str(exc.value)


def test_the_flag_parses_all_three_parts():
    assert cli._change_class("standard:alex@example.com:2026-12-31") == SIGNED


def test_no_declaration_is_not_an_error():
    assert cli._change_class(None) is None


# ── the permanent halts are untouchable ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(policy.PERMANENT_HALT_KINDS))
@pytest.mark.parametrize("klass", ["standard", "emergency"])
def test_a_permanent_halt_ignores_the_class_entirely(kind, klass):
    """Task 3. These are not gates and no class reaches them — checked for **every** kind, because
    a guard that holds for `deploy` and not for `money` is not a guard."""
    cfg = engine.RunConfig(
        node_specs={}, decisions={}, risk="low", undeclared="refuse",
        change_class={"class": klass, "authorised_by": "alex", "review_by": "2026-12-31"},
        today=TODAY,
        operations={"pm_plan": [{"description": "do the thing", "kind": kind,
                                 "targets": ["somewhere"]}]})
    tripped = engine._permanent_halt(graph.BY_ID["pm_plan"], cfg, engine.RunReport())
    assert tripped is not None, f"a {kind!r} operation passed under the {klass!r} class"


def test_the_halt_says_a_class_does_not_relax_it_either():
    """The message enumerates what cannot relax a permanent halt. A class is now a member of that
    family, and a list that stops being complete is how a reader learns the wrong rule."""
    cfg = engine.RunConfig(
        node_specs={}, decisions={}, risk="low", undeclared="refuse",
        operations={"pm_plan": [{"description": "ship it", "kind": "deploy",
                                 "targets": ["kubectl apply -f prod/"]}]})
    tripped = engine._permanent_halt(graph.BY_ID["pm_plan"], cfg, engine.RunReport())
    assert "change class" in str(tripped)


# ── end to end, through the real CLI ────────────────────────────────────────────────────────────

def _run(tmp_path, name, extra, operations=None):
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "examples/minimal/plan.json").read_text(encoding="utf-8"))
    payload["risk"] = "low"
    if operations:
        payload["operations"].update(operations)
    where = tmp_path / name
    where.mkdir()
    (where / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(root / "examples/minimal/runner.yaml"),
         "run", "--plan", str(where / "plan.json"), "--risk", "low",
         "--ask-journal", str(where / "asks")] + list(extra),
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=900)
    return (proc.stdout or "") + (proc.stderr or "")


def test_without_a_class_the_run_still_stops_at_merge(tmp_path):
    """The control, and the rollback story: with nothing declared, behaviour is exactly today's."""
    out = _run(tmp_path, "plain", [])
    assert "stopped at:    merge" in out, out[-800:]
    assert "change class:  nothing was declared" in out


def test_a_declared_class_carries_the_run_through_merge(tmp_path):
    """The feature, against that control — the only difference is the flag."""
    out = _run(tmp_path, "classed",
               ["--change-class", "standard:alex@example.com:2026-12-31"])
    assert "state:         finished" in out, out[-800:]
    assert "alex@example.com" in out, "the run must record on whose authority it did not stop"
    assert "would have been 'confirm'" in out, (
        "a relaxation that cannot be enumerated afterwards cannot be audited")


def test_an_expired_class_stops_the_run_and_says_why(tmp_path):
    out = _run(tmp_path, "expired", ["--change-class", "standard:alex@example.com:2026-08-01"])
    assert "stopped at:    merge" in out, out[-800:]
    assert "expired" in out and "2026-08-01" in out


def test_a_deploy_under_a_standard_class_still_halts(tmp_path):
    """Task 3 through the real command, not only at the function.

    The class demonstrably works — the test above finishes a run with it — so this failing would
    mean a pre-authorisation had reached the six actions that no configuration relaxes.
    """
    out = _run(tmp_path, "deploy",
               ["--change-class", "standard:alex@example.com:2026-12-31"],
               operations={"pm_plan": [{"description": "ship it", "kind": "deploy",
                                        "targets": ["kubectl apply -f prod/"]}]})
    assert "permanent halt" in out, out[-800:]
    assert "state:         stopped" in out
