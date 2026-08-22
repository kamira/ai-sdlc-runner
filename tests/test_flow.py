"""The flow, the work orders it renders, and the engine that walks it (CHG-20260823-01).

Four properties the requirement states in its own words, each tested where it can actually fail:

* **one node, one kind of work** — building, verifying your own work and being reviewed are three
  nodes, not one; PR and merge are two.
* **every asking node is its own session**, opened per ask and closed after — and a multi-seat review
  is several asks, so each seat gets its own.
* **the gate stops the run** — before the work where the work is the risk, after it where the point
  is to stop holding the result. A halt is a pause with a way back: confirming it continues.
* **the answers decide** — *多個 review 來共同交叉決議達到一致性共識或者多數決才允許放行*. A review
  whose verdict routes nothing is a review that was never consulted, which is how the first two
  versions of this engine passed their own tests while deciding nothing.
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

#: Branches the runner picks itself, at the two decision nodes nobody is asked at.
DECISIONS = {"next_module": ["module", "none"], "feedback": "done"}

#: What each asked node is answered, when the test does not say otherwise. Everything passes, so a
#: test that wants a failure changes exactly the one answer it is about.
ANSWERS = {
    "pm_confirm": "yes", "pm_signoff": "yes",
    "lead_task_review": "pass", "re_review": "pass", "qa_accept": "pass",
}
SEAT_PASS = "pass"


def _cfg(**kw):
    """A config for a dry run.

    ``undeclared="allow"`` is explicit here and is *not* the engine's default: a node that does real
    work and declares no operations is refused, because a plan that simply omits `operations` used
    to be checked against nothing at all. These tests are about the flow rather than about what any
    node touches, so they say so — and the tests that are about the declaration say the opposite.
    """
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow")
    base.update(kw)
    return engine.RunConfig(**base)


def _answer(order, answers=None):
    """The answer a model would give to this order — a branch where the node needs one."""
    if order.get("seat"):
        return {"verdict": SEAT_PASS}
    branch = (answers or ANSWERS).get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


class Recorder:
    """A dispatcher that answers every order and keeps what it was sent.

    ``answers`` overrides one node's answer; a list is consumed one per visit and falls back to the
    default afterwards. ``seat_verdicts`` applies to the **first** panel only. Both exist for the
    same reason: a failure that repeats forever tests the retry, not the routing, and the flow's
    only bound on repeats is `max_steps` — a test that hits it proves nothing about the branch.
    """

    def __init__(self, answers=None, seat_verdicts=None):
        self.orders = []
        self.answers = {k: (list(v) if isinstance(v, list) else v)
                        for k, v in (answers or {}).items()}
        self.seat_verdicts = seat_verdicts or {}
        self._seats_asked = 0

    def __call__(self, order):
        self.orders.append(order)
        seat = order.get("seat")
        if seat:
            first_panel = self._seats_asked < policy.SEAT_FLOOR
            self._seats_asked += 1
            verdict = self.seat_verdicts.get(seat, SEAT_PASS) if first_panel else SEAT_PASS
            return {"verdict": verdict}

        node_id = order["node_id"]
        override = self.answers.get(node_id)
        if isinstance(override, list):
            override = override.pop(0) if override else None
        if override:
            return {"verdict": override}
        return _answer(order)


#: The module loop's branches for a run that goes round twice — a failed panel or a failed
#: acceptance sends the flow back into it, and the second pass finds nothing left to build.
TWO_PASSES = {"next_module": ["module", "none", "none"], "feedback": "done"}


#: `merge` stops at every risk grade, so a run that is meant to reach the end confirms it. Spelling
#: this out in the tests rather than grading merge as auto is the point: the door asks every time.
THROUGH = ("merge",)

#: Every gate a high-risk run stops at, so a test can confirm them all and watch the run continue.
ALL_GATES = tuple(policy.GATES)


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
    assert graph.BY_ID["lead_review"].branches["pass"] == "qa_verify"
    assert graph.BY_ID["qa_verify"].role == "qa"


def test_a_review_gate_is_consulted_after_the_review_not_before_it():
    """A gate that halts *before* the work it grades is a review a high-risk change never gets."""
    for node_id in ("lead_review", "qa_verify", "qa_accept", "lead_task_review"):
        assert graph.BY_ID[node_id].gate_when == "after", node_id


def test_a_one_way_door_is_gated_before_it_swings():
    assert graph.BY_ID["merge"].gate_when == "before"


def test_a_gate_that_confirms_someones_judgement_waits_for_the_judgement():
    """`feasibility_confirmed` asks a person to confirm the lead's assessment. Stopping in front of
    the lead hands them an empty page — a verifier called this out, and it was wrong."""
    assert graph.BY_ID["lead_assess"].gate_when == "after"
    report = engine.walk(_cfg(risk="high", confirmed=("plan_confirmed",)), Recorder(), enabled=True)
    assert report.halted_at == "lead_assess"
    assert any(a.node_id == "lead_assess" for a in report.asks)


def test_every_node_that_is_asked_to_decide_says_its_answer_decides():
    """Otherwise the branch comes from the plan while somebody is being asked — a question whose
    answer changes nothing."""
    for node in graph.NODES:
        if node.branches and node.role and node.role != "seat":
            assert node.answer_decides, node.id


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
    # `seat` is the one other field that differs, and has to: adjudication counts verdicts by seat,
    # so an answer nobody can attribute to a seat cannot be counted towards a majority.
    ignore = {"instructions", "seat"}
    assert {k: v for k, v in a.items() if k not in ignore} == \
           {k: v for k, v in b.items() if k not in ignore}
    assert "independently" in a["instructions"]


def test_an_unknown_seat_is_refused():
    with pytest.raises(workorder.WorkOrderError):
        workorder.render(graph.BY_ID["lead_review"], SPEC,
                         policy.verdict("lead_review", "low"), seat="nobody")


# --------------------------------------------------------------------------------------
# the gate stops the run
# --------------------------------------------------------------------------------------

def test_a_before_gate_halts_without_dispatching_the_work_it_guards():
    """`merge` is gated before, and stops at every grade: the door is never opened first."""
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert report.halted_at == "merge"
    assert not any(a.node_id == "merge" for a in report.asks)


def test_an_after_gate_holds_the_result_rather_than_refusing_to_produce_it():
    """`pm_confirm` is gated after: PM is asked, and the run stops holding their answer."""
    report = engine.walk(_cfg(risk="high"), Recorder(), enabled=True)
    assert report.halted_at == "pm_confirm"
    assert any(a.node_id == "pm_confirm" for a in report.asks)


def test_the_halt_names_the_gate_and_the_risk():
    report = engine.walk(_cfg(risk="medium"), Recorder(), enabled=True)
    assert "plan_confirmed" in report.halt_reason
    assert "risk medium" in report.halt_reason


def test_a_halt_is_a_pause_with_a_way_back():
    """Without this every medium-risk run ends at the same node forever, and most of the gate matrix
    is unreachable — which is exactly what an independent verifier found."""
    stuck = engine.walk(_cfg(risk="medium"), Recorder(), enabled=True)
    assert stuck.halted_at == "pm_confirm"
    through = engine.walk(_cfg(risk="medium", confirmed=ALL_GATES), Recorder(), enabled=True)
    assert through.halted_at == "done"


def test_a_confirmed_gate_is_recorded_rather_than_silently_skipped():
    report = engine.walk(_cfg(risk="medium", confirmed=ALL_GATES), Recorder(), enabled=True)
    assert report.confirmations
    assert any("plan_confirmed" in line for line in report.confirmations)


def test_confirming_one_gate_does_not_confirm_the_next():
    report = engine.walk(_cfg(risk="medium", confirmed=("plan_confirmed",)), Recorder(),
                         enabled=True)
    assert report.halted_at == "lead_assess"


def test_a_high_risk_run_that_is_confirmed_all_the_way_still_reaches_every_gate():
    report = engine.walk(_cfg(risk="high", confirmed=ALL_GATES), Recorder(), enabled=True)
    assert report.halted_at == "done"
    assert set(graph.gates_used()) <= {v["gate"] for v in report.verdicts.values() if v["gate"]}


def test_a_node_with_no_gate_says_so_rather_than_borrowing_one():
    verdict = engine.resolve_verdict(graph.BY_ID["record_module"], "high")
    assert verdict["gate"] is None
    assert verdict["verdict"] == policy.AUTO
    assert "no gate" in verdict["source"]


def test_a_low_risk_change_reaches_the_end():
    assert engine.walk(_cfg(confirmed=THROUGH), Recorder(), enabled=True).halted_at == "done"


def test_merging_asks_even_at_low_risk():
    """A one-way door is a door whatever the change's grade. `low` grades the change, not the door."""
    assert engine.walk(_cfg(), Recorder(), enabled=True).halted_at == "merge"


def test_the_report_records_every_verdict_for_audit():
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert report.verdicts
    for verdict in report.verdicts.values():
        assert set(verdict) == {"gate", "risk", "verdict", "source", "tightened"}


# --------------------------------------------------------------------------------------
# the answers decide
# --------------------------------------------------------------------------------------

def test_a_failed_module_review_routes_to_the_fix_pass():
    report = engine.walk(_cfg(), Recorder({"lead_task_review": ["fail"]}), enabled=True)
    assert "fix_pass" in report.visited


def test_two_failures_on_one_module_halt_rather_than_retry():
    recorder = Recorder({"lead_task_review": "fail", "re_review": "fail"})
    report = engine.walk(_cfg(), recorder, enabled=True)
    assert report.halted_at == "halt_second_fail"


def test_a_failed_acceptance_does_not_reach_the_pull_request():
    report = engine.walk(_cfg(decisions=dict(TWO_PASSES), confirmed=THROUGH),
                         Recorder({"qa_accept": ["fail"]}), enabled=True)
    assert "acceptance_failed" in report.visited
    assert report.visited.index("acceptance_failed") < len(report.visited)
    assert "pr" not in report.visited[:report.visited.index("acceptance_failed") + 1]


def test_an_answer_naming_no_branch_is_an_error_not_a_default():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(), lambda order: {"ok": True}, enabled=True)
    assert "named no branch" in str(exc.value)


def test_an_answer_naming_a_branch_that_does_not_exist_is_refused():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(), Recorder({"pm_confirm": "maybe"}), enabled=True)
    assert "not one of" in str(exc.value)


# --------------------------------------------------------------------------------------
# the seats adjudicate
# --------------------------------------------------------------------------------------

def test_the_panel_passing_routes_to_qa():
    report = engine.walk(_cfg(), Recorder(), enabled=True)
    assert report.adjudications
    assert report.adjudications[0]["outcome"] == "pass"
    assert "qa_verify" in report.visited


def test_a_majority_against_does_not_pass():
    seats = {"conformance": "pass", "defect": "fail", "risk": "fail"}
    report = engine.walk(_cfg(decisions=dict(TWO_PASSES), confirmed=THROUGH),
                         Recorder(seat_verdicts=seats), enabled=True)
    assert report.adjudications[0]["outcome"] != "pass"
    assert "review_failed" in report.visited


def test_a_veto_seat_alone_is_enough_to_stop_it():
    """The veto seat's subject is a matter of fact, not of opinion, so a majority cannot outvote."""
    seats = {"conformance": "fail", "defect": "pass", "risk": "pass"}
    report = engine.walk(_cfg(decisions=dict(TWO_PASSES), confirmed=THROUGH),
                         Recorder(seat_verdicts=seats), enabled=True)
    assert report.adjudications[0]["outcome"] != "pass"
    assert "review_failed" in report.visited


def test_the_adjudication_records_every_seats_verdict():
    seats = {"conformance": "pass", "defect": "fail", "risk": "pass"}
    report = engine.walk(_cfg(decisions=dict(TWO_PASSES), confirmed=THROUGH),
                         Recorder(seat_verdicts=seats), enabled=True)
    assert report.adjudications[0]["verdicts"] == seats


def test_the_panel_routes_through_the_policy_not_the_engines_own_arithmetic():
    """Whatever `policy.adjudicate` says is what happens — the rule lives in one place."""
    seats = {"conformance": "pass", "defect": "fail", "risk": "pass"}
    report = engine.walk(_cfg(decisions=dict(TWO_PASSES), confirmed=THROUGH),
                         Recorder(seat_verdicts=seats), enabled=True)
    expected = policy.adjudicate(seats)
    assert report.adjudications[0]["outcome"] == expected["outcome"]


# --------------------------------------------------------------------------------------
# the permanent halts
# --------------------------------------------------------------------------------------

#: Six ordinary English sentences, one per red line, written by an independent verifier to break the
#: previous check. Not one of them contained a listed keyword, and **all six were dispatched**. They
#: are the corpus now, because a blacklist stops the phrasings somebody thought of and these are the
#: proof that the phrasings nobody thought of are always available.
BYPASS = (
    ("deploy", "promote the new build into the live environment"),
    ("migration", "rewrite all customer rows to the new format"),
    ("delete", "erase every customer record permanently"),
    ("money", "wire USD 500 to the vendor"),
    ("access", "grant Alice administrator privileges"),
    ("publish", "make the embargoed article visible to everyone"),
)


def _op(description, kind=policy.ORDINARY):
    return {"description": description, "kind": kind}


@pytest.mark.parametrize("kind,description", BYPASS)
def test_a_declared_red_line_stops_however_it_is_worded(kind, description):
    """The guarantee is the declaration, so the wording cannot get around it."""
    cfg = _cfg(confirmed=ALL_GATES, high_risk_mode=True,
               operations={"engineer_build": [_op(description, kind)]})
    report = engine.walk(cfg, Recorder(), enabled=True)
    assert report.halted_at == "engineer_build"
    assert policy.PERMANENT_HALT_KINDS[kind] in report.halt_reason


@pytest.mark.parametrize("kind,description", BYPASS)
def test_the_backstop_catches_a_red_line_misdeclared_as_ordinary(kind, description):
    """Every one of these six passed the old check. The word lists are a **second** net now — they
    can add a stop and can never remove one — and they were widened until all six trip."""
    assert policy.permanent_halt(description) is not None, description
    cfg = _cfg(confirmed=ALL_GATES, operations={"engineer_build": [_op(description)]})
    assert engine.walk(cfg, Recorder(), enabled=True).halted_at == "engineer_build"


def test_an_operation_that_declares_nothing_is_refused_not_assumed_safe():
    """The inversion that is the whole fix: unclassified stops, rather than being ordinary by
    default. A red line whose default branch is "proceed" is not a red line."""
    cfg = _cfg(operations={"engineer_build": [{"description": "do a thing"}]})
    with pytest.raises(policy.PolicyError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "declares no kind" in str(exc.value)


def test_a_bare_string_operation_is_refused():
    cfg = _cfg(operations={"engineer_build": ["deploy to production"]})
    with pytest.raises(policy.PolicyError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "must declare what kind of work it is" in str(exc.value)


def test_a_kind_nobody_defined_is_refused():
    cfg = _cfg(operations={"engineer_build": [_op("a thing", "probably-fine")]})
    with pytest.raises(policy.PolicyError) as exc:
        engine.walk(cfg, Recorder(), enabled=True)
    assert "not one of" in str(exc.value)


def test_no_confirmation_relaxes_a_permanent_halt():
    cfg = _cfg(confirmed=ALL_GATES, high_risk_mode=True,
               operations={"record_module": [_op("tick the box", "delete")]})
    report = engine.walk(cfg, Recorder(), enabled=True)
    assert report.halted_at == "record_module"
    assert "hard delete" in report.halt_reason


def test_a_permanent_halt_stops_before_the_work_is_dispatched():
    cfg = _cfg(operations={"engineer_build": [_op("rotate the key", "access")]})
    report = engine.walk(cfg, Recorder(), enabled=True)
    assert report.halted_at == "engineer_build"
    assert not any(a.node_id == "engineer_build" for a in report.asks)


def test_ordinary_work_declared_as_such_is_not_stopped():
    cfg = _cfg(confirmed=THROUGH,
               operations={"engineer_build": [_op("rename a local variable"),
                                              _op("add a unit test")]})
    assert engine.walk(cfg, Recorder(), enabled=True).halted_at == "done"


def test_every_kind_has_a_description_and_a_backstop_word_list():
    """Not the same as the old test, which fed each rule's own description back into its own word
    list and called the tautology a pass."""
    assert set(policy.PERMANENT_HALT_KINDS) == set(policy._HALT_WORDS)
    assert len(policy.PERMANENT_HALTS) == len(policy.PERMANENT_HALT_KINDS) == 6


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
                return _answer(order)

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
            return _answer(order)

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
        return dict(_answer(order), rationale=sentinel)

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
                return _answer(order)

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
    cfg = _cfg(confirmed=THROUGH)
    del cfg.decisions["feedback"]
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

#: Every way this repo used to reach a skill, plus the shapes a new one would take. Each needle is
#: **assembled from halves** so this file does not contain the literal it hunts for — otherwise the
#: scan's only finding is itself, and the usual fix (exempt the test file) puts the one file most
#: likely to grow a shortcut outside the scan.
#:
#: A path fragment alone was not enough: the previous version scanned only `src/ai_sdlc_runner/*.py`
#: and discarded the module docstring first, so a module that reached for a skill in its docstring,
#: or from `tools/`, or by importing the deleted store, passed it unchallenged.
FORBIDDEN = tuple(a + b for a, b in (
    ("skill", "_path"), ("skill", "_store"), ("skill", "store"), ("skill", "s/"),
    ("skill", "s\\"), ("SKILL", ".md"), ("ai-sdlc-", "autopilot/"), ("element", "s/"),
    ("halt", "_gate"), ("doc_integrity", "_check"), ("toolchain", "_probe"),
))

#: `graph.py` explains in prose that the flow was *designed from* the autopilot flowchart and is not
#: read from it. Naming the thing you do not depend on is not depending on it — but the exemption is
#: per-file and listed here so adding another is a visible decision, and it exempts the file, not
#: the rule: `graph.py` is still scanned by `test_no_skill_content_is_stored_in_the_repo`.
PROSE_EXEMPT = {"graph.py"}


def _scanned_files():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for folder in ("src", "tools", "tests"):
        yield from sorted((root / folder).rglob("*.py"))
    yield from sorted(root.glob("*.toml"))
    yield from sorted(root.glob("*.md"))
    yield from sorted((root / ".github" / "workflows").glob("*.yml"))


def test_no_file_reaches_for_a_skill():
    """The change's own constraint, asserted rather than promised, over everything that could carry
    it: source, tools, tests, packaging, the README and CI — docstrings and comments included."""
    offences = []
    for path in _scanned_files():
        code = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN:
            if forbidden in code and path.name not in PROSE_EXEMPT:
                offences.append(f"{path.name} reaches for {forbidden!r}")
    assert not offences, offences


def test_no_skill_content_is_stored_in_the_repo():
    """Not "no module reads one" — no copy exists to read."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for folder in ("skills", "elements"):
        assert not (root / folder).exists(), f"{folder}/ is back"
    assert not list(root.rglob("SKILL" + ".md"))


def test_the_scan_reads_this_file_and_every_docstring_in_it():
    """A tripwire nothing can trip is a comment. This proves the scan reaches the file most likely
    to grow a shortcut — its own — and does not throw docstrings away before looking."""
    scanned = {p.name for p in _scanned_files()}
    for expected in ("engine.py", "policy.py", "graph.py", "cli.py", "test_flow.py",
                     "ledger_check.py", "pyproject.toml", "README.md"):
        assert expected in scanned, f"the scan does not reach {expected}"

    from pathlib import Path
    text = Path(__file__).read_text(encoding="utf-8")
    assert '"""' in text, "the scan is throwing docstrings away"
    assert "SENTINEL-3ab77c-PRIOR" in text, "the scan is not reading string literals"


# --------------------------------------------------------------------------------------
# silence is not a declaration
# --------------------------------------------------------------------------------------

def test_a_node_that_does_work_and_declares_nothing_is_refused():
    """The hole a verifier found: the check only ever read what a plan volunteered, so omitting
    `operations` skipped it entirely. The red lines could be walked past by saying *less*."""
    cfg = _cfg(undeclared="refuse")
    report = engine.walk(cfg, Recorder(), enabled=True)
    assert report.halted_at == "pm_plan"
    assert "declares no operations" in report.halt_reason


def test_refusing_is_the_default():
    cfg = engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                           decisions=dict(DECISIONS), risk="low")
    assert cfg.undeclared == "refuse"
    assert engine.walk(cfg, Recorder(), enabled=True).halted_at == "pm_plan"


def test_a_node_that_declares_its_work_passes():
    declared = {node.id: [_op("ordinary development work")]
                for node in graph.NODES if node.role and node.role != "seat"}
    cfg = _cfg(undeclared="refuse", confirmed=THROUGH, operations=declared)
    assert engine.walk(cfg, Recorder(), enabled=True).halted_at == "done"


def test_a_review_seat_owes_no_declaration():
    """A seat reads and answers. It is the nodes that may write or execute that owe a declaration."""
    declared = {node.id: [_op("ordinary development work")]
                for node in graph.NODES if node.role and node.role != "seat"}
    cfg = _cfg(undeclared="refuse", confirmed=THROUGH, operations=declared)
    report = engine.walk(cfg, Recorder(), enabled=True)
    assert report.halted_at == "done"
    assert any(a.seat for a in report.asks)


def test_allowing_an_undeclared_run_is_recorded_as_a_relaxation():
    """`allow` exists for dry runs and never happens silently: a run that checked nothing against
    the permanent halts says so in its own report."""
    report = engine.walk(_cfg(confirmed=THROUGH), Recorder(), enabled=True)
    assert report.relaxations
    assert any("nothing was checked against the permanent halts" in r for r in report.relaxations)


# --------------------------------------------------------------------------------------
# a confirmation is spent, not standing
# --------------------------------------------------------------------------------------

def test_one_confirmation_covers_one_stop():
    """A verifier found that a single `--confirm plan_confirmed`, given to unlock a revision loop,
    also waved through the final approval on the way out. The operator confirmed *that* stop."""
    answers = {"pm_confirm": ["no", "yes"]}
    once = engine.walk(_cfg(risk="medium", confirmed=("plan_confirmed",)), Recorder(answers),
                       enabled=True)
    assert once.halted_at == "pm_confirm"
    assert len(once.confirmations) == 1


def test_confirming_twice_covers_two_stops():
    answers = {"pm_confirm": ["no", "yes"]}
    twice = engine.walk(_cfg(risk="medium", confirmed=("plan_confirmed", "plan_confirmed")),
                        Recorder(answers), enabled=True)
    assert twice.halted_at == "lead_assess"
    assert len(twice.confirmations) == 2


def test_a_confirmation_records_which_node_it_covered():
    report = engine.walk(_cfg(risk="medium", confirmed=("plan_confirmed",)), Recorder(),
                         enabled=True)
    assert "at pm_confirm" in report.confirmations[0]
