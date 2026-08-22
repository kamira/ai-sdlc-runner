"""The node engine (CHG-20260822-04 task 6).

The done-when has three clauses and each has its own group here: the engine walks the graph behind an
**opt-in flag**, an **untemplated node is a hard error naming the id**, and — carried forward from
task 5 and made binding by the review panel — a node whose **role has no shipped capability data
stops the run** rather than being skipped, with the run not advancing past it.

The requirement's own reason for independence is tested directly: one ask, one session, and a
multi-seat review is several asks. What the engine hands a dispatcher is a work order and nothing
else; there is no field in that schema able to carry a transcript, and the test asserts the
dispatcher never sees one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_sdlc_runner import engine, graph, workorder

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"
TREE = REPO_ROOT / "elements" / "v1.64.0"

pytestmark = pytest.mark.skipif(
    not (STORE / "assets").is_dir() or not TREE.is_dir(),
    reason="vendored store or element tree not present in this checkout",
)

SPEC = {
    "scope": "src/", "objective": "o", "done_criteria": ["d"], "input_artifacts": [],
    "expected_outputs": [], "acceptance_predicate": "p", "idempotence_probes": [], "workdir": ".",
}
#: A straight run: CHG already confirmed, plan passes, one task, review passes, acceptance passes.
DECISIONS = {
    "chg_confirmed": "yes", "plan_check": "pass", "next_task": "none",
    "task_review": "pass", "re_review": "pass", "acceptance": "pass",
}


def _cfg(**kw):
    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    # `low` is the only grade whose shipped verdicts are `auto` all the way through, so it is the
    # grade a straight-run fixture has to use now that the engine actually consults the policy.
    base = dict(node_specs=specs, decisions=dict(DECISIONS), languages=["en"], risk="low")
    base.update(kw)
    return engine.RunConfig(**base)


class Recorder:
    """A dispatcher that records exactly what it was handed, and nothing else exists to hand it."""

    def __init__(self):
        self.orders = []

    def __call__(self, order):
        self.orders.append(order)
        return {"ok": True}


# --------------------------------------------------------------------------------------
# done-when — the engine is opt-in
# --------------------------------------------------------------------------------------

def test_the_engine_refuses_to_run_unless_enabled():
    """Off by default, and it *refuses* rather than quietly doing nothing — a caller must not be
    able to mistake "flag off" for "ran and found nothing to do"."""
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, _cfg(), Recorder())
    assert "opt-in" in str(exc.value)


def test_the_four_stage_path_is_untouched():
    """D7: the existing path stays the only thing that runs until the flag flips, and flipping it is
    a separate later decision."""
    from ai_sdlc_runner import state
    assert state.STAGES == ("requirement_analysis", "structure_design", "implement", "acceptance")


# --------------------------------------------------------------------------------------
# done-when — nothing is skipped
# --------------------------------------------------------------------------------------

def test_a_node_with_no_work_order_is_a_hard_error_naming_the_node():
    cfg = _cfg()
    del cfg.node_specs["build"]
    cfg.decisions["next_task"] = ["task", "none"]
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    assert "build" in str(exc.value)
    assert "never a fall back" in str(exc.value)


def test_a_role_with_no_capability_data_stops_the_run_and_does_not_advance(monkeypatch):
    """The panel made this binding: terminate, name the role, and leave the frontier where it was.
    Driven through an actual walk rather than by calling the helper, which is the gap the review
    identified in the first version of this test."""
    original = graph.BY_ID["plan_check"]
    patched = graph.Node(id=original.id, kind=original.kind, source_phrase=original.source_phrase,
                         role="seat-risk", branches=dict(original.branches))
    monkeypatch.setitem(graph.BY_ID, "plan_check", patched)

    recorder = Recorder()
    cfg = _cfg()
    cfg.node_specs["plan_check"] = dict(SPEC)
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, cfg, recorder, enabled=True)
    message = str(exc.value)
    assert "seat-risk" in message and "stopping rather than skipping" in message
    # the frontier did not move past it: nothing after plan_check was ever dispatched
    assert all(o["node_id"] != "confirm_gate@autopilot:confirm_gate" for o in recorder.orders)


def test_an_unsupplied_branch_choice_is_a_hard_error_not_a_guess():
    cfg = _cfg()
    del cfg.decisions["chg_confirmed"]
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    assert "does not guess" in str(exc.value)


# --------------------------------------------------------------------------------------
# one ask, one session
# --------------------------------------------------------------------------------------

def test_each_ask_receives_a_work_order_and_nothing_else():
    """No transcript, no prior result, no accumulated context — and no field able to carry one."""
    recorder = Recorder()
    engine.walk(STORE, TREE, _cfg(), recorder, enabled=True)
    assert recorder.orders
    for order in recorder.orders:
        assert sorted(order) == sorted(workorder.WORK_ORDER_FIELDS)


def test_no_ask_can_see_a_previous_ask():
    """Independence stated as an absence, checked with a sentinel rather than by word-search.

    A substring search is the wrong instrument here and this test proved it on its first run: the
    anchor "Acceptance verification: verify the result" contains "result". So each ask returns a
    unique string, and the assertion is that no *later* order contains it — exact value, no false
    positives. The closed schema is the structural half of the same guarantee: there is no field a
    prior answer could occupy.
    """
    sentinel = "SENTINEL-9d21ab-PRIORANSWER"
    seen = []

    def dispatch(order):
        seen.append(json.dumps(order, ensure_ascii=False, sort_keys=True))
        return {"verdict": sentinel}

    engine.walk(STORE, TREE, _cfg(), dispatch, enabled=True)
    assert len(seen) > 1
    for rendered in seen:
        assert sentinel not in rendered
        assert sorted(json.loads(rendered)) == sorted(workorder.WORK_ORDER_FIELDS)


def test_only_asking_nodes_dispatch():
    """The requirement binds *asking* nodes. Work the runner does itself asks no model."""
    recorder = Recorder()
    report = engine.walk(STORE, TREE, _cfg(), recorder, enabled=True)
    dispatched = {a.node_id for a in report.asks}
    for node_id in dispatched:
        assert graph.BY_ID[node_id].role
    for node_id in ("handshake", "chg_confirmed", "next_task"):
        assert node_id not in dispatched


# --------------------------------------------------------------------------------------
# the review panel: one or many seats, each its own session
# --------------------------------------------------------------------------------------

def test_the_seat_floor_comes_from_the_store():
    shipped = json.loads((STORE / "assets" / "review_seats.json").read_text(encoding="utf-8"))
    assert engine.seat_floor(STORE) == len(shipped["seats"])


def test_the_default_is_the_shipped_floor():
    assert engine.resolve_seats(STORE, None, high_risk_mode=False) == engine.seat_floor(STORE)


def test_going_below_the_floor_is_refused_without_high_risk_mode():
    with pytest.raises(engine.EngineError) as exc:
        engine.resolve_seats(STORE, 1, high_risk_mode=False)
    assert "high-risk mode" in str(exc.value)
    assert "does not relax a gate on its own authority" in str(exc.value)


def test_high_risk_mode_allows_fewer_seats_and_the_run_records_it():
    """The user may relax it — that is their call. What it does not get to be is quiet."""
    recorder = Recorder()
    report = engine.walk(STORE, TREE, _cfg(review_seats=1, high_risk_mode=True), recorder,
                         enabled=True)
    assert report.relaxations
    assert "high-risk mode" in report.relaxations[0]
    assert "below the shipped floor" in report.relaxations[0]
    assert report.as_dict()["relaxations"] == report.relaxations


def test_more_seats_than_the_floor_needs_no_relaxation():
    assert engine.resolve_seats(STORE, 3, high_risk_mode=False) == 3
    report = engine.walk(STORE, TREE, _cfg(review_seats=3), Recorder(), enabled=True)
    assert report.relaxations == []


def test_each_seat_is_its_own_ask():
    """Three seats must be three sessions. One model answering three times in one context is one
    opinion repeated — the anchoring the seat count was bought to avoid."""
    recorder = Recorder()
    report = engine.walk(STORE, TREE, _cfg(), recorder, enabled=True)
    review_asks = [a for a in report.asks if a.node_id == "branch_review"]
    assert len(review_asks) == engine.seat_floor(STORE)
    assert len({a.seat for a in review_asks}) == len(review_asks)


def test_seats_open_in_the_shipped_order():
    """`_ordering` says the order is the opening order, least negotiable first, so opening fewer
    means taking a prefix — not picking favourites here."""
    shipped = list(json.loads((STORE / "assets" / "review_seats.json")
                              .read_text(encoding="utf-8"))["seats"])
    assert engine.seat_names(STORE, 1) == shipped[:1]
    assert engine.seat_names(STORE, 2) == shipped[:2]


def test_asking_for_more_seats_than_ship_is_refused():
    with pytest.raises(engine.EngineError):
        engine.seat_names(STORE, 99)


# --------------------------------------------------------------------------------------
# the walk itself
# --------------------------------------------------------------------------------------

def test_a_straight_run_reaches_close_out():
    report = engine.walk(STORE, TREE, _cfg(), Recorder(), enabled=True)
    assert report.visited[0] == "handshake"
    assert report.halted_at == "close_out"


def test_a_failed_plan_check_stops_at_the_shipped_terminal():
    cfg = _cfg()
    cfg.decisions["plan_check"] = "fail"
    report = engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    assert report.halted_at == "halt_bad_plan"


def test_a_second_review_failure_halts():
    cfg = _cfg()
    cfg.decisions.update({"next_task": ["task", "none"], "task_review": "fail",
                          "re_review": "fail"})
    report = engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    assert report.halted_at == "halt_second_fail"


def test_a_cycling_graph_is_stopped_rather_than_spun_forever():
    cfg = _cfg(max_steps=8)
    cfg.decisions["next_task"] = "task"      # always "task": the loop never ends
    cfg.decisions["task_review"] = "pass"
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    assert "cycling without progress" in str(exc.value)


# --------------------------------------------------------------------------------------
# every ask opens its own session and closes it — no continuity
# --------------------------------------------------------------------------------------

class _CountingSession:
    def __init__(self, log, index, raise_on_ask=False):
        self.log, self.index, self.raise_on_ask = log, index, raise_on_ask
        self.asks = 0

    def ask(self, order):
        self.asks += 1
        self.log.append(("ask", self.index))
        if self.raise_on_ask:
            raise RuntimeError("the model call failed")
        return {"ok": True}

    def close(self):
        self.log.append(("close", self.index))


class _Factory:
    def __init__(self, raise_on_first=False):
        self.log, self.made, self.raise_on_first = [], [], raise_on_first

    def __call__(self):
        session = _CountingSession(self.log, len(self.made),
                                   raise_on_ask=self.raise_on_first and not self.made)
        self.made.append(session)
        return session


def test_every_ask_opens_its_own_session_and_closes_it():
    """The lifecycle is the engine's, not the dispatcher's: open, ask once, close. A dispatcher
    cannot keep one alive across asks because it never gets the chance."""
    factory = _Factory()
    report = engine.walk(STORE, TREE, _cfg(), factory, enabled=True)
    assert len(factory.made) == len(report.asks)
    assert all(s.asks == 1 for s in factory.made)
    # every open is followed by exactly one ask and one close, in that order, before the next open
    assert factory.log == [step for i in range(len(factory.made))
                           for step in (("ask", i), ("close", i))]


def test_a_session_is_closed_even_when_the_ask_fails():
    """`finally`, not "on the happy path" — a failed ask must not leave a session open behind it."""
    factory = _Factory(raise_on_first=True)
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, _cfg(), factory, enabled=True)
    assert factory.log == [("ask", 0), ("close", 0)]


def test_a_factory_that_reuses_a_session_is_refused():
    """The persistent case, named and rejected: handing back a session that was already used is
    exactly the continuity the requirement rules out."""
    log = []
    single = _CountingSession(log, 0)
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(STORE, TREE, _cfg(), lambda: single, enabled=True)
    assert "already returned" in str(exc.value)
    assert "nothing carries over between asks" in str(exc.value)


def test_a_plain_callable_still_gets_one_session_per_ask():
    """Backwards compatible without weakening the property: the callable is wrapped one-shot, and a
    second ask on the same wrapper is refused."""
    session = engine._OneShot(lambda order: {"ok": True})
    assert session.ask({}) == {"ok": True}
    with pytest.raises(engine.EngineError) as exc:
        session.ask({})
    assert "spent" in str(exc.value)


def test_each_review_seat_gets_its_own_session():
    """Three seats, three sessions — not one session answering three times."""
    factory = _Factory()
    report = engine.walk(STORE, TREE, _cfg(), factory, enabled=True)
    seats = [a for a in report.asks if a.node_id == "branch_review"]
    assert len(seats) == engine.seat_floor(STORE)
    assert len(factory.made) == len(report.asks)      # no session shared by two seats


# --------------------------------------------------------------------------------------
# surviving a lost session: the question outlives it
# --------------------------------------------------------------------------------------

def test_the_question_is_written_down_before_it_is_asked(tmp_path):
    """A dropped session must cost the answer, not the question. Reconstructing a question later
    risks asking a subtly different one, and a subtly different question is how a rerun quietly
    stops being a rerun."""
    journal = engine.AskJournal(tmp_path / "asks")
    factory = _Factory(raise_on_first=True)
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, _cfg(journal=journal), factory, enabled=True)

    pending = journal.pending()
    assert len(pending) == 1
    assert pending[0]["status"] == "pending"
    assert sorted(pending[0]["order"]) == sorted(workorder.WORK_ORDER_FIELDS)


def test_a_pending_question_is_re_askable_verbatim(tmp_path):
    """The recovery property: what comes back off disk is byte-identical to what would be asked."""
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, _cfg(journal=journal), _Factory(raise_on_first=True), enabled=True)
    stored = journal.pending()[0]["order"]

    recorder = Recorder()
    engine.walk(STORE, TREE, _cfg(), recorder, enabled=True)
    assert json.dumps(stored, sort_keys=True) == json.dumps(recorder.orders[0], sort_keys=True)


def test_an_answered_ask_leaves_the_pending_set(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    report = engine.walk(STORE, TREE, _cfg(journal=journal), Recorder(), enabled=True)
    assert journal.pending() == []
    written = sorted((tmp_path / "asks").glob("*.json"))
    assert len(written) == len(report.asks)


def test_the_journal_is_lf_and_deterministic(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    engine.walk(STORE, TREE, _cfg(journal=journal), Recorder(), enabled=True)
    for path in (tmp_path / "asks").glob("*.json"):
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")


# --------------------------------------------------------------------------------------
# cross-model review: the same question, different answerers
# --------------------------------------------------------------------------------------

def test_seats_can_be_routed_to_different_models_without_changing_the_question():
    """What makes cross-review worth its cost: the seats differ, the question does not. Which model
    answers is a dispatch setting, and D5 keeps those out of the work order entirely."""
    routed = []
    orders = []

    class _Routed:
        def __init__(self, seat):
            self.seat = seat

        def ask(self, order):
            routed.append(self.seat)
            orders.append((self.seat, json.dumps(order, sort_keys=True)))
            return {"seat": self.seat}

        def close(self):
            pass

    def factory(seat=None):
        return _Routed(seat)

    report = engine.walk(STORE, TREE, _cfg(), factory, enabled=True)
    review_seats = [s for s in routed if s]
    assert len(review_seats) == engine.seat_floor(STORE)
    assert len(set(review_seats)) == len(review_seats)      # a distinct answerer per seat
    # every seat was handed the identical question — selected by seat, not by position, because
    # branch_review is not the last node in the run
    review_orders = {order for seat, order in orders if seat}
    assert len(review_orders) == 1
    assert [a.seat for a in report.asks if a.node_id == "branch_review"] == review_seats


# --------------------------------------------------------------------------------------
# every role survives an interruption, not just the review seats
# --------------------------------------------------------------------------------------

class _FailAt:
    """A factory whose Nth ask dies, standing in for a session that drops mid-command."""

    def __init__(self, index):
        self.index, self.count = index, 0

    def __call__(self, seat=None):
        outer = self

        class _S:
            def ask(self, order):
                outer.count += 1
                if outer.count - 1 == outer.index:
                    raise RuntimeError("session lost")
                return {"ok": True}

            def close(self):
                pass

        return _S()


def _ask_plan(**decisions):
    """(node_id, role) for every ask a run makes, in order."""
    cfg = _cfg()
    cfg.decisions.update(decisions)
    report = engine.walk(STORE, TREE, cfg, Recorder(), enabled=True)
    return [(a.node_id, a.role) for a in report.asks]


@pytest.mark.parametrize("role", ["analyst", "lead-implementer", "verifier"])
def test_any_role_can_be_interrupted_and_its_command_survives(tmp_path, role):
    """The requirement covers every asking role, not only the review panel: whoever was mid-command
    when the session dropped must find the same command waiting, not a reconstructed approximation."""
    plan = _ask_plan(chg_confirmed=["no", "yes"])
    index = next(i for i, (_, r) in enumerate(plan) if r == role)

    journal = engine.AskJournal(tmp_path / f"asks-{role}")
    cfg = _cfg(journal=journal)
    cfg.decisions["chg_confirmed"] = ["no", "yes"]
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, cfg, _FailAt(index), enabled=True)

    pending = journal.pending()
    assert len(pending) == 1
    assert pending[0]["node_id"] == plan[index][0]
    assert pending[0]["order"]["role"] == role


def test_the_dispatched_worker_is_covered_too(tmp_path):
    """`sub-implementer` only appears once the task loop is entered, so it needs its own run."""
    plan = _ask_plan(next_task=["task", "none"])
    index = next(i for i, (_, r) in enumerate(plan) if r == "sub-implementer")

    journal = engine.AskJournal(tmp_path / "asks-sub")
    cfg2 = _cfg(journal=journal)
    cfg2.decisions["next_task"] = ["task", "none"]
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, cfg2, _FailAt(index), enabled=True)

    pending = journal.pending()
    assert len(pending) == 1
    assert pending[0]["order"]["role"] == "sub-implementer"
    assert pending[0]["node_id"] == plan[index][0]


def test_what_was_already_answered_is_not_re_asked(tmp_path):
    """Resume needs both halves: the unanswered command preserved, and the answered ones marked so
    a rerun does not put them again. Everything before the drop is `answered`, exactly one is
    `pending`, and nothing is missing."""
    plan = _ask_plan()
    index = 2
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(RuntimeError):
        engine.walk(STORE, TREE, _cfg(journal=journal), _FailAt(index), enabled=True)

    entries = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((tmp_path / "asks").glob("*.json"))]
    assert [e["status"] for e in entries] == ["answered"] * index + ["pending"]
    assert [e["node_id"] for e in entries] == [n for n, _ in plan[:index + 1]]


def test_session_identity_survives_garbage_collection():
    """Regression for a bug the CI version matrix caught and 3.11 hid.

    The first version tracked `id(session)`. An id is not an identity once the object is gone —
    CPython reuses addresses, so on 3.13 a fresh session was handed the address of a collected one
    and rejected as a reuse. Every ask closes its session and drops it, which makes this the normal
    case rather than an exotic one; the check now compares the objects themselves.
    """
    import gc

    factory = _Factory()
    engine.walk(STORE, TREE, _cfg(), factory, enabled=True)
    gc.collect()
    # a second full run in the same process reuses the address space the first run released
    report = engine.walk(STORE, TREE, _cfg(), _Factory(), enabled=True)
    assert report.halted_at == "close_out"


# --------------------------------------------------------------------------------------
# the gate is consulted, not carried
# --------------------------------------------------------------------------------------

def test_the_engine_resolves_verdicts_from_the_shipped_policy():
    """Both independent verifiers named the same worst finding: the engine took a verdict from the
    caller's plan and walked past it without looking. A gate nobody consults is not a gate."""
    node = graph.BY_ID["confirm_gate"]
    assert engine.resolve_verdict(STORE, TREE, node, "low")["verdict"] == "auto"
    assert engine.resolve_verdict(STORE, TREE, node, "medium")["verdict"] == "confirm"
    assert engine.resolve_verdict(STORE, TREE, node, "high")["verdict"] == "halt"


def test_a_non_auto_verdict_stops_the_walk_before_anything_is_dispatched():
    """Halting after the work was done is not halting, so the gate is consulted first."""
    recorder = Recorder()
    report = engine.walk(STORE, TREE, _cfg(risk="high"), recorder, enabled=True)
    assert report.halted_at is not None
    assert "halt" in report.halt_reason
    node = graph.BY_ID[report.halted_at]
    assert not any(a.node_id == node.id for a in report.asks)


def test_the_halt_names_the_checkpoint_the_risk_and_the_source():
    report = engine.walk(STORE, TREE, _cfg(risk="high"), Recorder(), enabled=True)
    assert "risk high" in report.halt_reason
    assert ":" in report.halt_reason.split(" = ")[0]      # a real checkpoint id
    assert "assets/" in report.halt_reason or "halt_gate.py" in report.halt_reason


def test_a_medium_risk_confirm_also_stops():
    """`confirm` is not `auto`. Treating it as continue would be the runner approving on the user's
    behalf at the one gate the policy put there for them."""
    report = engine.walk(STORE, TREE, _cfg(risk="medium"), Recorder(), enabled=True)
    assert report.halted_at is not None
    assert "confirm" in report.halt_reason or "halt" in report.halt_reason


def test_a_node_with_no_checkpoint_gets_no_invented_one():
    """The silent fallback an independent verifier found: nodes with no checkpoint were defaulted to
    `halt:before_implement`, inside the module whose own docstring forbids silent fallbacks."""
    verdict = engine.resolve_verdict(STORE, TREE, graph.BY_ID["branch_review"], "high")
    assert verdict["checkpoint"] is None
    assert verdict["verdict"] == "auto"
    assert "no policy checkpoint" in verdict["source"]


def test_a_multi_checkpoint_node_is_judged_by_all_of_them():
    """`confirm_gate` carries two. The strictest wins — which is also why fork point 6 never has to
    be settled: anything that is not `auto` stops, so no ordering between the stopping values is
    needed."""
    node = graph.BY_ID["confirm_gate"]
    assert len(node.checkpoints) == 2
    verdict = engine.resolve_verdict(STORE, TREE, node, "high")
    assert verdict["verdict"] != "auto"
    assert verdict["checkpoint"] in node.checkpoints


def test_the_report_records_every_verdict_for_audit():
    report = engine.walk(STORE, TREE, _cfg(), Recorder(), enabled=True)
    assert report.verdicts
    for node_id, verdict in report.verdicts.items():
        assert set(verdict) == {"checkpoint", "risk", "verdict", "source"}
    assert report.as_dict()["verdicts"] == report.verdicts
