"""Settings, and the three findings from round 3 that CHG-20260823-03 did not cover.

**Settings** close the last line of the requirement still taken literally-but-not-quite:
*預設有強制下限,但允許使用者開啟高風險模式來規避這個限制,**在 GUI 上設定***. The seat count and the
bypass were command-line flags, and the interactive part was one confirmation shown at the moment
the floor was crossed. That is "the user decides"; it is not "set it in the GUI".

**The three findings** are what an independent verifier found after the previous round shipped:

* a work order whose `instructions` said *"deploy the new build to production, then wipe the users
  table"* ran to completion, because the operation beside it declared `ordinary`. The words were in
  the text the engineer would act on and nothing read them;
* the review seats were exempted from declaring anything **by role name**, while their role could
  execute and the work order handed that capability over;
* `--confirm no_such_gate` was swallowed whole — the operator believes they confirmed something, the
  run stops anyway, and nothing says why.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from ai_sdlc_runner import engine, graph, policy, settings as settings_mod

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _dispatch(order):
    if order.get("seat"):
        return {"verdict": "pass"}
    branch = ANSWERS.get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


def _cfg(instructions=None, node="engineer_build", **kw):
    """Every node gets an ordinary brief; `node` gets `instructions` if one is given.

    Putting the brief on every node made the first version of these tests assert the wrong node:
    the run halts at the *first* one whose brief describes a red line, which is `pm_plan`. The
    behaviour was right and the test was wrong — worth the comment, because a test that pins the
    wrong node passes for the wrong reason as soon as the ordering changes.
    """
    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    if instructions is not None:
        specs[node]["instructions"] = instructions
    base = dict(node_specs=specs,
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(kw)
    return engine.RunConfig(**base)


# --------------------------------------------------------------------------------------
# the brief is read, not just the operation beside it
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("brief", [
    "deploy the new build to production, then wipe the users table",
    "run the migration against the customer database",
    "rotate the API key before the handover",
    "make the repo public once the embargo lifts",
])
def test_a_brief_that_describes_a_red_line_stops_the_node(brief):
    """The exact hole: the words were in `instructions`, the operation beside them said `ordinary`,
    and nothing looked. A description giving itself away used not to matter as long as it gave
    itself away in the other field."""
    cfg = _cfg(instructions=brief,
               operations={"engineer_build": [{"description": "routine work", "kind": "ordinary"}]})
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.halted_at == "engineer_build"
    assert "its instructions describes" in report.halt_reason


def test_the_halt_quotes_the_brief_so_it_can_be_fixed():
    cfg = _cfg(instructions="wipe the users table")
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert "wipe the users table" in report.halt_reason
    assert "a person carries it out" in report.halt_reason


def test_declaring_it_does_not_get_past_it_either():
    """Both roads stop, which is the right answer for a node whose brief says it will wipe a table.
    There is no wording of the declaration that makes a red-line brief acceptable."""
    cfg = _cfg(instructions="wipe the users table",
               operations={"engineer_build": [{"description": "wipe it", "kind": "delete"}]})
    assert engine.walk(cfg, _dispatch, enabled=True).halted_at == "engineer_build"


def test_the_objective_and_scope_are_read_too():
    """About *which fields are read*, not about the word list's coverage — that is measured
    separately in `test_flow.py`, and it is weak on purpose-and-record."""
    cfg = _cfg()
    cfg.node_specs["engineer_build"]["objective"] = "drop table legacy_accounts"
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.halted_at == "engineer_build"
    assert "its objective describes" in report.halt_reason


def test_the_brief_check_is_the_backstop_and_inherits_its_weakness():
    """`drop the legacy table` is a hard delete and the word lists miss it — "drop table" is in the
    list, "drop the legacy table" is not. Recorded rather than papered over: reading more *fields*
    does not make the *matcher* better, and pretending otherwise is how a backstop gets trusted."""
    assert policy.permanent_halt("drop the legacy table") is None
    cfg = _cfg()
    cfg.node_specs["engineer_build"]["objective"] = "drop the legacy table"
    assert engine.walk(cfg, _dispatch, enabled=True).halted_at == "done"


def test_an_ordinary_brief_is_not_stopped():
    """The cost of reading the brief is false stops, so the ordinary case is pinned. A check that
    fires on "do the work" is one nobody keeps switched on."""
    assert engine.walk(_cfg(), _dispatch, enabled=True).halted_at == "done"


@pytest.mark.parametrize("brief", [
    "add a unit test for the parser",
    "rename the variable and update its callers",
    "fix the off-by-one in the loop bound",
    "write the docstring for this module",
    "remove the unused import",
])
def test_ordinary_briefs_across_the_kinds_of_work_this_runner_drives(brief):
    assert engine.walk(_cfg(instructions=brief), _dispatch, enabled=True).halted_at == "done"


# --------------------------------------------------------------------------------------
# a confirmation for a gate nobody defined
# --------------------------------------------------------------------------------------

def test_confirming_a_gate_that_does_not_exist_is_refused():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(confirmed=("no_such_gate",)), _dispatch, enabled=True)
    assert "does not exist" in str(exc.value)
    assert "confirms nothing" in str(exc.value)


def test_the_error_lists_the_gates_that_do_exist():
    with pytest.raises(engine.EngineError) as exc:
        engine.walk(_cfg(confirmed=("merge_it",)), _dispatch, enabled=True)
    for gate in policy.GATES:
        assert gate in str(exc.value)


def test_a_confirmation_the_run_never_reached_is_reported_not_dropped():
    """A run can legitimately finish without reaching a gate it was prepared for. Dropping that
    silently leaves the operator believing an approval was used."""
    report = engine.walk(_cfg(confirmed=("merge", "acceptance", "acceptance")), _dispatch,
                         enabled=True)
    assert report.halted_at == "done"
    assert any("more time(s) than the run stopped at it" in line for line in report.confirmations)


def _unspent(report):
    return [line for line in report.confirmations
            if "more time(s) than the run stopped at it" in line]


def test_a_walk_that_stops_reports_the_confirmation_it_never_reached():
    """The exit the test above does **not** cover, and the one the fix was actually for.

    CHG-20260823-05 moved this report into `_finish` precisely because four of the five ways a walk
    can end jumped past its old position. The only behavioural test written for it ends at `done` —
    the single exit that always worked — so regressing `_finish` to success-only left the suite
    green. Verified by an acceptance-round verifier doing exactly that; recorded as CHG-20260827-04.
    """
    report = engine.walk(_cfg(instructions="drop the production database", node="pm_plan",
                              undeclared="refuse", confirmed=("merge", "merge")),
                         _dispatch, enabled=True)
    assert report.state == "stopped"
    assert report.halted_at != "done"
    assert _unspent(report), (
        f"a stopped run dropped an unspent confirmation: {report.confirmations}")


def test_a_walk_that_suspends_reports_the_confirmation_it_never_reached():
    """The other broken exit: the run is waiting for a person, and still owes them this."""
    report = engine.walk(_cfg(risk="high", confirmed=("merge", "merge")), _dispatch, enabled=True)
    assert report.state == "suspended"
    assert report.halted_at != "done"
    assert _unspent(report), (
        f"a suspended run dropped an unspent confirmation: {report.confirmations}")


def test_the_unspent_confirmation_is_reported_once_and_not_once_per_finish():
    """A gate stop ran `_finish` twice, so one over-confirmation produced two complaints.

    `_gate` finishes the report itself — it has `cfg.conversation` and the call site in `walk` does
    not — and `walk` then finished the same report again, appending the lines a second time. Found
    while writing the two tests above, which is the point of driving an exit rather than reading it.

    The count in the sentence was right both times, so nothing looked wrong unless you read the
    report: two lines each saying "2 more time(s)" for a gate confirmed twice.
    """
    report = engine.walk(_cfg(risk="high", confirmed=("merge", "merge")), _dispatch, enabled=True)
    assert len(_unspent(report)) == 1, (
        f"the same unspent confirmation is reported {len(_unspent(report))} times: "
        f"{report.confirmations}")


# --------------------------------------------------------------------------------------
# settings: what the user sets, in the GUI
# --------------------------------------------------------------------------------------

def test_the_defaults_are_the_safe_end_of_every_axis():
    s = settings_mod.Settings()
    assert s.review_seats is None
    assert s.high_risk_mode is False
    assert s.seats() == policy.SEAT_FLOOR
    assert not s.below_floor()


def test_a_missing_file_is_the_defaults(tmp_path):
    assert settings_mod.load(str(tmp_path / "nope.json")) == settings_mod.Settings()


def test_an_empty_file_is_the_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("", encoding="utf-8")
    assert settings_mod.load(str(path)) == settings_mod.Settings()


def test_a_corrupt_file_is_an_error_not_the_defaults(tmp_path):
    """Falling back would make a typo indistinguishable from a deliberate choice, and one of the two
    settings here is a safety bypass."""
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError) as exc:
        settings_mod.load(str(path))
    assert "not valid JSON" in str(exc.value)


def test_a_setting_this_runner_does_not_read_is_refused(tmp_path):
    """Settings may lower the seat floor and nothing else. A key nobody reads looks exactly like one
    that works, which is how a person ends up believing they turned something on."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": 3, "skip_permanent_halts": True}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError) as exc:
        settings_mod.load(str(path))
    assert "skip_permanent_halts" in str(exc.value)
    assert "policy.py" in str(exc.value)


@pytest.mark.parametrize("bad", [0, -1, "three", 2.5, True])
def test_a_nonsense_seat_count_is_refused(tmp_path, bad):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": bad}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(str(path))


def test_a_nonsense_bypass_value_is_refused(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"high_risk_mode": "yes"}), encoding="utf-8")
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.load(str(path))


def test_saving_and_loading_round_trips(tmp_path):
    path = str(tmp_path / "settings.json")
    original = settings_mod.Settings(review_seats=1, high_risk_mode=True)
    settings_mod.save(original, path)
    assert settings_mod.load(path) == original


def test_the_floor_still_applies_without_the_bypass():
    """The whole point: a seat count below the floor does nothing on its own."""
    assert settings_mod.Settings(review_seats=1).seats() == policy.SEAT_FLOOR
    assert settings_mod.Settings(review_seats=1, high_risk_mode=True).seats() == 1


def test_the_description_says_when_it_is_running_below_the_floor():
    described = settings_mod.Settings(review_seats=1, high_risk_mode=True).describe()
    assert "below the floor" in described
    assert "high-risk mode: ON" in described
    assert "high-risk mode: off" in settings_mod.Settings().describe()


# --------------------------------------------------------------------------------------
# the screen itself
# --------------------------------------------------------------------------------------

class _Answers:
    """Drives `tui`'s numbered fallback: one answer per prompt, in order."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def __call__(self, prompt):
        return self.answers.pop(0) if self.answers else "q"


def test_discarding_changes_nothing(capsys):
    result = settings_mod.edit(settings_mod.Settings(), input_fn=_Answers("4"))
    assert result is None


def test_cancelling_changes_nothing():
    assert settings_mod.edit(settings_mod.Settings(), input_fn=_Answers("q")) is None


def test_setting_the_seat_count_and_saving():
    #  1 = review seats  →  1 = the floor  →  3 = save
    result = settings_mod.edit(settings_mod.Settings(), input_fn=_Answers("1", "1", "3"))
    assert result == settings_mod.Settings(review_seats=policy.SEAT_FLOOR)


def test_turning_the_bypass_on_when_nothing_is_being_crossed_needs_no_ceremony():
    #  2 = high-risk mode  →  3 = save. Seats are at the floor, so nothing is crossed yet.
    result = settings_mod.edit(settings_mod.Settings(), input_fn=_Answers("2", "3"))
    assert result == settings_mod.Settings(high_risk_mode=True)


def test_crossing_the_floor_asks_first_and_declining_leaves_it_off():
    #  2 = high-risk mode  →  1 = keep the floor  →  3 = save
    start = settings_mod.Settings(review_seats=1)
    result = settings_mod.edit(start, input_fn=_Answers("2", "1", "3"))
    assert result.high_risk_mode is False
    assert result.seats() == policy.SEAT_FLOOR


def test_crossing_the_floor_when_confirmed_turns_it_on():
    #  2 = high-risk mode  →  2 = enable  →  3 = save
    start = settings_mod.Settings(review_seats=1)
    result = settings_mod.edit(start, input_fn=_Answers("2", "2", "3"))
    assert result.high_risk_mode is True
    assert result.seats() == 1


def test_turning_the_bypass_off_asks_nothing():
    """Asymmetric on purpose: re-enforcing a floor can only make the run safer."""
    start = settings_mod.Settings(review_seats=1, high_risk_mode=True)
    result = settings_mod.edit(start, input_fn=_Answers("2", "3"))
    assert result.high_risk_mode is False


# --------------------------------------------------------------------------------------
# what settings may not do
# --------------------------------------------------------------------------------------

def test_settings_cannot_change_what_a_verdict_or_a_halt_or_the_rule_IS():
    """**The property, not the surface** (CHG-20260903-47, defect seat L-13).

    This asserted `FIELDS == (...)` and an `as_dict` key set, under a name claiming settings cannot
    reach a gate verdict, a permanent halt or the adjudication rule. It went **green on the defect
    and red on a rename** — the class this ledger has now corrected four times.

    What is actually true is narrower: settings cannot change the **definitions**. What they can
    change is whether a stop happens, and the two places that occurs are pinned below rather than
    denied here.
    """
    before = {"gates": {g: dict(v) for g, v in policy.GATES.items()},
              "halt_kinds": tuple(policy.PERMANENT_HALT_KINDS)}

    settings_mod.Settings(review_seats=1, high_risk_mode=True,
                          ordinary_commands=("pnpm", "npm")).as_dict()

    assert {g: dict(v) for g, v in policy.GATES.items()} == before["gates"], (
        "a settings object changed what a gate verdict is")
    assert tuple(policy.PERMANENT_HALT_KINDS) == before["halt_kinds"], (
        "a settings object changed which kinds are permanent halts")
    two = [seat.name for seat in policy.SEATS][:2]
    assert policy.adjudicate({two[0]: "pass", two[1]: "fail"})["outcome"] == "undecided", (
        "the adjudication rule itself must not move: a split panel is undecided")


def test_one_seat_makes_undecided_unreachable_and_that_is_disclosed():
    """**A settings field decides whether a person is asked to break a tie.**

    `undecided` is the outcome that means nobody could settle it and a person must. At one seat
    there is nothing to split, so the outcome cannot arise — the rule is untouched and the input
    that produces it is gone. `resolve_seats`' own docstring records this; the paragraph in
    `settings.py` denied it until CHG-20260903-47.
    """
    def outcome(seats, high_risk_mode):
        names = [s.name for s in policy.SEATS][:policy.resolve_seats(seats, high_risk_mode)]
        said = {name: ("pass" if i % 2 == 0 else "fail") for i, name in enumerate(names)}
        return policy.adjudicate(said)["outcome"], len(names)

    assert outcome(None, False) == ("pass", 3)
    assert outcome(2, True) == ("undecided", 2), "two seats can still disagree"
    assert outcome(1, True) == ("pass", 1), (
        "at one seat `undecided` is unreachable — if this ever returns `undecided`, the "
        "disclosure in `settings.py` is the thing to update")


def test_vouching_a_command_decides_whether_a_permanent_halt_trips():
    """The other disclosed consequence. `settings.py` said this in a bullet three lines under a
    sentence denying it, from CHG-20260903-28 until CHG-20260903-47."""
    node = graph.BY_ID["engineer_build"]
    operation = {"kind": "ordinary", "description": "build",
                 "targets": ["pnpm exec turbo run build"]}

    def stops(vouched):
        cfg = engine.RunConfig(node_specs={node.id: {"operations": [operation]}}, decisions={},
                               operations={node.id: [operation]}, ordinary_commands=vouched)
        return engine._permanent_halt(node, cfg, engine.RunReport())

    refused = stops(())
    assert refused and "does not recognise" in str(refused), refused
    assert stops(("pnpm",)) is None, (
        "vouching the command no longer lets the run past the unrecognised-target halt; if that "
        "is deliberate, `settings.py`'s disclosure is the thing to update")

    # And the direction it must never work in stays shut — vouching is not a red-line override.
    assert policy.recognise("rm -rf /srv", ("rm",)) == "red"


def test_the_surface_is_still_three_fields():
    """Kept from the old body, as what it actually was: an enumeration of the surface. It is a
    useful check and it was never the claim its name made."""
    assert settings_mod.FIELDS == ("review_seats", "high_risk_mode", "ordinary_commands")
    assert set(settings_mod.Settings().as_dict()) == set(settings_mod.FIELDS)


def test_vouching_cannot_turn_a_red_line_ordinary():
    """The one direction the operator's list must not work in."""
    for target in ("rm -rf /srv", "git push --force origin main", "kubectl apply -f prod/",
                   "dd if=/dev/zero of=/dev/sda"):
        assert policy.recognise(target, ("rm", "git", "kubectl", "dd")) == "red", target


def test_a_vouched_command_must_be_one_word():
    """A whole command line here would be the prefix mistake this setting exists to avoid."""
    import json as _json

    import pytest as _pytest
    from pathlib import Path as _Path

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = _Path(d) / "settings.json"
        path.write_text(_json.dumps({"ordinary_commands": ["npm run build"]}), encoding="utf-8")
        with _pytest.raises(settings_mod.SettingsError) as exc:
            settings_mod.load(str(path))
        assert "one word" in str(exc.value)


def test_no_settings_value_changes_what_the_policy_says():
    before = {g: dict(v) for g, v in policy.GATES.items()}
    settings_mod.Settings(review_seats=1, high_risk_mode=True).seats()
    assert {g: dict(v) for g, v in policy.GATES.items()} == before
    assert len(policy.PERMANENT_HALTS) == 6


# --------------------------------------------------------------------------------------
# declining a saved bypass, for one run
# --------------------------------------------------------------------------------------

def _shipped(tmp_path, py_stub, **saved):
    """A config, a plan and a settings file — the three inputs a real run takes."""
    import json as _json

    agent = """
import json, sys
order = json.load(sys.stdin)
answers = %r
if order.get("seat"):
    print(json.dumps({"verdict": "pass"}))
else:
    branch = answers.get(order["node_id"])
    print(json.dumps({"verdict": branch} if branch else {"ok": True}))
""" % (ANSWERS,)
    argv = py_stub(agent)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {_json.dumps(argv)}\n", encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(_json.dumps(saved), encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(_json.dumps({
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low"}), encoding="utf-8")
    return str(config), str(settings_file), str(plan)


def test_a_saved_bypass_can_be_declined_for_one_run(tmp_path, py_stub, capsys):
    """`--high-risk-mode` and the settings file were OR-ed, so a bypass persisted in settings could
    not be turned off for a single run. A verifier pointed out that "a flag beats the file" was only
    true in the *relaxing* direction — the wrong one to be asymmetric in. This shipped without a
    test; it has one now."""
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    out = capsys.readouterr().out
    # The thing that matters is whether a *bypass was recorded*, not whether the words "below the
    # floor" appear — the note explaining the fall-back to the floor contains them too, and an
    # assertion that cannot tell those apart is one that fails for the wrong reason.
    assert "review opened with" not in out, "a floor bypass was still recorded"
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_without_the_flag_the_saved_bypass_still_applies(tmp_path, py_stub, capsys):
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge"])
    assert "below the floor" in capsys.readouterr().out


def test_declining_puts_the_floor_back_not_merely_the_count(tmp_path, py_stub, capsys):
    """The bypass is what makes a count below the floor legal. Declining it must restore the floor,
    not run one seat without recording the relaxation."""
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub, review_seats=1, high_risk_mode=True)
    cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared", "allow",
              "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    out = capsys.readouterr().out
    assert "review opened with" not in out, "a floor bypass was still recorded"
    assert "opening 3" in out, "the fall-back to the floor should be stated, not silent"
    assert out.count("=pass") >= policy.SEAT_FLOOR


def test_the_flag_is_harmless_when_nothing_was_saved(tmp_path, py_stub, capsys):
    from ai_sdlc_runner import cli

    config, settings_file, plan = _shipped(tmp_path, py_stub)
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan, "--confirm", "merge", "--no-high-risk-mode"])
    assert code == 0
    assert "stopped at:    done" in capsys.readouterr().out


# ── the file counted itself and got the wrong number, in a sentence it prints ──────────────────
#
# `FIELDS` has held three names since `ordinary_commands` was added. Three sentences in this module
# said one or two, and the fourth was the `SettingsError` an operator reads on a typo. The third
# field is not decorative: measured, `policy.unverified({kind: ordinary, targets: ['npm ci']}, ())`
# returns `('npm ci',)` with `on_trust=True` — which `engine.py:1557` refuses on — and vouching
# `npm` returns `()` with `on_trust=False` and the run proceeds. `policy.py` even records that
# `load` refuses certain commands in that field, so a guard existed for the field whose existence
# the module's own paragraph denied (CHG-20260903-28, found by the defect seat).
#
# `test_settings.py:347` already pinned `FIELDS` to all three and its docstring names the third.
# Nothing compared the tuple to the prose, which is the gap these close.


def _module_prose():
    """Every docstring and comment in `settings.py`, which is where the counting happened."""
    return pathlib.Path(settings_mod.__file__).read_text(encoding="utf-8")


def test_no_sentence_in_this_module_states_a_count_that_disagrees_with_fields():
    """A paragraph that counts the file it is in has to be read against the file.

    This module's own docstring records being corrected once before, for the same class of error:
    it said "or corrupt yields the defaults" and contradicted `load()` directly below it.
    """
    prose = _module_prose()
    wrong = {"one": 1, "two": 2, "three": 3, "four": 4}
    claims = re.findall(r"(?:one|two|three|four) of the (one|two|three|four) settings", prose)
    for claimed in claims:
        assert wrong[claimed] == len(settings_mod.FIELDS), (
            f"a sentence says there are {claimed} settings; FIELDS has {len(settings_mod.FIELDS)}: "
            f"{list(settings_mod.FIELDS)}")


def test_the_module_does_not_claim_the_seat_floor_is_all_settings_can_do():
    """The specific false sentence, named, so a rewrite that reintroduces it goes red.

    `ordinary_commands` vouches commands so an undeclared target stops being refused. That is not
    lowering the seat floor, and it is the setting the file guards most carefully.
    """
    prose = _module_prose()

    assert "lower the seat floor and can do nothing else" not in prose
    assert "may lower the seat floor and nothing else" not in prose
    assert "ordinary_commands" in prose, "the third field must be described where the others are"


def test_the_error_an_operator_reads_names_every_field_this_runner_reads(tmp_path):
    """Derived from `FIELDS`, not typed beside it — so the sentence cannot drift again."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"nonsense": 1}), encoding="utf-8")

    with pytest.raises(settings_mod.SettingsError) as caught:
        settings_mod.load(path)

    said = str(caught.value)
    for field in settings_mod.FIELDS:
        assert field in said, f"{field} is read by this runner and the refusal does not say so"
