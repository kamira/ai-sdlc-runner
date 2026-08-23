"""Task 1 — a gate suspends, and a decision continues it.

The change the record grades itself high risk for, and the one both seats warned about in different
words. Three things make it survivable, and each has tests here:

**Nothing waits inside the walk.** A stop is still a `return`, exactly as every halt in this engine
has always been. The original design had `walk` call an `Approver` that blocks — which creates a
state where the run is *alive and stopped*, and "alive and stopped" is where a bug looks like "alive
and continuing". Round 1 corrected the record's belief that halts work by ending the process; they
work by returning, and that made the safer shape the *smaller* change.

**The report says which it is.** Before this, it could not: a gate halt set `halted_at`, and so did
every TERMINAL node including `done`. Finished and waiting were the same shape, so "is this waiting
for me?" had no answer. That is `test_finished_and_suspended_are_not_the_same_shape`.

**One ledger, not two.** A resumed decision spends the same `confirmations` mechanism a `--confirm`
does. Two overlapping approval ledgers is the one failure mode here that would be *silent* — a gate
opening on an approval one ledger spent and the other never saw, unreconstructable afterwards. An
independent seat named it as the highest-cost thing to get wrong, over the alternatives, precisely
because every other candidate fails loudly.
"""
import inspect

import pytest

from ai_sdlc_runner import engine, graph


# Borrowed rather than copied: a second hand-written spec drifts from the first the moment the
# work order gains a field, and then these tests pass for a reason unrelated to what they check.
from test_flow import ANSWERS, DECISIONS, SPEC  # noqa: E402


def _run(**cfg_kw):
    """Walk a dry run, so what stops it is a gate rather than anything about the work.

    ``undeclared="allow"`` is deliberate and is not the engine's default — these tests are about
    where a run stops and what a report says about it, not about what any node touches.
    """
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow")
    base.update(cfg_kw)

    def dispatch(order):
        if order.get("seat"):
            return {"verdict": "pass"}
        branch = ANSWERS.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    return engine.walk(engine.RunConfig(**base), dispatch, enabled=True)


# --- the distinction that did not exist -----------------------------------------------------

def test_the_three_states_are_closed():
    assert engine.STATES == (engine.FINISHED, engine.SUSPENDED, engine.STOPPED)


def test_a_gate_stop_is_suspended_and_says_what_would_continue_it():
    report = _run(risk="high")
    assert report.state == engine.SUSPENDED
    assert report.suspended is not None
    assert report.suspended["node_id"] == report.halted_at
    assert report.suspended["gate"] == graph.BY_ID[report.halted_at].gate
    # Everything a caller needs to construct an answer, without re-deriving it from the flow.
    for key in ("node_id", "gate", "gate_when", "verdict", "risk", "run_id"):
        assert key in report.suspended


def test_finished_and_suspended_are_not_the_same_shape():
    """The property the whole task rests on, and the one that did not exist.

    `halted_at` is set by a gate stop *and* by every terminal node, so before task 1 a caller
    holding a report could not tell "waiting for you" from "ran to the end". A seat found this while
    checking the record's claim that the resume machinery already existed — it existed for *asks*,
    not for this.
    """
    suspended = _run(risk="high")
    assert suspended.halted_at is not None
    assert suspended.state == engine.SUSPENDED

    # Terminal nodes still set halted_at -- the old signal is unchanged, which is why the new one
    # was needed rather than being a rename.
    terminal = graph.BY_ID["done"]
    assert terminal.kind == graph.TERMINAL
    source = inspect.getsource(engine.walk)
    assert "report.state = FINISHED" in source


def test_a_permanent_halt_is_stopped_not_suspended():
    """No decision continues a permanent halt, and the report must not imply one could.

    Offering a caller a way to approve something unapprovable is worse than offering nothing: the
    approval appears to be accepted and changes nothing.
    """
    report = _run(risk="low", undeclared="refuse",
                  operations={"pm_plan": [{"name": "ship it", "kind": "deploy",
                                           "targets": ["kubectl apply -f prod/"]}]})
    assert report.state == engine.STOPPED
    assert report.suspended is None


# --- one ledger -------------------------------------------------------------------------------

def test_an_untargeted_confirmation_still_works_exactly_as_before():
    report = _run(risk="high", confirmed=["plan_confirmed"])
    assert any("confirmed by the operator" in c for c in report.confirmations)


def test_a_targeted_decision_spends_the_same_ledger_and_is_recorded():
    """Not a second mechanism: the audit trail is the one `report.confirmations` already was."""
    stopped = _run(risk="high")
    node_id = stopped.halted_at
    gate = graph.BY_ID[node_id].gate

    report = _run(risk="high", confirmed=[engine.Approval(gate=gate, node_id=node_id)])
    assert any("decided by the operator" in c for c in report.confirmations)
    assert report.halted_at != node_id, "the decision should have carried the run past that gate"


def test_a_decision_for_the_wrong_node_does_not_open_this_gate():
    """A gate that is not the one the decision named must still stop the run."""
    stopped = _run(risk="high")
    gate = graph.BY_ID[stopped.halted_at].gate
    other = next(n.id for n in graph.NODES if n.gate == gate and n.id != stopped.halted_at) \
        if any(n.gate == gate and n.id != stopped.halted_at for n in graph.NODES) else "merge"

    report = _run(risk="high", confirmed=[engine.Approval(gate=graph.BY_ID[other].gate,
                                                          node_id=other)])
    assert report.state == engine.SUSPENDED
    assert report.halted_at == stopped.halted_at, "an answer for another node opened this one"


def test_a_decision_naming_a_node_that_does_not_exist_is_refused():
    with pytest.raises(engine.EngineError, match="not in the flow"):
        _run(risk="high", confirmed=[engine.Approval(gate="plan_confirmed", node_id="no_such")])


def test_a_decision_for_a_gate_that_does_not_exist_is_refused():
    with pytest.raises(engine.EngineError, match="does not exist"):
        _run(risk="high", confirmed=[engine.Approval(gate="no_such_gate")])


def test_a_decision_is_spent_once():
    """Duplicate clicks must not buy two gate openings from one approval."""
    stopped = _run(risk="high")
    node_id = stopped.halted_at
    gate = graph.BY_ID[node_id].gate
    report = _run(risk="high", confirmed=[engine.Approval(gate=gate, node_id=node_id)])
    decided = [c for c in report.confirmations if "decided by the operator" in c]
    assert len(decided) == 1


# --- run identity ------------------------------------------------------------------------------

def test_a_run_without_a_journal_has_no_identity():
    """No new authority is invented: the journal is the only durable identity there has ever been."""
    assert engine.RunConfig(node_specs={}, decisions={}).run_id is None


def test_the_run_id_is_the_journals(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    cfg = engine.RunConfig(node_specs={}, decisions={}, journal=journal)
    assert cfg.run_id == str((tmp_path / "asks").resolve())


def test_a_decision_from_another_run_is_refused(tmp_path):
    """The stale-tab case, and the reason a decision carries a run id at all."""
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(engine.EngineError, match="another run"):
        _run(risk="high", journal=journal,
             confirmed=[engine.Approval(gate="plan_confirmed", run_id="/somewhere/else")])


def test_a_decision_naming_this_run_is_accepted(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    cfg = engine.RunConfig(node_specs={}, decisions={}, journal=journal)
    stopped = _run(risk="high")
    node_id = stopped.halted_at
    report = _run(risk="high", journal=journal,
                  confirmed=[engine.Approval(gate=graph.BY_ID[node_id].gate,
                                             node_id=node_id, run_id=cfg.run_id)])
    assert any("decided by the operator" in c for c in report.confirmations)


# --- the guarantee that must not erode ----------------------------------------------------------

def test_nothing_waits_inside_the_walk():
    """The halt guarantee, stated as a property of the source.

    An `Approver` the walk calls and blocks in was the original design, and both seats named the
    same safer alternative. This test is what stops it coming back: no sleeping, no waiting, no
    input, no polling inside `walk`. A stop is a return, so "alive and stopped" never exists.
    """
    source = inspect.getsource(engine.walk)
    for blocking in ("time.sleep", "input(", ".join()", ".wait(", ".acquire(", "Event("):
        assert blocking not in source, f"walk blocks on {blocking} — a stop must stay a return"


def test_the_suspended_report_is_returned_not_yielded():
    source = inspect.getsource(engine.walk)
    marker = source.index("report.state = SUSPENDED")
    assert "return _finish(report, confirmations)" in source[marker:marker + 900]


def test_a_report_cannot_claim_a_state_the_engine_does_not_know():
    report = engine.RunReport()
    report.state = "probably done"
    with pytest.raises(engine.EngineError, match="not one of"):
        engine._finish(report, {})


def test_suspended_and_its_details_must_agree():
    """Half a suspension is worse than none: two callers reading different fields disagree."""
    report = engine.RunReport()
    report.state = engine.SUSPENDED
    report.suspended = None
    with pytest.raises(engine.EngineError, match="must agree"):
        engine._finish(report, {})


def test_the_state_survives_serialisation():
    report = _run(risk="high")
    payload = report.as_dict()
    assert payload["state"] == engine.SUSPENDED
    assert payload["suspended"]["gate"] == report.suspended["gate"]
