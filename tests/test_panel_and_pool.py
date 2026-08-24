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


# --- task 3: an undecided panel may be given another round --------------------------------------

def _tie_run(reruns, resolve_on=None, **kw):
    """A two-model panel that ties, and optionally stops tying on a later round."""
    rounds = {"n": 0}

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                if seat:
                    return {"verdict": "pass"}
                if order["node_id"] == "lead_task_review":
                    rounds["n"] += 1
                    this_round = (rounds["n"] + 1) // 2      # two voices per round
                    if resolve_on and this_round >= resolve_on:
                        return {"verdict": "pass"}
                    return {"verdict": "fail" if model == "codex" else "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions=dict(DECISIONS), risk="low", undeclared="allow",
                node_models={"lead_task_review": ["opus", "codex"]}, panel_reruns=reruns)
    base.update(kw)
    return engine.walk(engine.RunConfig(**base), factory, enabled=True)


def test_with_no_reruns_a_tie_goes_straight_to_a_person():
    """The honest default. A re-run trades independence for information; nobody pays that by accident."""
    report = _tie_run(reruns=0)
    assert report.state == engine.SUSPENDED
    assert report.suspended["undecided"] is True
    assert not report.panel_rounds


def test_a_tie_can_be_put_to_the_panel_again():
    report = _tie_run(reruns=2, resolve_on=2)
    assert report.panel_rounds, "the extra round should be recorded"
    assert report.panel_rounds[0]["node_id"] == "lead_task_review"
    # Round two resolved it, so the panel is no longer what the run is waiting for.
    assert not (report.suspended or {}).get("undecided")


def test_the_extra_round_carries_both_sides_attributed():
    """Only the objections would be a thumb on the scale — half the room's reasoning."""
    report = _tie_run(reruns=1)
    carried = report.panel_rounds[0]["carried"]
    verdicts = {row["voice"]: row["verdict"] for row in carried}
    assert verdicts == {"opus": "pass", "codex": "fail"}, "both sides, named"


def test_the_carried_round_reaches_the_work_order():
    """Recording it is not the same as sending it. This checks the voices were actually told."""
    told = []

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                if order["node_id"] == "lead_task_review":
                    got = order["instructions"]
                    told.append(got if isinstance(got, str) else " ".join(got))
                    return {"verdict": "fail" if model == "codex" else "pass"}
                if seat:
                    return {"verdict": "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    engine.walk(engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions=dict(DECISIONS), risk="low", undeclared="allow",
        node_models={"lead_task_review": ["opus", "codex"]}, panel_reruns=1),
        factory, enabled=True)

    later = [t for t in told if "last round" in t]
    assert later, "round two was not told what round one said"
    assert "codex said fail" in later[0]
    assert "opus said pass" in later[0], "the voice that passed is carried too"
    assert "you have not seen what the others say this round" in later[0]


def test_the_limit_still_ends_at_a_person():
    """If they have read each other and still cannot agree, another round will not help."""
    report = _tie_run(reruns=2)
    assert len(report.panel_rounds) == 2, "exactly the allowed number of extra rounds"
    assert report.state == engine.SUSPENDED
    assert report.suspended["undecided"] is True


def test_the_seats_are_never_re_run():
    """Each seat answers a different question, so carrying their reasons across is contamination.

    Driven rather than grepped: a four-seat panel is made to tie with `panel_reruns` set high, and
    nothing extra may happen. Their independence is not the user's to set.
    """
    names = policy.seat_names(4)
    failing = {names[0], names[1]}
    # Objecting once and then passing, because a seat panel that fails forever loops forever —
    # `lead_review` returns to the module loop, which comes straight back. That gap is recorded in
    # the change record's "What is not settled"; this test declines to depend on it.
    rounds = {}

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                if seat:
                    rounds[seat] = rounds.get(seat, 0) + 1
                    if rounds[seat] > 1:
                        return {"verdict": "pass"}
                    return {"verdict": "fail" if seat in failing else "pass"}
                if order["node_id"] == "pm_plan":
                    return {"modules": ["only-one"]}
                if order["node_id"] == "engineer_build":
                    return {"module": "only-one"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    report = engine.walk(engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": engine.FRONTIER, "feedback": "done"},
        risk="low", undeclared="allow", review_seats=4, high_risk_mode=True,
        panel_reruns=5), factory, enabled=True)

    assert not [r for r in report.panel_rounds if r["node_id"] == "lead_review"],         "the seats were given another round; their independence is not configurable"
