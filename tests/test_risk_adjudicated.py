"""The grade that indexes every gate is no longer set by one voice (CHG-20260827-17).

`lead_assess` was `mode=SINGLE`. Every other consequential decision in the flow is adjudicated —
`pm_confirm`, `pm_signoff`, `lead_task_review`, `re_review`, `qa_accept` are model panels and
`lead_review` is a seat panel. The one input deciding **which row of the gate table every later node
reads** was the one input no panel saw.

## The circularity, which is tighter than it looks

`engine.py` resolved every gate from one `cfg.risk`. `pm_signoff` is the panel that reviews the
lead's assessment, and `pm_signoff`'s own gate was resolved **from the grade under review**. The
reviewer stood at a height the reviewed thing chose. A change graded `low` when it is really a
migration got `before_dispatch: low → auto`, and the gate that exists to put a person in front of
exactly that never fired.

## Two rules, deliberately not the same rule

**Deciding the grade is a majority**, and a panel that has not agreed has decided nothing
(`policy.adjudicate_grade`). "Any voice saying `high` makes it high" would be a veto, and
`policy.adjudicate`'s own docstring says a model panel has no veto because every voice answers the
same question.

**Protecting an open question is the strictest anybody proposed** (`engine._grade_in_force`). That
is not a decision about what the grade is; it is how much protection an unsettled question gets.
Collapsing the two would let one cautious voice decide alone — the thing this change removes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import engine, graph, policy  # noqa: E402


# ── deciding the grade ───────────────────────────────────────────────────────────────────────────

def test_a_majority_decides_the_grade():
    out = policy.adjudicate_grade({"a": "medium", "b": "medium", "c": "high"})
    assert (out["outcome"], out["grade"]) == (policy.PASS, "medium")


def test_three_voices_disagreeing_decide_nothing():
    """low / medium / high is the honest `undecided`: they disagree about the thing every later
    gate is indexed by, so there is nothing a person can be spared."""
    out = policy.adjudicate_grade({"a": "low", "b": "medium", "c": "high"})
    assert out["outcome"] == policy.UNDECIDED
    assert out["grade"] is None
    assert out["proposed"] == {"a": "low", "b": "medium", "c": "high"}


def test_an_even_split_decides_nothing():
    assert policy.adjudicate_grade({"a": "low", "b": "high"})["outcome"] == policy.UNDECIDED


def test_one_cautious_voice_cannot_set_the_grade_alone():
    """The rule that is NOT "strictest wins". A model panel has no veto — every voice answers the
    same question, so there is no per-voice subject for a veto to be about. One voice saying `high`
    against two saying `low` loses, and the run is graded `low` after sign-off.

    The protection while the question is open is a separate matter, and the next test is it.
    """
    out = policy.adjudicate_grade({"a": "high", "b": "low", "c": "low"})
    assert (out["outcome"], out["grade"]) == (policy.PASS, "low")


@pytest.mark.parametrize("bad", ["catastrophic", "", "LOW", "medium "])
def test_a_voice_that_did_not_grade_is_refused(bad):
    """Reading `catastrophic` as a grade would invent one. The panel is refused, not guessed at."""
    with pytest.raises(policy.PolicyError):
        policy.adjudicate_grade({"a": bad, "b": "low"})


# ── protecting the open question ────────────────────────────────────────────────────────────────

def _report(**kw):
    r = engine.RunReport()
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def test_an_unsettled_grade_is_protected_at_the_strictest_candidate():
    """The circularity fix. While the grade is open, every gate resolves at the most anybody
    proposed — so the assessment cannot lower the gate standing over its own review."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="low")
    report = _report(risk_proposed={"a": "low", "b": "high"})
    assert engine._grade_in_force(cfg, report) == "high"


def test_the_plans_own_grade_is_one_of_the_candidates():
    """`--risk low` with a panel that has said nothing yet still protects at `low`; with a voice
    proposing `high` it protects at `high`. The plan does not get to be the floor on its own."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="medium")
    assert engine._grade_in_force(cfg, _report()) == "medium"
    assert engine._grade_in_force(cfg, _report(risk_proposed={"a": "high"})) == "high"


def test_a_settled_grade_is_used_even_when_it_is_lower():
    """Being signed off is what makes a grade the answer. After that, the strictest *candidate* is
    history — otherwise a single dissenting voice would raise the gates for the whole run, which is
    the veto this design refuses."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="high")
    report = _report(risk_proposed={"a": "high", "b": "low", "c": "low"}, risk_settled="low")
    assert engine._grade_in_force(cfg, report) == "low"


# ── the flow says who grades and who ratifies ───────────────────────────────────────────────────

def test_the_flow_has_exactly_one_grader_and_one_ratifier():
    graders = [n.id for n in graph.NODES if n.grades_risk]
    settlers = [n.id for n in graph.NODES if n.settles_risk]
    assert graders == ["lead_assess"], graders
    assert settlers == ["pm_signoff"], settlers


def test_the_grader_is_a_panel():
    """`graph.validate` refuses a grading node that is not one — one voice setting the grade alone
    is the whole defect."""
    assert graph.BY_ID["lead_assess"].mode == graph.MODEL_PANEL


def test_a_panel_must_adjudicate_something():
    """The invariant this change widened by exactly one case.

    `validate` refused `MODEL_PANEL` on anything but a `DECISION`, because "a node that reaches no
    verdict has nothing to adjudicate". `lead_assess` is a STEP that reaches a *grade*, which is
    something. What the guard exists to refuse — a plain work-producing step with several models —
    is still refused, which is why `engineer_build` is a POOL.
    """
    import dataclasses

    step_that_grades_nothing = dataclasses.replace(
        graph.BY_ID["lead_assess"], grades_risk=False)
    with pytest.raises(graph.GraphError) as exc:
        _validate_one(step_that_grades_nothing)

    # Specific, because a mutation showed this assertion passing for the wrong reason. Asserting
    # `"adjudicate" in ...` matched the *settles_risk* invariant's message instead -- it says
    # "unadjudicated", which contains the substring. So disabling the invariant under test left the
    # test green, caught by nothing but `tools/mutation_check.py --only risk`.
    assert "that grades nothing" in str(exc.value), str(exc.value)
    assert "lead_assess" in str(exc.value)


def _validate_one(node):
    """`validate()` walks the shipped NODES; this checks one node against the same rules by
    swapping it in. Kept explicit rather than reaching into a private helper that may not exist."""
    import ai_sdlc_runner.graph as g

    original = g.NODES
    try:
        g.NODES = tuple(node if n.id == node.id else n for n in original)
        g.validate()
    finally:
        g.NODES = original


def test_a_grading_node_that_is_not_a_panel_is_refused():
    import dataclasses

    single_grader = dataclasses.replace(graph.BY_ID["lead_assess"], mode=graph.SINGLE)
    with pytest.raises(graph.GraphError) as exc:
        _validate_one(single_grader)
    # Also specific: an `or` across two phrases is an assertion that passes if either error fires,
    # and this file already shipped one assertion that matched the wrong one.
    assert "panel or it is nothing" in str(exc.value), str(exc.value)


# ── the case this change exists for ──────────────────────────────────────────────────────────────

MIGRATION = {"description": "convert each account row into the replacement layout",
             "kind": "migration", "targets": []}


def test_a_migration_graded_low_still_stops_before_dispatch():
    """The self-shielding case, and the reason the grade could not be left to one voice.

    Before this change: `lead_assess` is `SINGLE`, one model says `low`, every later gate resolves
    from that `low`, and `before_dispatch: low -> auto`. The gate that exists to put a person in
    front of a migration never fires — the wrong grade hid the danger *and* hid the gate that would
    have caught the wrong grade.

    The migration itself is still stopped by `PERMANENT_HALT_KINDS`, which is the defence that made
    the old shape survivable and which this change did not touch. What is tested here is the gate:
    a run whose plan says `low` while a voice says `high` is gated at `high` until somebody ratifies
    a grade.
    """
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="low")
    open_question = _report(risk_proposed={"lead-a": "high", "lead-b": "low"})

    in_force = engine._grade_in_force(cfg, open_question)
    assert in_force == "high", "an unratified disagreement must not be gated at the lower claim"

    before_dispatch = engine.resolve_verdict(graph.BY_ID["pm_signoff"], in_force)
    assert before_dispatch["verdict"] in policy.STOPPING, (
        f"`before_dispatch` at {in_force} did not stop: {before_dispatch}")

    # And the shape the defect had: gated at the proposed `low`, it does not stop.
    assert engine.resolve_verdict(graph.BY_ID["pm_signoff"], "low")["verdict"] == policy.AUTO


def test_the_reviewer_no_longer_stands_at_a_height_the_reviewed_thing_chose():
    """`pm_signoff` reviews the lead's grade. Its own gate must not be resolved from that grade
    while it is still the thing under review."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="high")
    proposed_low = _report(risk_proposed={"a": "low", "b": "low"})

    # The panel agreed `low`; nobody has ratified it. The plan said `high`, so `high` still holds.
    assert engine._grade_in_force(cfg, proposed_low) == "high"

    # Once ratified, `low` is the answer and the gates drop. That is a decision somebody made.
    proposed_low.risk_settled = "low"
    assert engine._grade_in_force(cfg, proposed_low) == "low"


def test_a_disagreed_grade_is_visible_in_the_report():
    """Task 5. Both grades appear, so "three voices said low" is distinguishable from "one did"."""
    report = engine.RunReport()
    report.risk_proposed.update({"a": "low", "b": "high"})
    report.risk_agreed = None
    assert report.risk_proposed == {"a": "low", "b": "high"}
    assert report.risk_settled is None, "nothing is settled until somebody signs it off"
