"""Tasks 4 and 5 — the mode finally does something at run time.

Task 12 put the execution mode in `graph.Node` and made `graph.validate()` enforce it, and the engine
read it in exactly one place: whether a node is the seat panel. So a node declared `model_panel` with
three models configured was still **asked once**. The field was authoritative in the data and inert
in the walk — half of the decorative-data failure an independent seat predicted, arrived on schedule.

These two tasks close it, and the pair belongs in one file because the whole point of the mode is the
difference between them:

* **`model_panel`** — N models, **one question**, N sessions, adjudicated. A vote.
* **`pool`** — N models, **one piece of work**, one session. A dispatch.

Same three model ids in `node_models`; entirely different runs. If either behaved like the other the
record would be describing something that did not happen — which is the objection that produced the
mode in the first place.
"""
import pytest

from ai_sdlc_runner import engine, graph, policy
from test_flow import DECISIONS, SPEC


def _run(node_models=None, answers=None, **cfg_kw):
    """Walk with a factory that routes by model, so who answered is observable."""
    answers = answers or {}
    asked = []

    def factory(seat=None, model=None):
        class Session(engine.Session):
            def ask(self, order):
                asked.append((order["node_id"], seat, model))
                if seat:
                    return {"verdict": "pass"}
                key = (order["node_id"], model)
                if key in answers:
                    return {"verdict": answers[key]}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return Session()

    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow",
                node_models=node_models or {})
    base.update(cfg_kw)
    report = engine.walk(engine.RunConfig(**base), factory, enabled=True)
    return report, asked


# --- task 4: a panel is N sessions on one question --------------------------------------------

def test_a_model_panel_opens_one_session_per_model():
    report, asked = _run(node_models={"lead_task_review": ["opus", "codex", "gemini"]})
    at_node = [a for a in asked if a[0] == "lead_task_review"]
    assert len(at_node) == 3
    assert sorted(a[2] for a in at_node) == ["codex", "gemini", "opus"]


def test_each_voice_is_recorded_with_the_model_that_gave_it():
    """A record that cannot say which model said what has kept the votes and lost the panel."""
    report, _ = _run(node_models={"lead_task_review": ["opus", "codex"]})
    voices = [a for a in report.asks if a.node_id == "lead_task_review"]
    assert sorted(v.model for v in voices) == ["codex", "opus"]


def test_the_panel_is_adjudicated_by_the_model_rule():
    report, _ = _run(node_models={"lead_task_review": ["opus", "codex", "gemini"]},
                     answers={("lead_task_review", "codex"): "fail"})
    adj = [a for a in report.adjudications if a["node_id"] == "lead_task_review"][-1]
    assert adj["outcome"] == policy.PASS
    assert adj["verdicts"] == {"opus": "pass", "codex": "fail", "gemini": "pass"}
    assert adj["vetoed"] == [], "no model voice vetoes — see task 20"


def test_a_model_panel_that_ties_suspends_for_a_person():
    """The three tasks meeting: a tie (2) reaches a person (13) through a suspension (1)."""
    report, _ = _run(node_models={"lead_task_review": ["opus", "codex"]},
                     answers={("lead_task_review", "codex"): "fail"})
    assert report.state == engine.SUSPENDED
    assert report.halted_at == "lead_task_review"
    assert report.suspended["undecided"] is True
    assert report.suspended["verdicts"] == {"opus": "pass", "codex": "fail"}


def test_a_person_can_break_a_model_panels_tie():
    report, _ = _run(node_models={"lead_task_review": ["opus", "codex"]},
                     answers={("lead_task_review", "codex"): "fail"},
                     rulings=[engine.Ruling(node_id="lead_task_review", branch="pass")])
    assert any("a person chose 'pass'" in r for r in report.rulings)


def test_one_configured_model_is_still_one_ask():
    """The mode says how to read the list, not how long it is — a panel of one is one voice."""
    report, asked = _run(node_models={"lead_task_review": ["opus"]})
    assert len([a for a in asked if a[0] == "lead_task_review"]) == 1


def test_a_node_with_no_models_configured_is_asked_once():
    report, asked = _run()
    assert len([a for a in asked if a[0] == "lead_task_review"]) == 1


# --- task 5: a pool is one session, and says where it went ------------------------------------

def test_a_pool_asks_exactly_one_model():
    """The correction the user made: several models on a build is a dispatch, not a vote."""
    report, asked = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    builds = [a for a in asked if a[0] == "engineer_build"]
    assert len(builds) == 1
    assert builds[0][2] in ("opus", "codex", "gemini")


def test_a_pool_records_where_it_dispatched():
    """"At random" is only acceptable if the choice is afterwards visible.

    An unrecorded random dispatch is indistinguishable from a preference nobody declared.
    """
    report, _ = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    line = [d for d in report.dispatches if d.startswith("engineer_build")]
    assert line and "dispatched to" in line[0]
    assert "chosen at random" in line[0]
    assert "lead" in line[0], "the main that dispatched should be named"


def test_the_pool_does_not_adjudicate():
    report, _ = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    assert not [a for a in report.adjudications if a["node_id"] == "engineer_build"]


def test_the_dispatch_is_reproducible():
    """Arbitrary with respect to the work, not with respect to the record.

    A resumed run has to reach the same engineer, and "which model built this" has to stay
    answerable after the fact.
    """
    first, _ = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    second, _ = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    assert first.dispatches == second.dispatches


def test_a_different_seed_can_dispatch_differently():
    """Reproducible is not fixed: the seed is what makes it repeatable, not a hidden ranking."""
    seen = set()
    for seed in range(12):
        report, _ = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]},
                         dispatch_seed=seed)
        seen.add(report.dispatches[0].split("dispatched to ")[1].split(" ")[0])
    assert len(seen) > 1, "every seed picked the same model — that is a ranking, not a dispatch"


# --- task 5: follows reuses the builder --------------------------------------------------------

def test_selfverify_follows_the_model_that_built_it():
    """"Its own work" is the whole reason that node exists; a different model is a second opinion."""
    report, asked = _run(node_models={"engineer_build": ["opus", "codex", "gemini"]})
    built = [a for a in asked if a[0] == "engineer_build"][0][2]
    verified = [a for a in asked if a[0] == "engineer_selfverify"][0][2]
    assert verified == built
    assert any("follows engineer_build" in d for d in report.dispatches)


def test_a_follows_with_nothing_to_follow_asks_the_default():
    """No models configured on the build means nothing to follow, and that is not an error."""
    report, asked = _run()
    verified = [a for a in asked if a[0] == "engineer_selfverify"]
    assert len(verified) == 1
    assert verified[0][2] is None


# --- the refusal an independent seat asked for -------------------------------------------------

def test_a_panel_that_collects_fewer_verdicts_than_configured_is_refused():
    """Three configured, fewer answered, and nothing saying so — the silent-one-ask failure.

    Two models answering under one name is not a panel; it is one voice counted twice. Driven by
    configuring a duplicate, which is the shape that would otherwise collapse three into two.
    """
    with pytest.raises(engine.EngineError, match="short of a voice"):
        _run(node_models={"lead_task_review": ["opus", "opus", "codex"]})


def test_the_mode_and_not_the_node_name_decides():
    """`qa_verify` is `single`. Three models there is a configuration error, not a panel.

    Keyed off the declared mode, so renaming a node changes nothing — which is the property task 12
    was built for and this is the first task that could demonstrate it.
    """
    assert graph.BY_ID["qa_verify"].mode == graph.SINGLE
    report, asked = _run(node_models={"qa_verify": ["opus", "codex", "gemini"]})
    assert len([a for a in asked if a[0] == "qa_verify"]) == 1
    assert not [a for a in report.adjudications if a["node_id"] == "qa_verify"]
