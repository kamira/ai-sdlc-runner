"""Every order says how to answer it (CHG-20260925-01).

Before `reply`, no order said what shape its answer must take, and the shape depends on how the ask
was dispatched: `pm_confirm` asked once reads `yes`/`no`, asked of a panel reads `pass`/`fail`. A
backend answering the way the README said stopped runs. Every order now carries `reply.schema`,
built by `engine._answer_schema` from the reader that will read the answer.

The tests that matter here are the walks. `ReplyAgent` answers from `reply.schema` alone, so a path
that sends the wrong schema — or none — stops the walk, which is the wire being cut (KN-8).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_sdlc_runner import conversations, engine, graph, intake, policy, workorder  # noqa: E402
from test_flow import ALL_GATES, DECISIONS, NOTHING_READ, SPEC  # noqa: E402

#: The one choice `reply.schema` does not make for an agent: which offered word moves the run on.
FORWARD = ("pass", "yes", "low")

FRONTIER = {"next_module": engine.FRONTIER, "feedback": "done"}

PANELS = [n.id for n in graph.NODES if n.mode == graph.MODEL_PANEL]


class ReplyAgent:
    """Answers every order from its `reply.schema`, and from nothing else in the order.

    Two things the schema cannot carry are added, and only these: a preference among the words it
    offers (`FORWARD`), and module ids — which this agent makes up at `pm_plan` and remembers,
    because an order never names a module (KN-5: no prior answer).
    """

    PLANNED = ["alpha", "beta"]

    def __init__(self, override=None):
        self.orders = []
        self.built = []
        self.override = override or (lambda order: None)

    def factory(self, seat=None, model=None):
        agent = self

        class Session(engine.Session):
            def ask(self, order):
                agent.orders.append(order)
                forced = agent.override(order)
                return forced if forced is not None else agent.answer(order["reply"]["schema"])

            def close(self):
                pass
        return Session()

    def answer(self, schema):
        return {key: self._value(key, schema["properties"][key]) for key in schema["required"]}

    def _value(self, key, prop):
        if prop["type"] == "string":
            if "enum" in prop:
                return next((word for word in FORWARD if word in prop["enum"]), prop["enum"][0])
            if key == "module":
                todo = [m for m in self.PLANNED if m not in self.built]
                self.built.extend(todo[:1])
                return todo[0] if todo else ""
            return "text"
        if key == "modules":
            return list(self.PLANNED)
        if "enum" in prop["items"]:
            return []
        return [f"choice {n + 1}" for n in range(prop.get("minItems", 0))]

    def schemas(self, node_id, seat=False):
        return [o["reply"]["schema"] for o in self.orders
                if o["node_id"] == node_id and bool(o.get("seat")) == seat]


def _walk(agent, **kw):
    # Every gate confirmed: the gates are not what these tests are about, and `merge` stops for a
    # person at every grade.
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow", confirmed=ALL_GATES)
    base.update(kw)
    return engine.walk(engine.RunConfig(**base), agent.factory, enabled=True)


# ── an agent that reads only `reply` gets through every path ──────────────────────────────────


def test_an_agent_answering_from_reply_alone_finishes_the_default_flow():
    agent = ReplyAgent()
    report = _walk(agent)
    assert report.state == engine.FINISHED, report.halt_reason
    assert agent.schemas("pm_confirm")[0]["properties"]["verdict"]["enum"] == ["no", "yes"]


def test_it_finishes_under_a_frontier_decision_where_module_and_modules_are_read():
    """The default decisions read `module` only as built-or-not, so this is the walk that cuts the
    `module`, `modules` and `error` wires: omit one and the frontier never closes."""
    agent = ReplyAgent()
    report = _walk(agent, decisions=dict(FRONTIER))
    assert report.state == engine.FINISHED, report.halt_reason
    assert agent.built == ReplyAgent.PLANNED, "every planned module was built, then the loop ended"
    assert agent.schemas("pm_plan")[0]["required"] == ["modules"]
    build = agent.schemas("engineer_build")[0]
    assert build["required"] == ["module"] and "error" in build["properties"], (
        "`error` is offered for a failed build, and never required")


@pytest.mark.parametrize("module", ["", "alpha"], ids=["no module", "a named module"])
@pytest.mark.parametrize("decisions", [DECISIONS, FRONTIER], ids=["a list", "frontier"])
def test_a_build_the_engineer_says_failed_stops_the_run_under_either_decision(decisions, module):
    """`reply` offers `error` for a build that failed, so the run must act on it on both paths and
    whatever `module` says. Measured before: with the decisions a list, `{"module": "", "error":
    ...}` walked to `finished` — 17 asks, nothing said — and a named module with a failure was
    recorded as built on both paths."""
    def fails_to_build(order):
        if order["node_id"] == "engineer_build":
            return {"module": module, "error": "tests fail"}
        return None

    with pytest.raises(engine.EngineError, match="could not build") as caught:
        _walk(ReplyAgent(fails_to_build), decisions=dict(decisions))
    assert "tests fail" in str(caught.value)


def test_it_finishes_with_every_model_panel_node_asked_of_two_models():
    agent = ReplyAgent()
    report = _walk(agent, node_models={node: ["model-a", "model-b"] for node in PANELS})
    assert report.state == engine.FINISHED, report.halt_reason
    assert agent.schemas("lead_assess")[0]["required"] == ["risk"]
    confirm = agent.schemas("pm_confirm")[0]["properties"]["verdict"]
    assert confirm["enum"] == list(policy.VERDICTS), (
        "a panel voice at a yes/no node is asked for the panel's words, not the node's branches")


def test_the_option_ask_answered_from_reply_is_accepted():
    """The escalation is not on a green walk, so it is driven on its own."""
    def survey_says_flow_is_missing(order):
        if order["node_id"] == "intake_review" and order.get("seat"):
            return {"missing": ["flow"], "problems": [], "unsafe": []}
        return None

    agent = ReplyAgent(survey_says_flow_is_missing)
    report = _walk(agent, decisions=dict(FRONTIER),
                   intake_history=[{"missing": ["flow"]}] * intake.ASK_LIMIT)
    assert report.state == engine.SUSPENDED
    assert len(report.suspended["options"]["flow"]) == intake.MIN_OPTIONS
    offered = agent.schemas("intake_review")[-1]["properties"]["options"]
    assert offered["minItems"] == intake.MIN_OPTIONS and offered["uniqueItems"] is True


def test_a_survey_seat_is_asked_for_findings_and_a_review_seat_for_a_verdict():
    agent = ReplyAgent()
    _walk(agent)
    assert agent.schemas("intake_review", seat=True)[0]["required"] == ["missing", "problems",
                                                                         "unsafe"]
    assert agent.schemas("lead_review", seat=True)[0]["required"] == ["verdict"]


def test_an_ask_the_run_reads_nothing_from_says_so():
    agent = ReplyAgent()
    _walk(agent)
    assert agent.schemas("qa_verify")[0]["required"] == []


# ── what `reply` must not carry, and what the seats must share ─────────────────────────────────


def test_no_model_name_and_no_brief_text_reaches_reply():
    """KN-5's instrument: put a sentinel where the dispatcher and the brief keep things, and look
    for it where the order must not carry it. `reply` is built from runner constants and the graph
    only, which is also why the red-line scan may leave it alone."""
    agent = ReplyAgent()
    _walk(agent, node_models={node: ["SENTINEL-MODEL-A", "SENTINEL-MODEL-B"] for node in PANELS},
          instructions=["SENTINEL-INSTRUCTION"], artifacts=["SENTINEL-ATTACHMENT.md"])
    for order in agent.orders:
        assert "SENTINEL-MODEL" not in workorder.to_json(order), order["node_id"]
        shown = json.dumps(order["reply"])
        assert "SENTINEL" not in shown, order["node_id"]
    # And the brief's sentinels did reach the orders, elsewhere — or their absence above proves
    # nothing.
    assert all("SENTINEL-INSTRUCTION" in workorder.to_json(o) for o in agent.orders)
    assert all("SENTINEL-ATTACHMENT" in workorder.to_json(o) for o in agent.orders)


def test_an_unknown_dispatch_path_is_refused_not_read_as_one_voice():
    """`voices` classifies, so it is closed (KN-9): a mistyped path must not fall through to the
    one-voice schema — a panel told a single voice's words is the defect `reply` exists to end."""
    cfg = engine.RunConfig(node_specs={}, decisions=dict(DECISIONS), risk="low")
    with pytest.raises(engine.EngineError, match="not a dispatch path"):
        engine._answer_schema(graph.BY_ID["pm_confirm"], cfg, "model")


def test_the_seats_of_one_node_share_their_reply():
    """A seat's order may differ in `seat` and `instructions`; the answer asked of it may not."""
    agent = ReplyAgent()
    _walk(agent)
    for node in ("intake_review", "lead_review"):
        seated = [o for o in agent.orders if o["node_id"] == node and o.get("seat")]
        assert len(seated) > 1
        rest = [{k: v for k, v in o.items() if k not in ("seat", "instructions")} for o in seated]
        assert all(r == rest[0] for r in rest), node


@pytest.mark.parametrize("schema, says", [
    ({**NOTHING_READ, "properties": {"why": {"type": "string"}}}, "no description"),
    ({**NOTHING_READ, "properties": {"x": {"type": "number", "description": "a count"}}},
     "'string' or 'array'"),
    ({**NOTHING_READ, "properties": {"x": {"type": "string", "enum": [], "description": "d"}}},
     "must list its words"),
    ({**NOTHING_READ, "properties": {"x": {"type": "array", "items": {"type": "object"},
                                           "description": "d"}}}, "`items` must be"),
    ({**NOTHING_READ, "properties": {"x": {"type": "string", "format": "email",
                                           "description": "d"}}}, "outside"),
    ({**NOTHING_READ, "required": ["x"]}, "`required` names"),
    ({**NOTHING_READ, "additionalProperties": True}, "allows no key"),
    ({**NOTHING_READ, "$schema": "draft-07"}, "must have exactly"),
])
def test_a_schema_outside_the_subset_is_refused(schema, says):
    with pytest.raises(workorder.WorkOrderError, match="reply") as caught:
        workorder.render(graph.BY_ID["pr"], SPEC, policy.verdict("pr", "low"), answer_schema=schema)
    assert says in str(caught.value)


# ── resume: a journal written before `reply`, and the runner's own wording ────────────────────


def _journal_walk(tmp_path, agent, resume, **kw):
    journal = engine.AskJournal(tmp_path / "asks")
    try:
        report = _walk(agent, journal=journal, resume=resume, **kw)
    except engine.EngineError as exc:
        return None, journal, exc
    return report, journal, None


def _strip_reply(journal):
    """Rewrite every entry the way this runner wrote it before CHG-20260925-01."""
    for entry in journal.entries():
        entry["order"].pop("reply", None)
        (journal.dir / f"{entry['ask_id']}.json").write_text(json.dumps(entry), encoding="utf-8")


def test_a_journal_written_before_reply_resumes_without_asking_again(tmp_path):
    first, journal, _ = _journal_walk(tmp_path, ReplyAgent(), resume=False)
    _strip_reply(journal)

    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED
    assert again.orders == [], f"re-asked {[o['node_id'] for o in again.orders]}"
    assert len(report.resumed) == len(first.asks)


def test_a_pre_reply_answer_the_walk_refused_is_asked_again(tmp_path):
    """A journal records `answered` before any reader runs, so reusing every reply-less entry would
    replay an answer the walk refused — and an operator upgrading to fix it would stay stuck."""
    def prose_at_confirm(order):
        return {"stdout": "shall I proceed?"} if order["node_id"] == "pm_confirm" else None

    _, journal, exc = _journal_walk(tmp_path, ReplyAgent(prose_at_confirm), resume=False)
    assert isinstance(exc, engine.EngineError), "prose at a decision node stops the walk"
    _strip_reply(journal)

    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED
    asked = [o["node_id"] for o in again.orders]
    assert asked[0] == "pm_confirm", f"the refused answer was reused: {asked}"
    assert not {"intake_review", "pm_plan"} & set(asked), (
        "the answers before it conform, and are reused")


def test_a_changed_schema_is_asked_again_even_when_nothing_else_changed(tmp_path):
    """A frontier decision changes what `pm_plan` is asked for and nothing in its brief, so this is
    the case "always ignore `reply`" would wrongly reuse. The first plan already names modules, so
    the plan's own `accept` would take it: only the comparison can ask it again."""
    def plans_anyway(order):
        return {"modules": list(ReplyAgent.PLANNED)} if order["node_id"] == "pm_plan" else None

    _journal_walk(tmp_path, ReplyAgent(plans_anyway), resume=False)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True, decisions=dict(FRONTIER))
    assert exc is None, exc
    asked = {o["node_id"] for o in again.orders}
    assert "pm_plan" in asked, "asked for `modules` now, and answered before it was asked"
    assert "intake_review" not in asked, "an ask whose schema did not change is reused"


def test_the_runners_own_wording_does_not_ask_again(tmp_path, monkeypatch):
    """The fixed sentences and the descriptions will be tuned; tuning them must not re-ask every
    journaled node — under `serve`, every `engineer_build` again."""
    _journal_walk(tmp_path, ReplyAgent(), resume=False)
    monkeypatch.setattr(workorder, "REPLY_UNATTENDED", "reworded")
    monkeypatch.setattr(workorder, "REPLY_FORMAT", "reworded too")
    monkeypatch.setattr(engine, "WHY", {**engine.WHY, "description": "reworded as well"})

    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and again.orders == []


# ── the conversation still shows what the run acted on ────────────────────────────────────────


@pytest.mark.parametrize("result, starts", [
    ({"missing": ["ui"], "problems": [], "unsafe": [], "why": "no screens named"}, "missing:"),
    ({"options": ["a", "b", "c"], "why": "three ways"}, "options:"),
    ({"module": "alpha", "error": "tests fail"}, "error:"),
    ({"module": "", "error": "tests fail"}, "error:"),
    ({"risk": "high", "why": "touches billing"}, "risk:"),
    ({"why": "nothing is read here"}, "why:"),
])
def test_why_does_not_hide_what_the_run_acted_on(result, starts):
    """Every order now invites `why`; the log line must still lead with the finding."""
    line = conversations._summary({"kind": conversations.ANSWER, "result": result})
    assert line.startswith(starts), line


# ── a failed build stops at its ask, and a resume asks again ──────────────────────────────────


def _fails_to_build(order):
    return {"module": "", "error": "tests fail"} if order["node_id"] == "engineer_build" else None


def test_a_failed_build_stops_at_its_own_ask(tmp_path):
    """"The run stops at this order" is what the `error` description says, so nothing after the
    build is asked — before, `engineer_selfverify` and `lead_task_review` ran first."""
    agent = ReplyAgent(_fails_to_build)
    _, journal, exc = _journal_walk(tmp_path, agent, resume=False)
    assert isinstance(exc, engine.EngineError) and "could not build" in str(exc)
    assert agent.orders[-1]["node_id"] == "engineer_build", [o["node_id"] for o in agent.orders]
    status = {e["node_id"]: e["status"] for e in journal.entries()}
    assert status["engineer_build"] == "refused"


def test_a_resume_after_a_failed_build_asks_the_engineer_again(tmp_path):
    """Journaled `answered`, the failure replayed on every resume and stopped again with nothing
    asked — the only ways out were deleting the file or re-asking everything."""
    _journal_walk(tmp_path, ReplyAgent(_fails_to_build), resume=False)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED
    asked = [o["node_id"] for o in again.orders]
    assert asked[0] == "engineer_build" and "pm_plan" not in asked, asked


def test_a_failure_journaled_answered_by_an_older_runner_is_asked_again(tmp_path):
    """The entry an older runner wrote: `answered`, no `reply`, holding the failure."""
    _, journal, _ = _journal_walk(tmp_path, ReplyAgent(_fails_to_build), resume=False)
    _strip_reply(journal)
    for entry in journal.entries():
        if entry["node_id"] == "engineer_build":
            entry["status"] = "answered"
            (journal.dir / f"{entry['ask_id']}.json").write_text(json.dumps(entry),
                                                                 encoding="utf-8")
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED
    assert [o["node_id"] for o in again.orders][0] == "engineer_build"


def test_nothing_said_after_a_refused_answer_is_reused(tmp_path):
    """The journal an older runner actually wrote: it walked on past a failed build, so the
    self-check, the task review and everything to `merge` were answered about the failed attempt.
    Reusing them after asking the engineer again merged the rebuild on reviews of the failure —
    the verification panel measured it with the pre-change runner writing the journal."""
    def walks_past_a_failure(order):
        if order["node_id"] == "engineer_build":
            return {"module": "alpha"}
        return None

    first, journal, exc = _journal_walk(tmp_path, ReplyAgent(walks_past_a_failure), resume=False)
    assert exc is None and first.state == engine.FINISHED, exc
    _strip_reply(journal)
    later = []
    for entry in journal.entries():
        if entry["node_id"] == "engineer_build":
            entry["result"] = {"module": "", "error": "tests fail"}
            (journal.dir / f"{entry['ask_id']}.json").write_text(json.dumps(entry),
                                                                 encoding="utf-8")
        elif later or any(e["node_id"] == "engineer_build" for e in journal.entries()
                          if e["ask_id"] < entry["ask_id"]):
            later.append(entry["node_id"])
    assert "lead_task_review" in later, later

    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED, exc
    asked = [o["node_id"] for o in again.orders]
    assert asked[0] == "engineer_build", asked
    assert set(later) <= set(asked), (
        f"said about the failed attempt, and reused: {sorted(set(later) - set(asked))}")
    assert "pm_plan" not in asked, "what came before the refused answer is still reused"
    assert len(report.resumed) == len(first.asks) - len(later) - 1, report.resumed


def test_a_changed_question_does_not_stop_the_reuse_after_it(tmp_path):
    """The clear is for an answer refused, not for a question that changed: a frontier decision
    changes what `pm_plan` is asked, and the asks after it that did not change are still reused."""
    _journal_walk(tmp_path, ReplyAgent(), resume=False)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True, decisions=dict(FRONTIER))
    assert exc is None, exc
    assert "pm_confirm" not in {o["node_id"] for o in again.orders}


@pytest.mark.parametrize("error, stops", [
    (True, True), ("tests fail", True), (False, False), ("   ", False), ("", False)])
def test_a_named_module_stops_on_a_true_error_and_not_on_a_blank_one(error, stops):
    """`error: true` is a failure said without a reason — as `_went_wrong` reads it beside an empty
    module — and a blank string is the key left out."""
    said = engine._build_failure({"module": "alpha", "error": error})
    assert bool(said) is stops, said


def test_a_failed_build_keeps_its_why_for_the_person_it_stops_for(tmp_path):
    """A refused answer reaches the conversation only as the stop's message, and a resume's re-ask
    overwrites the journaled one — so the message carries the engineer's `error` and `why` whole."""
    long_error = "tests fail: " + "x" * 300
    agent = ReplyAgent(lambda o: {"module": "", "error": long_error, "why": "the fixture is gone"}
                       if o["node_id"] == "engineer_build" else None)
    _, _, exc = _journal_walk(tmp_path, agent, resume=False)
    assert long_error in str(exc) and "the fixture is gone" in str(exc), str(exc)
    assert "journaled as refused" in str(exc)


def test_a_backstop_does_not_claim_the_journal_was_told():
    """Only the ask's own `accept` journals the answer `refused`; a backstop cannot."""
    said = str(engine._build_failed("module_built", {"module": "", "error": "tests fail"}))
    assert "could not build" in said and "journaled" not in said, said
    said = str(engine._build_failed("module_built", {"errors": ["x"]}))
    assert "answered no module" in said, said


# ── an empty plan under a frontier decision stops at its ask ──────────────────────────────────


def _plans_nothing(order):
    return {"modules": [], "why": "the brief names no work"} if order["node_id"] == "pm_plan" \
        else None


def test_an_empty_plan_under_a_frontier_decision_stops_at_its_own_ask(tmp_path):
    """The `modules` description offers `[]` to a planner that could not plan, so that answer has
    to stop where it is given. Before, `pm_confirm`, `lead_assess` and `pm_signoff` were asked
    first, the stop came at `next_module`, and every resume replayed it with nothing asked."""
    agent = ReplyAgent(_plans_nothing)
    _, journal, exc = _journal_walk(tmp_path, agent, resume=False, decisions=dict(FRONTIER))
    assert isinstance(exc, engine.EngineError) and "names no modules" in str(exc), exc
    assert "the brief names no work" in str(exc)
    assert agent.orders[-1]["node_id"] == "pm_plan", [o["node_id"] for o in agent.orders]
    assert {e["node_id"]: e["status"] for e in journal.entries()}["pm_plan"] == "refused"

    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True, decisions=dict(FRONTIER))
    assert exc is None and report.state == engine.FINISHED, exc
    assert [o["node_id"] for o in again.orders][0] == "pm_plan"


def test_an_empty_plan_journaled_answered_by_an_older_runner_is_asked_again(tmp_path):
    _journal_walk(tmp_path, ReplyAgent(_plans_nothing), resume=False, decisions=dict(FRONTIER))
    for entry in engine.AskJournal(tmp_path / "asks").entries():
        if entry["node_id"] == "pm_plan":
            entry["status"] = "answered"
            entry["result"] = {"modules": []}
            (tmp_path / "asks" / f"{entry['ask_id']}.json").write_text(json.dumps(entry),
                                                                       encoding="utf-8")
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True, decisions=dict(FRONTIER))
    assert exc is None and report.state == engine.FINISHED, exc
    assert [o["node_id"] for o in again.orders][0] == "pm_plan"


def test_a_plan_is_held_to_modules_only_under_a_frontier_decision():
    """With the decisions a list nothing reads `modules`, so nothing stops on it."""
    report = _walk(ReplyAgent(_plans_nothing))
    assert report.state == engine.FINISHED, report.halt_reason


def test_a_later_plan_with_no_list_keeps_the_earlier_one_as_the_reader_does():
    """`_frontier` reads the latest plan that has a `modules` list, so a re-plan without one is not
    refused where an earlier plan gave one — no stricter than the reader."""
    class _Ask:
        def __init__(self, node_id, result):
            self.node_id, self.result = node_id, result

    report = engine.RunReport()
    with pytest.raises(engine.EngineError, match="names no modules"):
        engine._stop_on_empty_plan({"summary": "planned"}, report)
    report.asks = [_Ask("pm_plan", {"modules": ["alpha"]})]
    engine._stop_on_empty_plan({"summary": "planned"}, report)
    with pytest.raises(engine.EngineError, match="an empty `modules` list"):
        engine._stop_on_empty_plan({"modules": []}, report)


def test_a_named_module_beside_an_old_failure_key_is_still_a_build():
    """Only `error` — the key the order offers — stops a named module. A backend that never read
    `reply` and reports `errors: [...]` beside a module it did build was recorded as built before
    this change, and still is."""
    agent = ReplyAgent(lambda o: {"module": "alpha", "errors": ["lint warning"]}
                       if o["node_id"] == "engineer_build" else None)
    report = _walk(agent)
    assert report.state == engine.FINISHED, report.halt_reason


def test_a_journaled_answer_the_walk_refused_is_asked_again_with_reply_too(tmp_path):
    """Not only the entries written before `reply`: any answer a reader refused, at any time."""
    def prose_at_confirm(order):
        return {"stdout": "shall I proceed?"} if order["node_id"] == "pm_confirm" else None

    _, _, exc = _journal_walk(tmp_path, ReplyAgent(prose_at_confirm), resume=False)
    assert isinstance(exc, engine.EngineError)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and report.state == engine.FINISHED
    assert [o["node_id"] for o in again.orders][0] == "pm_confirm"


def test_an_old_journal_in_the_shapes_the_readers_accept_resumes_in_full(tmp_path):
    """Built from the shapes older backends answered with, not from this schema: `branch` for a
    decision, a survey naming one key of three, an engineer's prose. The readers accept all of
    them, so the reuse check must too — stricter would re-ask, under `serve`, the builds this
    rule exists to keep."""
    def old_shapes(order):
        node, seat = order["node_id"], order.get("seat")
        if node == "intake_review" and seat:
            return {"problems": []}
        if seat:
            return {"verdict": "pass"}
        if node in ("pm_confirm", "pm_signoff"):
            return {"branch": "yes"}
        if node in ("lead_task_review", "re_review", "qa_accept"):
            return {"outcome": "pass"}
        if node == "engineer_build":
            return {"summary": "built it"}
        return {"summary": f"{node} done"}

    first, journal, exc = _journal_walk(tmp_path, ReplyAgent(old_shapes), resume=False)
    assert exc is None and first.state == engine.FINISHED, exc
    _strip_reply(journal)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True)
    assert exc is None and again.orders == [], [o["node_id"] for o in again.orders]
    assert len(report.resumed) == len(first.asks)


def test_the_module_built_backstop_stops_on_a_failure_it_is_handed():
    """On the shipped graph the ask stops first; this pins the backstop by calling it directly."""
    class _Ask:
        def __init__(self, node_id, result):
            self.node_id, self.result = node_id, result

    report = engine.RunReport()
    report.asks = [_Ask("engineer_build", {"module": "alpha", "error": "tests fail"})]
    with pytest.raises(engine.EngineError, match="could not build"):
        engine._module_built(report)


def test_no_current_document_describes_the_rejected_draft():
    """The first implementation shipped `reply.schema` while README, SCHEMAS and design.md still
    described the draft the design panel rejected — `reply.keys`, `engine._reads`, `one_of`
    descriptors — which is the first page a backend author reads (CHG-20260925-01). The needles
    are the draft's own spellings, each found in that tree's pages, so the guard fails it. The ledger
    (`docs/changes`, `docs/acceptance`, `docs/design`) keeps its history and is not scanned."""
    root = Path(__file__).resolve().parents[1]
    pages = [root / "README.md", root / "examples" / "minimal" / "agent.py",
             *root.glob("docs/*.md"), *root.glob("docs/structure/*.md"),
             *root.glob("examples/**/*.md")]
    stale = [f"{page.relative_to(root)}: {word}"
             for page in pages
             for word in ("reply.keys", "engine._reads", "*, reads", "`one_of`", "at_least")
             if word in page.read_text(encoding="utf-8")]
    assert stale == [], stale
