"""Tasks 6, 7 and 18 — the send-back, the retry, and the refusal.

Three small tasks with one thing in common: each is a place where the runner could quietly decide
something on a person's behalf, and each is written so it cannot.

* **6** — a summary is where an objection gets softened, so the originals travel with it.
* **7** — a retry is for a backend that *failed to answer*, never for an answer somebody dislikes.
* **18** — a refusal goes where the graph says, and a gate with nowhere to send one cannot be refused.
"""
import subprocess

import pytest

from ai_sdlc_runner import cli, engine, graph, policy
from test_flow import DECISIONS, SPEC


def _walk(dispatch, **cfg_kw):
    # `next_module` is decided from the frontier rather than a fixed list: a failed panel routes
    # back into the module loop, so how many times it is reached depends on what fails — which is
    # exactly the thing a written-in-advance sequence cannot know.
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": engine.FRONTIER, "feedback": "done"},
                risk="low", undeclared="allow")
    base.update(cfg_kw)
    return engine.walk(engine.RunConfig(**base), dispatch, enabled=True)


def _seats(verdicts):
    """Seats that object **once** and then pass, the way a real rework goes.

    Not a convenience. A panel that fails forever loops forever — `lead_review` fails to
    `review_failed`, which returns to `next_module`, which finds nothing left and goes straight back
    to `lead_review`. `max_steps` catches it, but the flow's own docstring promises *"one fix pass,
    one re-review, and a second failure halts. Not repeat-until-green"* — and that bound exists at
    the module level and **not** around the seat panel. Recorded as an open question rather than
    papered over here; this fixture just declines to depend on it.
    """
    rounds = {"n": 0}

    def dispatch(order):
        if order.get("seat"):
            # `intake_review` is a seat node too, and it is a SURVEY — it wants problems and
            # missing aspects, not a verdict. Counting its asks towards the review panel's rounds
            # had the panel pass before it was ever asked to object.
            if order["node_id"] == "intake_review":
                return {"problems": [], "missing": [], "unsafe": []}
            rounds[order["seat"]] = rounds.get(order["seat"], 0) + 1
            if rounds[order["seat"]] > 1:
                return {"verdict": "pass"}       # the rework landed
            return {"verdict": verdicts.get(order["seat"], "pass")}
        if order["node_id"] == "pm_plan":
            return {"modules": ["only-one"]}
        if order["node_id"] == "engineer_build":
            return {"module": "only-one"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}
    return dispatch


# --- task 6: the brief leads, the originals are appended --------------------------------------

def test_a_failed_panel_records_a_brief_and_the_originals():
    names = policy.seat_names(3)
    report = _walk(_seats({names[0]: "fail", names[1]: "fail"}),
                   review_seats=3, high_risk_mode=True)
    back = [b for b in report.send_backs if b["node_id"] == "lead_review"]
    assert back, "a panel that did not pass should have said what the rework is for"
    entry = back[-1]
    assert entry["brief"].startswith("lead_review did not pass")
    assert entry["appendix_is"] == "reference, not instruction"


def test_the_appendix_carries_every_voice_not_only_the_objections():
    """Both sides, for the reason the user gave: only the objections is a thumb on the scale."""
    names = policy.seat_names(3)
    report = _walk(_seats({names[0]: "fail", names[1]: "fail"}),
                   review_seats=3, high_risk_mode=True)
    entry = [b for b in report.send_backs if b["node_id"] == "lead_review"][-1]
    voices = {row["voice"]: row["verdict"] for row in entry["appendix"]}
    assert len(voices) == 3
    assert sorted(v for v in voices.values() if v == "fail")
    assert sorted(v for v in voices.values() if v == "pass"), "the ones who passed are here too"


def test_the_brief_names_who_objected():
    """"Somebody objected" is not something a rework can act on."""
    names = policy.seat_names(3)
    report = _walk(_seats({names[0]: "fail", names[1]: "fail"}),
                   review_seats=3, high_risk_mode=True)
    entry = [b for b in report.send_backs if b["node_id"] == "lead_review"][-1]
    assert names[0] in entry["brief"] and names[1] in entry["brief"]


def test_a_panel_that_passes_sends_nothing_back():
    report = _walk(_seats({}), review_seats=3, high_risk_mode=True)
    assert not [b for b in report.send_backs if b["node_id"] == "lead_review"]


def test_the_send_back_survives_serialisation():
    names = policy.seat_names(3)
    report = _walk(_seats({names[0]: "fail", names[1]: "fail"}),
                   review_seats=3, high_risk_mode=True)
    assert report.as_dict()["send_backs"] == report.send_backs


# --- task 7: retries are the dispatcher's, and only for a failure to answer --------------------

def test_a_backend_that_fails_once_is_retried(monkeypatch):
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return subprocess.CompletedProcess(argv, 1, "", "it fell over")
        return subprocess.CompletedProcess(argv, 0, '{"verdict": "pass"}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = cli._Process(["agent"], timeout=5, retries=2)
    assert session.ask({"node_id": "x", "role": "lead"})["verdict"] == "pass"
    assert calls["n"] == 2


def test_every_failed_attempt_is_recorded(monkeypatch):
    """A run that took four tries must not read like one that took one."""
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return subprocess.CompletedProcess(argv, 1, "", "nope")
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = cli._Process(["agent"], timeout=5, retries=3)
    session.ask({"node_id": "build", "role": "engineer"})
    assert len(session.attempts) == 2
    assert all("build" in line and "retrying" in line for line in session.attempts)


def test_exhausted_retries_give_up_and_say_so(monkeypatch):
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "always"))
    session = cli._Process(["agent"], timeout=5, retries=2)
    with pytest.raises(cli.CliError, match="failed 3 time"):
        session.ask({"node_id": "x", "role": "lead"})


def test_a_timeout_is_retried_too(monkeypatch):
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise subprocess.TimeoutExpired(argv, 5)
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = cli._Process(["agent"], timeout=5, retries=1)
    session.ask({"node_id": "x", "role": "lead"})
    assert calls["n"] == 2


def test_a_verdict_is_never_retried(monkeypatch):
    """The one that matters. Retrying a `fail` until it comes back `pass` is shopping for a verdict.

    The retry loop sits above the parse and below the routing, so it never sees a verdict at all —
    which is why this test can only be written by checking the backend was called once.
    """
    calls = {"n": 0}

    def fake_run(argv, **kw):
        calls["n"] += 1
        return subprocess.CompletedProcess(argv, 0, '{"verdict": "fail"}', "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = cli._Process(["agent"], timeout=5, retries=5)
    assert session.ask({"node_id": "x", "role": "lead"})["verdict"] == "fail"
    assert calls["n"] == 1, "a disliked answer was retried — that is not a retry"


def test_retries_are_off_unless_configured():
    factory = cli.session_factory({"agent_command": ["x"]})
    assert factory().retries == 0
    louder = cli.session_factory({"agent_command": ["x"], "agent_retries": 3})
    assert louder().retries == 3


# --- task 18: a refusal goes where the graph says ----------------------------------------------

def test_every_gate_either_has_a_rejection_target_or_cannot_be_rejected():
    for node in graph.NODES:
        if node.rejects_to is not None:
            assert node.gate, f"{node.id} routes a rejection but has no gate"
            assert node.rejects_to in graph.BY_ID


def test_the_targets_are_the_ones_that_can_act_on_a_refusal():
    """Not one universal target: `pm_plan` is right for a plan, wrong for a failed QA run."""
    assert graph.BY_ID["pm_confirm"].rejects_to == "pm_plan"
    assert graph.BY_ID["qa_verify"].rejects_to == "next_module"
    assert graph.BY_ID["lead_review"].rejects_to == "review_failed"


def test_merge_and_pr_cannot_be_rejected():
    """Rejecting `merge` means *do not merge*, and there is no node for that.

    Inventing one would be pretending a refusal is a step. Leaving the run stopped is the refusal.
    """
    assert graph.BY_ID["merge"].rejects_to is None
    assert graph.BY_ID["pr"].rejects_to is None


def test_rejecting_a_gate_sends_the_run_to_the_declared_node():
    seen = []

    def dispatch(order):
        seen.append(order["node_id"])
        if order.get("seat"):
            return {"verdict": "pass"}
        if order["node_id"] == "pm_plan":
            return {"modules": ["only-one"]}
        if order["node_id"] == "engineer_build":
            return {"module": "only-one"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    report = _walk(dispatch, risk="medium",
                   rejections=(engine.Rejection(gate="plan_confirmed", node_id="pm_confirm",
                                                reason="the scope is wrong"),))
    assert report.rejections, "the refusal should be recorded"
    assert "the scope is wrong" in report.rejections[0]
    assert "goes to pm_plan" in report.rejections[0]
    assert seen.count("pm_plan") >= 2, "the run should have gone back to the PM"


def test_rejecting_a_gate_that_cannot_be_rejected_is_refused():
    with pytest.raises(engine.EngineError, match="nowhere to send a refusal"):
        _walk(_seats({}), rejections=(engine.Rejection(gate="merge", node_id="merge"),))


def test_a_rejection_naming_the_wrong_gate_for_its_node_is_refused():
    with pytest.raises(engine.EngineError, match="has gate"):
        _walk(_seats({}),
              rejections=(engine.Rejection(gate="merge", node_id="pm_confirm"),))


def test_a_rejection_from_another_run_is_refused(tmp_path):
    journal = engine.AskJournal(tmp_path / "asks")
    with pytest.raises(engine.EngineError, match="another run"):
        _walk(_seats({}), journal=journal,
              rejections=(engine.Rejection(gate="plan_confirmed", node_id="pm_confirm",
                                           run_id="/elsewhere"),))


def test_a_rejection_is_spent_once():
    """Otherwise a single refusal would bounce the run round the loop forever."""
    def dispatch(order):
        if order.get("seat"):
            return {"verdict": "pass"}
        if order["node_id"] == "pm_plan":
            return {"modules": ["only-one"]}
        if order["node_id"] == "engineer_build":
            return {"module": "only-one"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    report = _walk(dispatch, risk="medium",
                   rejections=(engine.Rejection(gate="plan_confirmed", node_id="pm_confirm"),),
                   confirmed=("plan_confirmed", "feasibility_confirmed", "before_dispatch",
                              "merge"))
    assert len(report.rejections) == 1


def test_the_rework_brief_reaches_the_node_it_was_written_for():
    """`_send_back` calls its `brief` "the instruction". Nothing delivered it.

    It was appended to `report.send_backs`, serialised into the report and the server snapshot, and
    asserted by the tests above — and read by **no work order**. So a panel that did not pass sent
    the run back to a node that was asked its original question again, and answered it the same
    way. Measured before the fix: the two orders `pm_plan` received across a `fail` compared equal.

    That is the same non-convergence CHG-20260901-12 closed for a *person's* rejection. There are
    two paths back into the flow — a person refusing a gate, and a panel not passing a node — and
    only one of them carried its reason (CHG-20260901-13, design conformance seat).
    """
    orders = []

    def factory(seat=None, model=None):
        class Session(engine.Session):
            def ask(self, order):
                if order["node_id"] == "pm_plan":
                    orders.append(order)
                if order["node_id"] == "pm_confirm":
                    # Two voices, both against: the panel adjudicates `fail` and routes to `no`.
                    return {"verdict": "fail"} if len(orders) < 2 else {"verdict": "pass"}
                branch = {"pm_signoff": "yes", "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return Session()

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions=dict(DECISIONS), risk="low", undeclared="allow",
        node_models={"pm_confirm": ["opus", "codex"]},
        confirmed=["merge"])
    try:
        engine.walk(cfg, factory, enabled=True)
    except engine.EngineError:
        pass          # the extra lap outruns the fixture's loop decisions; the orders are collected

    assert len(orders) >= 2, "the panel's `fail` did not send the run back to pm_plan"
    assert "did not pass" not in str(orders[0].get("instructions")), (
        "the first order cannot know about a verdict nobody has reached yet")
    second = str(orders[1].get("instructions"))
    assert "did not pass" in second, (
        "the node the panel sent the run back to was not told why — it will produce the same plan "
        "and be failed again, which is the loop this test exists to close")
    assert "A person refused" not in second, (
        "a panel is not a person; saying so tells a model something untrue about who objected")
