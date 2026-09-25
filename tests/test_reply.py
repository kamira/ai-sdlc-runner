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
    assert confirm["enum"] == list(policy.VERDICTS)
    assert "`pass` is this node's `yes`" in confirm["description"], (
        "a panel voice is told what its word means at a node whose branches are yes/no")


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
    """A frontier decision changes what `pm_plan` and `engineer_build` are asked for and nothing in
    their briefs, so this is the case "always ignore `reply`" would wrongly reuse."""
    _journal_walk(tmp_path, ReplyAgent(), resume=False)
    again = ReplyAgent()
    report, _, exc = _journal_walk(tmp_path, again, resume=True, decisions=dict(FRONTIER))
    assert exc is None, exc
    asked = {o["node_id"] for o in again.orders}
    assert {"pm_plan", "engineer_build"} <= asked
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
    ({"why": "nothing is read here"}, "why:"),
])
def test_why_does_not_hide_what_the_run_acted_on(result, starts):
    """Every order now invites `why`; the log line must still lead with the finding."""
    line = conversations._summary({"kind": conversations.ANSWER, "result": result})
    assert line.startswith(starts), line
