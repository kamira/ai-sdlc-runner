"""The flow, the work orders it renders, and the engine that walks it (CHG-20260823-01).

Three properties the requirement states in its own words, each tested where it can actually fail:

* **one node, one kind of work** — building, verifying your own work and being reviewed are three
  nodes, not one; PR and merge are two.
* **every asking node is its own session**, opened per ask and closed after — and a multi-seat review
  is several asks, so each seat gets its own.
* **the gate is consulted, not carried** — the engine asks the policy before dispatching, because
  halting after the work was done is not halting.
"""
from __future__ import annotations

import json

import pytest

from ai_sdlc_runner import engine, graph, policy, workorder

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
DECISIONS = {
    "pm_confirm": "yes", "pm_signoff": "yes", "next_module": ["module", "none"],
    "lead_task_review": "pass", "re_review": "pass", "qa_accept": "pass", "feedback": "done",
}


def _cfg(**kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low")
    base.update(kw)
    return engine.RunConfig(**base)


class Recorder:
    def __init__(self):
        self.orders = []

    def __call__(self, order):
        self.orders.append(order)
        return {"ok": True}


# --------------------------------------------------------------------------------------
# the flow's shape
# --------------------------------------------------------------------------------------

def test_the_flow_is_consistent_and_agrees_with_the_policy():
    graph.validate()


def test_one_node_one_kind_of_work():
    """Build, self-verify and review are three; PR and merge are two; plan and confirm are two."""
    assert graph.BY_ID["engineer_build"].next == "engineer_selfverify"
    assert graph.BY_ID["engineer_selfverify"].next == "lead_task_review"
    assert graph.BY_ID["pr"].next == "merge"
    assert graph.BY_ID["pm_plan"].next == "pm_confirm"


def test_the_module_loop_has_a_back_edge():
    assert graph.BY_ID["record_module"].next == "next_module"
    assert graph.BY_ID["next_module"].kind == graph.LOOP


def test_the_retry_is_bounded():
    """One fix pass, one re-review, and a second failure halts. Not repeat-until-green."""
    assert graph.BY_ID["lead_task_review"].branches["fail"] == "fix_pass"
    assert graph.BY_ID["fix_pass"].next == "re_review"
    assert graph.BY_ID["re_review"].branches["fail"] == "halt_second_fail"
    assert graph.BY_ID["halt_second_fail"].kind == graph.TERMINAL


def test_feedback_returns_to_pm():
    """The flow closes rather than ends — new feedback is a new plan."""
    assert graph.BY_ID["feedback"].branches["more"] == "pm_plan"


def test_the_lead_reviews_work_it_did_not_write():
    assert graph.BY_ID["engineer_build"].role == "engineer"
    assert graph.BY_ID["lead_task_review"].role == "lead"


def test_qa_comes_after_the_review_not_instead_of_it():
    assert graph.BY_ID["lead_review"].next == "qa_verify"
    assert graph.BY_ID["qa_verify"].role == "qa"


# --------------------------------------------------------------------------------------
# work orders
# --------------------------------------------------------------------------------------

def test_an_order_has_exactly_the_closed_schema():
    order = workorder.render(graph.BY_ID["engineer_build"], SPEC,
                             policy.verdict("self_verify", "low"))
    assert sorted(order) == sorted(workorder.WORK_ORDER_FIELDS)


def test_an_order_carries_no_harness_specific_field():
    """Checked by enumerating what is present against the whitelist — never by searching for banned
    words, which scores false positives on any real corpus."""
    order = workorder.render(graph.BY_ID["qa_verify"], SPEC, policy.verdict("qa_verify", "low"))
    assert set(order["capabilities"]) == {"can_spawn", "can_write", "can_execute"}
    assert "tools" not in order and "model" not in order


def test_a_field_outside_the_contract_cannot_ride_in_through_the_caller():
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(graph.BY_ID["pr"], dict(SPEC, model="something"),
                         policy.verdict("pr", "low"))
    assert "outside the contract" in str(exc.value)


def test_a_missing_field_is_refused_rather_than_rendered_partial():
    spec = {k: v for k, v in SPEC.items() if k != "acceptance_predicate"}
    with pytest.raises(workorder.WorkOrderError) as exc:
        workorder.render(graph.BY_ID["pr"], spec, policy.verdict("pr", "low"))
    assert "acceptance_predicate" in str(exc.value)


def test_every_order_carries_the_permanent_halts_in_full():
    """Filtering them to the ones a node might hit needs a judgement about what the work will touch,
    and every omission is a gate quietly disarmed."""
    order = workorder.render(graph.BY_ID["merge"], SPEC, policy.verdict("merge", "low"))
    assert order["permanent_halts"] == list(policy.PERMANENT_HALTS)


def test_a_seat_order_differs_only_in_its_instructions():
    """What makes several seats a cross-check rather than one opinion asked repeatedly."""
    verdict = policy.verdict("lead_review", "low")
    node = graph.BY_ID["lead_review"]
    a = workorder.render(node, SPEC, verdict, seat="conformance")
    b = workorder.render(node, SPEC, verdict, seat="defect")
    assert a["instructions"] != b["instructions"]
    assert {k: v for k, v in a.items() if k != "instructions"} == \
           {k: v for k, v in b.items() if k != "instructions"}
    assert "independently" in a["instructions"]


def test_an_unknown_seat_is_refused():
    with pytest.raises(workorder.WorkOrderError):
        workorder.render(graph.BY_ID["lead_review"], SPEC,
                         policy.verdict("lead_review", "low"), seat="nobody")


# --------------------------------------------------------------------------------------
# the gate is consulted, not carried
# --------------------------------------------------------------------------------------

def test_a_stopping_verdict_halts_before_anything_is_dispatched():
    recorder = Recorder()
    report = engine.walk(_cfg(risk="high"), recorder, enabled=True)
    assert report.halted_at == "pm_confirm"
    assert not any(a.node_id == "pm_confirm" for a in report.asks)


def test_the_halt_names_the_gate_and_the_risk():
    report = engine.walk(_cfg(risk="medium"), Recorder(), enabled=True)
    assert "plan_confirmed" in report.halt_reason
    assert "risk medium" in report.halt_reason


def test_a_node_with_no_gate_says_so_rather_than_borrowing_one():
    verdict = engine.resolve_verdict(graph.BY_ID["record_module"], "high")
    assert verdict["gate"] is None
    assert verdict["verdict"] == policy.AUTO
    assert "no gate" in verdict["source"]


def test_a_low_risk_change_reaches_the_end():
    assert engine.walk(_cfg(), Recorder(), enabled=True).halted_at == "done"


def test_the_report_records_every_verdict_for_audit():
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert report.verdicts
    for verdict in report.verdicts.values():
        assert set(verdict) == {"gate", "risk", "verdict", "source", "tightened"}


# --------------------------------------------------------------------------------------
# one ask, one session
# --------------------------------------------------------------------------------------

class _CountingFactory:
    def __init__(self):
        self.made, self.log = [], []

    def __call__(self, seat=None):
        outer = self

        class _S:
            def ask(self, order):
                outer.log.append(("ask", len(outer.made) - 1))
                return {"ok": True}

            def close(self):
                outer.log.append(("close", len(outer.made) - 1))

        session = _S()
        self.made.append(session)
        return session


def test_every_ask_opens_its_own_session_and_closes_it():
    factory = _CountingFactory()
    report = engine.walk(_cfg(), factory, enabled=True)
    assert len(factory.made) == len(report.asks)
    assert factory.log == [step for i in range(len(factory.made))
                           for step in (("ask", i), ("close", i))]


def test_a_factory_that_reuses_a_session_is_refused():
    class _S:
        def ask(self, order):
            return {}

        def close(self):
            pass

    single = _S()
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(), lambda: single, enabled=True)
    assert "already returned" in str(exc.value)


def test_each_review_seat_is_its_own_ask():
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    seats = [a for a in report.asks if a.seat]
    assert len(seats) == policy.SEAT_FLOOR
    assert len({a.seat for a in seats}) == len(seats)


def test_only_asking_nodes_dispatch():
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    for ask in report.asks:
        assert graph.BY_ID[ask.node_id].role
    assert "record_module" not in {a.node_id for a in report.asks}


def test_no_ask_can_see_a_previous_answer():
    """A sentinel rather than a word search: the closed schema has no field a prior answer could
    occupy, and the sentinel proves none leaks in by another route."""
    sentinel = "SENTINEL-3ab77c-PRIOR"
    seen = []

    def dispatch(order):
        seen.append(json.dumps(order, ensure_ascii=False, sort_keys=True))
        return {"verdict": sentinel}

    engine.walk(_cfg(), dispatch, enabled=True)
    assert len(seen) > 1
    assert all(sentinel not in rendered for rendered in seen)


# --------------------------------------------------------------------------------------
# the question outlives the session
# --------------------------------------------------------------------------------------

class _FailAt:
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


@pytest.mark.parametrize("role", ["pm", "lead", "engineer", "qa"])
def test_any_role_can_be_interrupted_and_its_command_survives(tmp_path, role):
    """Every asking role, not only the review seats: whoever was mid-command when the session
    dropped must find the same command waiting, not a reconstructed approximation."""
    plan = [(a.node_id, a.role) for a in engine.walk(_cfg(), Recorder(), enabled=True).asks]
    index = next(i for i, (_, r) in enumerate(plan) if r == role)

    journal = engine.AskJournal(tmp_path / role)
    with pytest.raises(RuntimeError):
        engine.walk(_cfg(journal=journal), _FailAt(index), enabled=True)

    pending = journal.pending()
    assert len(pending) == 1
    assert pending[0]["order"]["role"] == role
    assert pending[0]["node_id"] == plan[index][0]


def test_what_was_already_answered_is_not_re_asked(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(RuntimeError):
        engine.walk(_cfg(journal=journal), _FailAt(2), enabled=True)
    entries = [json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((tmp_path / "asks").glob("*.json"))]
    assert [e["status"] for e in entries] == ["answered", "answered", "pending"]


# --------------------------------------------------------------------------------------
# nothing is skipped, nothing is guessed
# --------------------------------------------------------------------------------------

def test_the_engine_is_opt_in():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(), Recorder())
    assert "opt-in" in str(exc.value)


def test_an_untemplated_node_is_a_hard_error_naming_it():
    cfg = _cfg()
    del cfg.node_specs["engineer_build"]
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "engineer_build" in str(exc.value)


def test_an_unsupplied_branch_is_a_hard_error_not_a_guess():
    cfg = _cfg()
    del cfg.decisions["pm_confirm"]
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "does not guess" in str(exc.value)


def test_a_cycling_flow_is_stopped_rather_than_spun_forever():
    cfg = _cfg(max_steps=10)
    cfg.decisions["next_module"] = "module"
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "cycling without progress" in str(exc.value)


# --------------------------------------------------------------------------------------
# no skill, anywhere
# --------------------------------------------------------------------------------------

def test_no_module_reads_a_skill():
    """The change's own constraint, asserted rather than promised: nothing here resolves a skill
    path, vendored or installed. A quiet 'if the store is there, use it' branch is exactly what this
    catches."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "ai_sdlc_runner"
    for module in sorted(src.glob("*.py")):
        code = module.read_text(encoding="utf-8").split('"""', 2)[-1]
        for forbidden in ("skill_path", "skill_store", "skills/", "SKILL.md", "halt_gate"):
            assert forbidden not in code, f"{module.name} still reaches for {forbidden}"
