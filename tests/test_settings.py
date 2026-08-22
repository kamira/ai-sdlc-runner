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

def test_settings_cannot_reach_a_gate_verdict_or_a_permanent_halt():
    """Asserted by enumerating the surface rather than promising it in prose.

    Three fields now: the seat floor, its bypass, and the operator's vouched command list. The third
    can only ever move a target from `unrecognised` to `ordinary`, and `policy._SUSPECT` still
    overrides it — vouching for `npm` does not vouch for `npm run release`. None of the three can
    reach a gate verdict, a permanent halt kind, or the adjudication rule.
    """
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
