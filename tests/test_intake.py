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
import pathlib

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


@pytest.mark.parametrize("answer,where", [
    ({"problems": True}, "'problems'"),
    ({"missing": True}, "'missing'"),
    ({"unsafe": {"issue": "rm -rf /"}}, "'unsafe'"),
    ({"problems": [True]}, "'problems'[0]"),
    ({"unsafe": [{"issue": "rm -rf /"}]}, "'unsafe'[0]"),
    ({"missing": ["ui", 3]}, "'missing'[1]"),
])
def test_a_value_that_is_not_text_is_refused_and_says_where(answer, where):
    """**One rule, both branches.** The scalar fallback and the list read the same question — is
    this item text — and repairing only one is what left this open for fifteen days:
    `CHG-20260903-36` swept the fallback, and the list beside it went on reading
    `{'issue': ...}` as a finding. A list is the shape `docs/SCHEMAS.md` documents, so it is the
    branch that mattered.

    The message names the seat, the key and the index, because `collect` aggregates four seats and
    "something was not text" is not actionable.
    """
    with pytest.raises(intake.IntakeError, match="which is not text") as caught:
        intake.collect({"risk": answer})
    said = str(caught.value)
    assert "seat 'risk'" in said and where in said, said


def test_dropping_it_instead_would_walk_a_safety_finding_to_merge():
    """Why refusing rather than dropping, measured rather than argued.

    Three seats answering `{"unsafe": [{"issue": "rm -rf /"}]}`, on `aea1398`:

        today                       stops at intake_review; a person is asked to decide about
                                    `unsafe: risk: {'issue': 'rm -rf /'}`, and `--proceed-unsafe`
                                    spends its digest against that repr
        dropping in the fallback    identical — the list branch is untouched, and a list is the
                                    documented shape, so the repair does nothing to the case it
                                    was proposed for
        dropping in both branches   halted=done, safety=None, **merge reached**

    The last is CHG-20260906-07's unanimous finding through another door, and worse than the one
    CHG-20260907-01 closed: that counted silence as agreement; this turns a seat that spoke into
    silence first. This test pins the half that can be pinned here — that the finding survives as
    a refusal rather than as nothing.
    """
    with pytest.raises(intake.IntakeError):
        intake.collect({"risk": {"unsafe": [{"issue": "rm -rf /"}], "missing": [], "problems": []}})


def test_three_things_nobody_can_read_are_not_three_options():
    """`read_options` refuses fewer than three because *two is a false choice*. Three objects
    passed that count and reached a person as `["{'a': 1}", "{'b': 2}", "{'c': 3}"]`, which is
    three of nothing.
    """
    with pytest.raises(intake.IntakeError, match="which is not text") as caught:
        intake.read_options({"options": [{"a": 1}, {"b": 2}, {"c": 3}]}, "ui")
    assert "the options offered for 'ui'" in str(caught.value)


def test_a_seat_that_says_nothing_about_the_requirement_is_an_error():
    """*"A voice that said nothing is not a voice that voted no"* — `engine.walk` says that for
    model panels. The survey had no equivalent, at the one node whose purpose is to find problems.

    The realistic answer is not prose or a crash. It is `{"verdict": "pass"}`: the shape every
    **other** seat node in this runner expects, from an agent that did not special-case this one.
    """
    for answer in ({"verdict": "pass", "why": "nothing found"},
                   {"backend": "stub", "node_id": "intake_review", "role": "seat"},
                   {},
                   {"Missing": ["ui"], "Unsafe": ["x"]}):
        with pytest.raises(intake.IntakeError, match="without saying anything"):
            intake.collect({"conformance": answer})


def test_a_seat_that_looked_and_found_nothing_says_so_with_empty_lists():
    """The other half, and the reason the check is about **keys** and not about emptiness."""
    survey = intake.collect({"conformance": {"missing": [], "problems": [], "unsafe": []}})
    assert survey.complete and not survey.problems and not survey.safety

    # One key is enough. A seat reporting only what is missing has still answered.
    assert intake.collect({"conformance": {"missing": ["ui"]}}).missing == ["ui"]


def test_the_shipped_dry_run_backend_no_longer_passes_the_survey_in_silence():
    """Measured on `main` before this change, with no test harness at all:

        nodes asked: ['intake_review', 'intake_review', 'intake_review', 'pm_plan', 'pm_confirm']
        raised at  : node 'pm_confirm' decides on its answer, but the answer named no branch

    `cli._Stub` is the default backend — *"answers nothing, records that it was asked"* — so this
    is what anyone running `runner run` without an agent got. Three seats were asked, all three
    said nothing about the requirement, the survey called it complete, and the run **planned** at
    `pm_plan` before anything refused it.

    It still cannot complete a walk. It now stops at the node whose contract it did not meet,
    with a sentence naming that contract, rather than two nodes later with one about branches.
    """
    from ai_sdlc_runner import cli

    answer = cli._Stub().ask({"node_id": "intake_review", "role": "seat"})
    assert not intake.ANSWER_KEYS & set(answer), "the stub answers none of the three"
    with pytest.raises(intake.IntakeError, match="without saying anything"):
        intake.collect({"conformance": answer})


def test_a_complete_requirement_says_so():
    survey = intake.collect({"a": {"problems": ["a nit"]}, "b": {"problems": []}})
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
    """**Counted in asks, not in recorded stops** (CHG-20260903-42).

    This test asserted the defect. It read `history` as "how many times this has been asked", but a
    history of two recorded stops means the ask **in flight is the third** — the engine checks
    before writing the current stop — and the old body asserted that the runner must *not* offer
    options there. Named for the third, measuring the fourth.

    `>=` and not `>` was never the question: the third unanswered ask is the one that has failed,
    and `asks_including_this_one` is what makes the history say so.
    """
    def asking_now(recorded):
        """`recorded` stops are behind us; this call is the next ask."""
        return intake.needs_options([{"missing": ["ui"]}] * recorded, "ui")

    assert intake.asks_including_this_one([], "ui") == 1, "an empty history means this is the first"
    assert not asking_now(0), "the first ask does not offer options"
    assert not asking_now(1), "nor the second"
    assert asking_now(2), (
        "two stops are recorded and this is the third ask — the one three declarations in "
        "`intake.py` say offers options")
    assert asking_now(3), "and it does not go back to asking afterwards"


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
                # A seat this test did not name is a seat that looked and found nothing —
                # three empty lists, not silence. The `{}` this defaulted to was
                # indistinguishable from a seat that answered something else entirely, so
                # no test in this file could have been about the difference.
                return dict(seat_answers.get(
                    order["seat"], {"problems": [], "missing": [], "unsafe": []}))
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


# ── a seat calling something unsafe is a question for a person (CHG-20260906-07) ──────────────


def test_an_unsafe_finding_stops_the_run_even_when_nothing_is_missing():
    """Measured before the change: `complete=True`, no suspension, and the walk reached `merge`
    with the words *"it deletes user data"* printed on no surface at all — not the terminal, not
    the snapshot, not the console. `Survey.complete` reads only `missing`, and the suspension was
    entered only when it was false, so the one answer the seats have for "this should not be done"
    was the one answer that stopped nothing.
    """
    report = _walk({"risk": {"missing": [], "unsafe": ["it deletes user data"]}})

    assert report.state == engine.SUSPENDED
    assert report.halted_at == "intake_review"
    assert report.suspended["unsafe"] is True
    assert report.suspended["incomplete"] is False, "nothing is missing; it is not that question"
    assert report.suspended["safety"] == {"risk": ["it deletes user data"]}
    assert "it deletes user data" in report.suspended["reason"] or "risk" in \
        report.suspended["reason"], "the sentence has to name who said it"
    assert "pm_plan" not in report.visited, "nothing was planned"
    assert "merge" not in report.visited


def test_the_requirement_being_incomplete_is_asked_first_and_hides_nothing():
    """Both questions at once. A seat cannot weigh a requirement it says it has not been told, so
    the missing aspect is asked first — but the findings ride along on that stop, because deferring
    a question is not the same as dropping it.
    """
    report = _walk({"risk": {"missing": ["ui"], "unsafe": ["it deletes user data"]}})

    assert report.suspended["incomplete"] is True
    assert report.suspended["unsafe"] is False, "one question at a time, and this is the other one"
    assert report.suspended["safety"] == {"risk": ["it deletes user data"]}, \
        "deferred, not dropped"


def test_the_flag_alone_decides_nothing():
    """**The operator's rule.** A decision is about findings somebody read; a flag passed before
    anything was shown answers a question nobody was asked. `unsafe_shown` is empty here, which is
    what a first run looks like.
    """
    report = _walk({"risk": {"missing": [], "unsafe": ["it deletes user data"]}},
                   proceed_unsafe="--proceed-unsafe")

    assert report.suspended is not None and report.suspended["unsafe"] is True
    assert "merge" not in report.visited


def test_a_decision_answers_the_findings_it_was_shown_and_no_others():
    """The digest is of the findings themselves, not of the run or the brief.

    The ask journal's files carry no run id and no brief hash — the risk seat measured that a
    shared journal directory therefore lets one brief's history answer for another's. Pinning the
    decision to what was displayed sidesteps that: a seat that raises something new on a later lap
    has produced a different list, and a decision about the old one does not cover it.
    """
    shown = _walk({"risk": {"missing": [], "unsafe": ["it deletes user data"]}})
    digest = intake.shown_digest(shown.suspended["safety"])

    same = _walk({"risk": {"missing": [], "unsafe": ["it deletes user data"]}},
                 proceed_unsafe="--proceed-unsafe", unsafe_shown=(digest,))
    assert "merge" in same.visited, "the findings that were read are the findings that were answered"
    spoken = [line for line in same.relaxations if "unsafe" in line]
    assert len(spoken) == 1, "continuing past it is a relaxation, and is written down"
    assert same.relaxation_authorisers[spoken[0]] == "--proceed-unsafe", "and by whom"

    other = _walk({"risk": {"missing": [], "unsafe": ["it drops the audit table"]}},
                  proceed_unsafe="--proceed-unsafe", unsafe_shown=(digest,))
    assert other.suspended is not None and other.suspended["unsafe"] is True, \
        "a different finding is a different question"
    assert "merge" not in other.visited


def test_a_clean_survey_is_untouched_by_any_of_this():
    """The floor. Nothing unsafe, nothing missing, and the run is exactly what it was."""
    report = _walk({"risk": {"missing": [], "unsafe": []}})
    assert report.halted_at == "done"
    assert "merge" in report.visited


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


def test_the_command_line_can_reach_the_escalation_it_documents(tmp_path):
    """`intake.py` promises options after the third unanswered ask. `runner run` could not get there.

    `cmd_serve` accumulates the count in `RunState`, which is one process. `cmd_run` passed no
    `intake_history` at all, so `cfg.intake_history` was `()` on every invocation, `times_asked`
    was hard-wired to 0, and `needs_options` was False at any count — the escalation could not fire
    on the command line, ever, and `stop_reason` rendered "asked once" on the fifth re-run
    (CHG-20260901-17, defect seat).

    Driven through `AskJournal`, because the journal is what `cmd_run` now reads and writes.
    """
    journal = engine.AskJournal(tmp_path / "asks")
    reached = []
    for _ in range(intake.ASK_LIMIT + 1):
        history = journal.intake_stops()
        reached.append(intake.needs_options(history, "flow"))
        journal.record_intake_stop(["flow"])

    # **The message and the assertion disagreed** (CHG-20260903-42). The message below is the rule
    # and always was; the list was `[False] * ASK_LIMIT + [True]`, which fires on the *fourth*. Two
    # tests in this file were named and documented for the third and asserted the fourth — the same
    # confusion between "stops recorded" and "times asked" that caused the defect, which is why
    # neither of them ever caught it.
    assert reached == [False] * (intake.ASK_LIMIT - 1) + [True, True], (
        f"the escalation fires on the {intake.ASK_LIMIT}th unanswered ask and not before; "
        f"got {reached}")
    assert intake.times_asked(journal.intake_stops(), "flow") == intake.ASK_LIMIT + 1


def test_an_intake_stop_is_not_mistaken_for_an_unanswered_ask(tmp_path):
    """Stops share the journal directory with asks, and must stay out of the ask ledgers.

    An intake stop carries no `ask_id`, no `status` and no `order`. If `entries()` swept one up,
    `pending()` would report it as a question nobody answered and a resumed run would try to
    re-ask something that was never asked.
    """
    journal = engine.AskJournal(tmp_path / "asks")
    journal.record("a1", "pm_plan", None, {"objective": "x"})
    journal.record_intake_stop(["flow", "ui"])
    journal.answered("a1", {"ok": True})

    assert [e["ask_id"] for e in journal.entries()] == ["a1"]
    assert journal.pending() == []
    assert set(journal.answers()) == {"a1"}
    assert journal.intake_stops() == [{"missing": ["flow", "ui"]}]


def test_a_stop_with_nothing_missing_is_not_recorded(tmp_path):
    """`times_asked` counts stops that named an aspect. A stop that named none is not one of them,
    and recording it would inflate every aspect's count by nothing anybody asked for."""
    journal = engine.AskJournal(tmp_path / "asks")
    journal.record_intake_stop([])
    assert journal.intake_stops() == []


# ── a falsy answer is not a problem (CHG-20260903-36) ───────────────────────────────────────────


@pytest.mark.parametrize("value", [False, 0, {}, [], "", "   "])
def test_a_falsy_answer_is_not_recorded_as_a_problem(value):
    """`_strings`'s `str` and `list` branches strip and drop blanks; the fallback did neither.

    A seat answering `"problems": false` — a plausible JSON shape for *none* — was recorded as
    having raised one problem named `False`, attributed to it, and printed to the operator by
    `Survey.all_problems()`:

        _strings(False) -> ['False']    _strings(0) -> ['0']    _strings({}) -> ['{}']

    This is `CHG-20260903-27` L-30's shape — *"fabricated a verdict where there was no answer"* —
    one module over, and that record swept no further than the adjudicators (idiom seat).
    """
    assert intake._strings(value) == []


def test_a_real_answer_still_arrives():
    """The false-stop guard, in both shapes the module reads generously."""
    assert intake._strings("  a real problem  ") == ["a real problem"]
    assert intake._strings(["a", "", "b"]) == ["a", "b"]


def test_a_seat_that_says_no_problems_raises_none():
    """The consequence, at the surface an operator reads."""
    survey = intake.collect({"defect": {"problems": False, "missing": []}})

    assert survey.problems.get("defect", []) == []


def test_nothing_reads_the_raw_tally_where_the_ask_in_flight_counts():
    """**The rule** (CHG-20260903-42): one name, so the two readers cannot drift apart again.

    `stop_reason` wrote `times_asked(...) + 1` and `needs_options` wrote `times_asked(...)`, twelve
    lines apart in one module, over the same history — and the operator read *"(asked 3 times)"*
    beside a decision that had counted two. Both now go through `asks_including_this_one`, and this
    refuses a third reader that re-derives the `+ 1` or forgets it.

    Read as structure rather than as text: a guard pinning the wording would go red on a rename and
    green on the defect, which CHG-20260903-39 had to undo twice in one change.
    """
    import ast

    tree = ast.parse(pathlib.Path(intake.__file__).read_text(encoding="utf-8"))
    allowed = {"times_asked", "asks_including_this_one"}
    offenders = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name in allowed:
            continue
        for call in ast.walk(fn):
            if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "times_asked":
                offenders.append(fn.name)

    assert offenders == [], (
        f"{sorted(set(offenders))} read the raw tally directly. `times_asked` counts stops already "
        f"recorded; every question about how many times a person has been asked is asked before "
        f"this run's stop is written, so it must go through `asks_including_this_one`")

    # And the floor: the rule must be capable of flagging something, or it passes by examining
    # nothing. `asks_including_this_one` is the one function allowed to call `times_asked`, and it
    # must actually do so.
    named = next(fn for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                 and fn.name == "asks_including_this_one")
    assert any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "times_asked"
               for c in ast.walk(named)), "the one name no longer reads the tally it exists to adjust"


def test_the_sentence_and_the_decision_agree_on_the_same_run():
    """What the defect looked like from the operator's chair, pinned as a property.

    Neither half is checked here for its own sake: the claim is that the number a person is shown
    and the number the runner acts on are **one number** (CHG-20260903-42).
    """
    aspect = sorted(intake.BY_ASPECT)[0]

    class _Survey:
        missing = (aspect,)
        complete = False

    history = []
    for expected in range(1, intake.ASK_LIMIT + 3):
        shown = intake.stop_reason(_Survey(), history)
        offering = intake.needs_options(history, aspect)

        word = {1: "asked once", 2: "asked twice"}.get(expected, f"asked {expected} times")
        assert word in shown, f"ask {expected} is described as something else: {shown}"
        assert offering == (expected >= intake.ASK_LIMIT), (
            f"the person is told {word!r} and the decision beside it "
            f"{'offers options' if offering else 'asks again'}")
        history.append({"missing": [aspect]})
