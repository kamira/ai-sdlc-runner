"""Tasks 2 and 20 — a tie decides nothing, and a model panel is not a seat panel.

Both tasks land together because both are `policy.adjudicate`, and splitting them would have meant
rewriting the same function twice with the second rewrite unable to see the first.

## Why the engine test matters more than the policy test

Three review rounds all found the same thing, and it was never in `policy.py`:

    return "pass" if outcome["outcome"] == "pass" else "fail"          # engine.py, before task 2

Adding `undecided` to the policy and stopping there would have left the engine flattening it back to
`fail` — the run sends the work back, the tests go green, and the change is a no-op that *looks*
done. Two independent seats found it separately, in round 1. So the tests below that matter most are
the ones asserting the **engine** does not collapse, not the ones asserting the policy returns a new
string.

## Why no model voice vetoes

A veto belongs to the conformance seat because that seat owns a subject — "is this the thing that was
asked for" is a matter of fact, and counting votes on a fact is how a panel talks itself out of one.
A model panel has no per-voice subject: every voice answers the *same* question. There is nothing for
a veto to be about, and handing one model a veto would be granting it authority for being itself —
the ranking nobody wrote down that this design refuses everywhere else.
"""
import inspect

import pytest

from ai_sdlc_runner import engine, graph, policy


# --- the policy: three outcomes, and a tie is the third ------------------------------------------

def test_the_three_outcomes_are_named():
    assert policy.OUTCOMES == (policy.PASS, policy.FAIL, policy.UNDECIDED)


def test_an_even_split_of_seats_is_undecided():
    out = policy.adjudicate({"conformance": "pass", "defect": "fail"})
    assert out["outcome"] == policy.UNDECIDED


def test_a_minority_pass_is_still_a_failure():
    # Undecided must not swallow the ordinary case. Two of four is a tie; one of four is a loss.
    out = policy.adjudicate(
        {"conformance": "pass", "defect": "fail", "risk": "fail", "idiom": "fail"})
    assert out["outcome"] == policy.FAIL


def test_a_majority_still_passes():
    out = policy.adjudicate({"conformance": "pass", "defect": "pass", "risk": "fail"})
    assert out["outcome"] == policy.PASS


def test_a_veto_beats_a_tie():
    # The veto is checked before the count, so a vetoed tie is a failure and not an undecided —
    # the conformance seat *did* decide, which is the whole point of it having a veto.
    out = policy.adjudicate({"conformance": "fail", "defect": "pass"})
    assert out["outcome"] == policy.FAIL
    assert out["vetoed"] == ["conformance"]


# --- task 20: a model panel adjudicates differently, and says so ---------------------------------

def test_model_voices_are_refused_by_the_seat_rule():
    """The finding that undercut the design's own justification.

    The record said any node could be a panel because it was "a generalisation of code that exists".
    It was not a generalisation — it was a `PolicyError`. This test pins the fact that made the
    claim false, so nobody restores the claim without tripping it.
    """
    with pytest.raises(policy.PolicyError, match="unknown seat"):
        policy.adjudicate({"opus": "pass", "codex": "fail"})


def test_a_model_panel_adjudicates_by_majority():
    out = policy.adjudicate({"opus": "pass", "codex": "pass", "gemini": "fail"}, voices="models")
    assert out["outcome"] == policy.PASS


def test_a_model_panel_ties_to_undecided():
    out = policy.adjudicate({"opus": "pass", "codex": "fail"}, voices="models")
    assert out["outcome"] == policy.UNDECIDED


def test_a_model_panel_can_fail():
    out = policy.adjudicate({"opus": "fail", "codex": "fail", "gemini": "pass"}, voices="models")
    assert out["outcome"] == policy.FAIL


def test_no_model_voice_vetoes():
    """A model sharing a seat's name must not inherit that seat's veto.

    `conformance` is the veto seat. As a *model* name it is just a string, and if the model panel
    reached into `BY_SEAT` it would hand one voice a veto for being called the right thing — a name
    constraining what happens without anybody deciding it should.
    """
    out = policy.adjudicate(
        {"conformance": "fail", "defect": "pass", "risk": "pass"}, voices="models")
    assert out["outcome"] == policy.PASS
    assert out["vetoed"] == []


def test_an_unknown_panel_kind_is_refused():
    with pytest.raises(policy.PolicyError, match="unknown panel kind"):
        policy.adjudicate({"opus": "pass"}, voices="committee")


def test_an_empty_model_panel_is_refused():
    with pytest.raises(policy.PolicyError, match="no verdicts"):
        policy.adjudicate({}, voices="models")


# --- the engine: the collapse is gone, and cannot come back --------------------------------------

def test_the_engine_no_longer_collapses_every_non_pass_to_fail():
    """The test that would have failed for every version of task 2 that went green and did nothing."""
    source = inspect.getsource(engine._adjudicate)
    assert '"pass" if outcome["outcome"] == "pass" else "fail"' not in source, (
        "the engine is flattening the policy's outcome again — this is the exact line three review "
        "rounds identified, and restoring it makes `undecided` unreachable while all tests pass")


def test_the_engine_refuses_an_outcome_it_cannot_route(monkeypatch):
    """An unrecognised outcome is not a failure, and must not be quietly treated as one.

    Driven rather than grepped: the policy is made to return something the engine has never heard
    of, and the engine must **raise** rather than pick a branch. This is the same lesson as
    `policy.recognise`'s third state — "I do not know what this is" and "this is safe" are different
    answers, and a system that maps the first onto the second has stopped examining anything.
    """
    node = graph.BY_ID["lead_review"]
    report = engine.RunReport()
    report.asks.append(
        engine.Ask(node_id=node.id, role="seat", seat="conformance", result={"verdict": "pass"}))

    monkeypatch.setattr(
        policy, "adjudicate",
        lambda verdicts, **kw: {"outcome": "probably fine", "reason": "?", "vetoed": []})

    with pytest.raises(engine.EngineError, match="knows how"):
        engine._adjudicate(node, report, seats=1)


def test_an_undecided_panel_does_not_take_a_branch_by_itself():
    """Updated by task 13, which gave the stop somewhere to go.

    When this was written the walk *stopped* at an undecided panel and that was the whole handling.
    Task 13 turned the stop into a suspension a person can answer. What has not changed, and is what
    this test was always protecting, is that **the runner never picks the branch itself**.
    """
    source = inspect.getsource(engine.walk)
    assert "policy.UNDECIDED" in source, "the walk must recognise the third outcome"
    assert "will not pick a" in source, (
        "an undecided stop should say nobody decided — reporting it as a failure would send the "
        "work back on a judgement the panel never made")


def test_the_undecided_stop_is_a_return_like_every_other_halt():
    """No new stopping mechanism, in task 2 or in task 13.

    Every halt in this engine is a returned report. Task 2 must not have reached task 1's suspend
    early by inventing a second way to stop, and task 13 must not have reached it by blocking — so
    the marker still has to be followed by a plain return.
    """
    source = inspect.getsource(engine.walk)
    marker = source.index("will not pick a")
    after = source[marker:marker + 500]
    assert "return _finish(report, confirmations)" in after


def test_lead_review_has_no_undecided_branch_which_is_why_it_stops():
    """The structural fact behind the stop, so the reason survives the code.

    `lead_review` offers `pass` and `fail`. There is no third edge for a tie, and inventing one
    would be the runner deciding where undecided work goes — which is a person's call and is task 13.
    """
    node = graph.BY_ID["lead_review"]
    assert sorted(node.branches) == ["fail", "pass"]
    assert policy.UNDECIDED not in node.branches
