"""Task 13 — an undecided panel suspends for a person, and their choice routes.

Task 2 gave a tie a name; task 1 gave a stop a way back. This is the one that connects them, and it
was blocked on both: `lead_review` branches on `pass` and `fail` only, and a tie is **not a gate** —
it has no gate name for `confirmed` to spend — so neither of the earlier tasks reached it.

## Why a `Ruling` is not an `Approval`

Task 1's answer to "one ledger or two?" was **one**, and the hazard it was avoiding is worth stating
precisely, because this task adds a second mechanism and has to explain why that is not the same
mistake. The danger there was two mechanisms answering the **same** question: an approval that one
ledger spends and the other never sees, so a gate opens with no reconstructable trail.

These answer different questions. An approval says *may this proceed past a gate*; a ruling says
*which way*. A ruling can never open a gate and an approval can never pick a branch, so there is no
spend either could miss. They are audited separately for the same reason — filing a ruling under
`confirmations` would make the report say a gate was confirmed when nobody confirmed anything.

## What must stay true

The runner never breaks the tie itself. Everything below is arranged around that: a run with no
ruling suspends, a ruling for the wrong branch is refused rather than coerced, and the record credits
**the person**, not the panel, with the decision the panel did not reach.
"""
import pytest

from ai_sdlc_runner import engine, graph, policy
from test_flow import DECISIONS, SPEC


def _run(seat_verdicts, **cfg_kw):
    """Walk with the seats answering as given, so `lead_review` reaches the outcome under test."""
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow",
                review_seats=len(seat_verdicts), high_risk_mode=True)
    base.update(cfg_kw)

    def dispatch(order):
        if order.get("seat"):
            return {"verdict": seat_verdicts[order["seat"]]}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    return engine.walk(engine.RunConfig(**base), dispatch, enabled=True)


def _split():
    """A two-seat panel that ties: one passes, one fails, and neither has the casting vote."""
    names = policy.seat_names(2)
    return {names[0]: "pass", names[1]: "fail"}


# --- the suspension --------------------------------------------------------------------------

def test_a_tie_suspends_rather_than_stopping_dead():
    """`suspended`, not `stopped`: a person *can* continue this.

    Reporting it as unresumable would hide a live decision from the one party entitled to make it —
    which is the opposite of what stopping for a person is for.
    """
    report = _run(_split())
    assert report.state == engine.SUSPENDED
    assert report.halted_at == "lead_review"


def test_the_suspension_says_what_an_answer_would_have_to_look_like():
    report = _run(_split())
    stop = report.suspended
    assert stop["undecided"] is True
    assert stop["gate"] is None, "a tie is not a gate — it has no gate to confirm"
    # Same keys as a gate suspension, so a client reads one shape rather than two.
    for key in ("node_id", "undecided", "gate", "gate_when", "verdict", "risk",
                "branches", "run_id"):
        assert key in stop
    assert stop["branches"] == ["fail", "pass"]
    assert stop["verdicts"], "the person needs to see who said what"
    assert "reason" in stop


def test_a_gate_suspension_and_a_tie_suspension_are_distinguishable():
    """Two different questions, and a caller must not offer the wrong control for either."""
    tie = _run(_split())
    assert tie.suspended["undecided"] is True
    assert tie.suspended["gate"] is None


def test_the_runner_never_picks_the_branch_itself():
    report = _run(_split())
    assert report.halted_at == "lead_review"
    assert "qa_verify" not in report.visited, "the pass branch was taken with nobody deciding"
    assert "review_failed" not in report.visited, "the fail branch was taken with nobody deciding"


# --- the ruling ------------------------------------------------------------------------------

def test_a_ruling_routes_the_run_and_is_credited_to_the_person():
    report = _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="pass")])
    assert report.halted_at != "lead_review", "the ruling should have carried the run onward"
    assert any("a person chose 'pass'" in r for r in report.rulings)


def test_the_panel_is_not_credited_with_a_verdict_it_did_not_reach():
    """The whole distinction `undecided` exists to draw.

    The adjudication still records what the panel actually did — nothing — and the ruling is filed
    separately as the person's. Merging them would let a later reader conclude the seats agreed.
    """
    report = _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="pass")])
    panel = [a for a in report.adjudications if a["node_id"] == "lead_review"][-1]
    assert panel["outcome"] == policy.UNDECIDED
    assert report.rulings, "the person's decision must be recorded somewhere"


def test_a_ruling_is_not_filed_as_a_gate_confirmation():
    report = _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="pass")])
    assert not any("lead_review" in c and "confirmed by the operator" in c
                   for c in report.confirmations), (
        "a ruling filed under confirmations would make the report claim a gate was confirmed when "
        "nobody confirmed one")


def test_either_branch_can_be_chosen():
    """A ruling is a decision, not a rubber stamp — 'fail' has to work as well as 'pass'.

    The extra loop decision is because 'fail' routes back through `review_failed` into the module
    loop, so the run reaches `next_module` once more than the pass branch does.
    """
    report = _run(_split(),
                  decisions={"next_module": ["module", "none", "none"], "feedback": "done"},
                  rulings=[engine.Ruling(node_id="lead_review", branch="fail")])
    assert "review_failed" in report.visited


def test_a_ruling_is_spent_once():
    report = _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="pass")])
    assert len(report.rulings) == 1


def test_a_ruling_for_an_unknown_node_is_refused():
    with pytest.raises(engine.EngineError, match="not in the flow"):
        _run(_split(), rulings=[engine.Ruling(node_id="no_such", branch="pass")])


def test_a_ruling_for_a_branch_the_node_does_not_offer_is_refused():
    """Refused, not coerced to the nearest branch. A branch nobody wrote down is not a decision."""
    with pytest.raises(engine.EngineError, match="does not offer"):
        _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="maybe")])


def test_a_ruling_from_another_run_is_refused(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(engine.EngineError, match="another run"):
        _run(_split(), journal=journal,
             rulings=[engine.Ruling(node_id="lead_review", branch="pass",
                                    run_id="/somewhere/else")])


def test_a_ruling_naming_this_run_is_accepted(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    run_id = engine.RunConfig(node_specs={}, decisions={}, journal=journal).run_id
    report = _run(_split(), journal=journal,
                  rulings=[engine.Ruling(node_id="lead_review", branch="pass", run_id=run_id)])
    assert report.rulings


def test_a_ruling_does_nothing_where_the_panel_actually_decided():
    """An unspent ruling must not reach in and override a decision that was reached.

    A person answering a tie that has since resolved is the stale case, and applying it anyway would
    let a stale view overturn a panel that agreed.
    """
    names = policy.seat_names(2)
    agreed = {names[0]: "pass", names[1]: "pass"}
    report = _run(agreed, rulings=[engine.Ruling(node_id="lead_review", branch="fail")])
    assert not report.rulings, "a ruling was spent at a node that decided for itself"
    assert "review_failed" not in report.visited


def test_the_ruling_survives_serialisation():
    report = _run(_split(), rulings=[engine.Ruling(node_id="lead_review", branch="pass")])
    assert report.as_dict()["rulings"] == report.rulings


# --- the CLI surface --------------------------------------------------------------------------

def test_the_cli_parses_a_ruling():
    from ai_sdlc_runner import cli

    assert cli._rulings(["lead_review=pass"]) == [
        engine.Ruling(node_id="lead_review", branch="pass")]


def test_the_cli_refuses_a_malformed_ruling():
    """Refused, never guessed.

    A mistyped ruling that silently becomes a different branch is a person's decision changed
    without them knowing, at the one place in the flow whose entire point is that a person decided.
    """
    from ai_sdlc_runner import cli

    for bad in ("lead_review", "=pass", "lead_review=", ""):
        with pytest.raises(SystemExit):
            cli._rulings([bad])
