"""The seats read the requirement before anybody builds against it.

Two things make this different from every other multi-voice node in the runner, and both are the
point rather than a shortcut:

**It is a union, not a vote.** Everywhere else several voices are adjudicated — veto, majority, tie.
Here they are collected, and a problem one seat raised is kept whether or not the other three agree.
Adjudication answers *"may this proceed?"*, which has one answer. Intake answers *"what is wrong with
this?"*, which has as many answers as there are things wrong — and counting them **destroys** the
information. Outvoting a problem would be the panel agreeing not to know something.

**Asking again has a limit.** Three times, then the runner stops asking and puts at least three
options on the table. Not because three is magic, but because a third unanswered ask is evidence
about the question rather than about the person — and at that point continuing to ask is a way of
not deciding while looking diligent.
"""
import pytest

from ai_sdlc_runner import engine, graph, intake, policy
from test_flow import SPEC


# --- the union --------------------------------------------------------------------------------

def test_every_problem_is_kept_even_if_only_one_seat_raised_it():
    """The rule that makes this a survey. A problem three seats missed is still a problem."""
    survey = intake.collect({
        "conformance": {"problems": ["the acceptance test is not stated"]},
        "defect": {"problems": []},
        "risk": {"problems": []},
        "idiom": {"problems": []},
    })
    assert survey.all_problems() == ["conformance: the acceptance test is not stated"]


def test_problems_stay_attributed():
    """"Who saw this" is most of what makes a problem actionable; a flat list loses it."""
    survey = intake.collect({
        "risk": {"problems": ["no rollback is described"]},
        "defect": {"problems": ["the error case is not covered"]},
    })
    assert survey.problems["risk"] == ["no rollback is described"]
    assert survey.problems["defect"] == ["the error case is not covered"]


def test_nothing_is_adjudicated():
    """No veto, no majority, no tie. Three seats disagreeing is three findings, not a vote."""
    survey = intake.collect({
        "conformance": {"missing": ["ui"]},
        "defect": {"missing": []},
        "risk": {"missing": []},
    })
    assert survey.missing == ["ui"], "one seat noticing is enough"
    assert not hasattr(survey, "outcome")


def test_missing_aspects_are_unioned_and_ordered():
    survey = intake.collect({
        "a": {"missing": ["outputs", "flow"]},
        "b": {"missing": ["flow", "ui"]},
    })
    assert survey.missing == ["flow", "outputs", "ui"], "stable, readable order"


def test_safety_is_kept_apart_from_ordinary_problems():
    """"This is dangerous" and "this is underspecified" want different responses from a person."""
    survey = intake.collect({"risk": {"problems": ["vague"], "unsafe": ["it deletes user data"]}})
    assert survey.safety["risk"] == ["it deletes user data"]
    assert "it deletes user data" not in survey.problems.get("risk", [])


def test_an_aspect_this_runner_does_not_ask_about_is_an_error():
    """Dropping it would lose a real observation while looking like agreement."""
    with pytest.raises(intake.IntakeError, match="not one of the aspects"):
        intake.collect({"defect": {"missing": ["database"]}})


def test_a_complete_requirement_says_so():
    survey = intake.collect({"a": {"problems": ["a nit"]}, "b": {}})
    assert survey.complete, "problems do not make a requirement incomplete — missing aspects do"


# --- the six aspects ----------------------------------------------------------------------------

def test_the_aspect_list_is_closed_and_covers_what_was_asked_for():
    """flow, architecture, requirements, inputs, outputs, UI — the six the user named."""
    assert intake.ASPECT_IDS == ("flow", "architecture", "requirements", "inputs", "outputs", "ui")
    for aspect in intake.ASPECT_IDS:
        assert intake.BY_ASPECT[aspect], f"{aspect} needs a description a person can read"


# --- asking, and stopping asking ------------------------------------------------------------------

def test_asking_is_counted_per_aspect():
    history = [{"missing": ["ui", "flow"]}, {"missing": ["ui"]}]
    assert intake.times_asked(history, "ui") == 2
    assert intake.times_asked(history, "flow") == 1
    assert intake.times_asked(history, "inputs") == 0


def test_options_are_offered_only_after_the_third_time():
    """`>=` and not `>`: the third unanswered ask is the one that has failed, not the fourth."""
    history = []
    assert not intake.needs_options(history, "ui")
    history = [{"missing": ["ui"]}, {"missing": ["ui"]}]
    assert not intake.needs_options(history, "ui")
    history.append({"missing": ["ui"]})
    assert intake.needs_options(history, "ui")


def test_the_option_request_asks_a_model_and_does_not_answer_itself():
    """A runner that quietly authors requirements has stopped being a runner."""
    request = intake.option_request("ui", ["build the thing"])
    assert request["minimum"] == intake.MIN_OPTIONS >= 3
    assert "Do not pick one" in request["question"]
    assert intake.BY_ASPECT["ui"] in request["question"]


def test_fewer_than_three_options_is_refused():
    """Two is a false choice and one is a decision wearing a question mark."""
    with pytest.raises(intake.IntakeError, match="false choice"):
        intake.read_options({"options": ["a", "b"]}, "ui")


def test_three_options_are_accepted():
    assert intake.read_options({"options": ["a", "b", "c"]}, "ui") == ["a", "b", "c"]


def test_the_stop_reason_says_what_is_missing_and_how_often_it_was_asked():
    survey = intake.collect({"a": {"missing": ["ui"]}})
    reason = intake.stop_reason(survey, [{"missing": ["ui"]}])
    assert "asked twice" in reason
    assert intake.BY_ASPECT["ui"] in reason
    assert "Nothing has been planned or built" in reason


# --- the node, and the walk -----------------------------------------------------------------------

def test_the_survey_node_is_first_and_asks_the_seats():
    node = graph.BY_ID["intake_review"]
    assert node.mode == graph.SURVEY
    assert node.role == "seat"
    assert graph.BY_ID["intake"].next == "intake_review"
    assert node.next == "pm_plan", "nothing is planned before the requirement has been read"


def test_the_survey_node_has_no_gate():
    """What stops a run here is the requirement being incomplete, not a risk grade.

    A gate that fires on a *complete* requirement would be asking a person to approve the absence of
    a problem, and one that never fires is decoration — which `policy.py` says in as many words.
    """
    assert graph.BY_ID["intake_review"].gate is None


def _walk(seat_answers, **cfg_kw):
    def dispatch(order):
        if order["node_id"] == "intake_review":
            if order.get("seat"):
                return dict(seat_answers.get(order["seat"], {}))
            return {"options": ["one", "two", "three"]}      # the option ask
        if order.get("seat"):
            return {"verdict": "pass"}
        if order["node_id"] == "pm_plan":
            return {"modules": ["m"]}
        if order["node_id"] == "engineer_build":
            return {"module": "m"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": engine.FRONTIER, "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(cfg_kw)
    return engine.walk(engine.RunConfig(**base), dispatch, enabled=True)


def test_an_incomplete_requirement_stops_before_anything_is_planned():
    report = _walk({"conformance": {"missing": ["ui", "inputs"],
                                    "problems": ["no screen is described"]}})
    assert report.state == engine.SUSPENDED
    assert report.halted_at == "intake_review"
    assert report.suspended["incomplete"] is True
    assert report.suspended["missing"] == ["inputs", "ui"]
    assert "pm_plan" not in report.visited, "nothing was planned"


def test_the_stop_carries_every_problem_the_seats_raised():
    report = _walk({"conformance": {"missing": ["ui"], "problems": ["no screen"]},
                    "defect": {"problems": ["the error case is unstated"]}})
    problems = report.suspended["problems"]
    assert any("no screen" in p for p in problems)
    assert any("error case" in p for p in problems), "a second seat's problem is kept too"


def test_a_complete_requirement_lets_the_run_continue():
    report = _walk({"conformance": {"problems": ["a nit, but nothing is missing"]}})
    assert "pm_plan" in report.visited
    assert report.survey["complete"] is True
    assert report.survey["problems"]["conformance"] == ["a nit, but nothing is missing"]


def test_after_three_asks_the_stop_carries_options():
    """The escalation. Asking again is right; asking forever is not."""
    history = [{"missing": ["ui"]}, {"missing": ["ui"]}, {"missing": ["ui"]}]
    report = _walk({"conformance": {"missing": ["ui"]}}, intake_history=history)
    assert report.suspended["options"]["ui"] == ["one", "two", "three"]
    assert len(report.options["ui"]) >= intake.MIN_OPTIONS


def test_before_three_asks_there_are_no_options_only_the_question():
    report = _walk({"conformance": {"missing": ["ui"]}},
                   intake_history=[{"missing": ["ui"]}])
    assert not report.suspended["options"], "it is still worth asking"
    assert "asked twice" in report.halt_reason


def test_a_survey_reaches_no_verdict():
    """No adjudication is recorded for the survey node, because none is reached."""
    report = _walk({"conformance": {"problems": ["a nit"]}})
    assert not [a for a in report.adjudications if a["node_id"] == "intake_review"]
