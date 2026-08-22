"""The command line (CHG-20260823-01).

This file exists because an independent verifier found `cli.py` with no test at all — 203 lines that
decide which model answers which seat, what the operator can confirm, and whether a run has side
effects. The three things worth pinning here are the ones a reader cannot check by eye:

* **one process per ask** — the session boundary made physical, so "closed after the ask" is not a
  promise a backend has to keep;
* **`--seat-model` routes the same question to a different answerer**, which is what makes
  cross-model review real rather than one model asked several times;
* **the flags reach the engine** — a `--confirm` the engine never sees is a switch connected to
  nothing, which is the failure this whole round was about.
"""
from __future__ import annotations

import json
import sys

import pytest

from ai_sdlc_runner import cli, engine, graph, policy

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _plan(**kw):
    plan = {
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low",
    }
    plan.update(kw)
    return plan


def _plan_file(tmp_path, **kw):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_plan(**kw)), encoding="utf-8")
    return str(path)


#: A stand-in agent: reads the work order on stdin and answers whatever branch the node needs. Kept
#: as Python run through `sys.executable` rather than a shell script — Windows has no shebang, so a
#: bare `.sh` path handed to CreateProcess raises WinError 193.
AGENT = """
import json, sys
order = json.load(sys.stdin)
answers = %r
if order.get("seat"):
    print(json.dumps({"verdict": "pass", "seat": order["seat"]}))
else:
    branch = answers.get(order["node_id"])
    print(json.dumps({"verdict": branch} if branch else {"ok": True}))
""" % (ANSWERS,)


# --------------------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------------------

def test_a_missing_config_is_an_empty_one_not_a_crash():
    assert cli.load_config("no/such/runner.yaml") == {}


def test_the_fallback_reader_handles_the_flat_keys_without_pyyaml(tmp_path, monkeypatch):
    """PyYAML is optional, so the fallback is not a nicety — it is the only reader on a bare box."""
    path = tmp_path / "runner.yaml"
    path.write_text('agent_command: "my-agent --json"\nagent_timeout: 30  # seconds\n',
                    encoding="utf-8")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", no_yaml)
    config = cli.load_config(str(path))
    assert config["agent_command"] == "my-agent --json"
    assert config["agent_timeout"] == "30"


# --------------------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------------------

def test_with_no_agent_configured_the_factory_answers_with_the_stub():
    session = cli.session_factory({})()
    assert isinstance(session, cli._Stub)
    answer = session.ask({"node_id": "pm_plan", "role": "pm"})
    assert answer["backend"] == "stub"


def test_every_ask_gets_a_new_session_object():
    """The one-session rule is enforced in the engine by identity, so a factory that hands back the
    same object is refused. This checks the CLI's factory never does."""
    factory = cli.session_factory({"agent_command": "true"})
    assert factory() is not factory()


def test_a_seat_model_routes_that_seat_to_a_different_command():
    """The same question, different answerers — which is what cross-model review means."""
    factory = cli.session_factory({"agent_command": ["default-agent"]},
                                  {"conformance": ["other-agent"]})
    assert factory("conformance").argv == ["other-agent"]
    assert factory("defect").argv == ["default-agent"]


def test_a_seat_with_no_model_of_its_own_falls_back_to_the_default():
    factory = cli.session_factory({"agent_command": ["default-agent"]}, {"risk": ["other"]})
    assert factory("conformance").argv == ["default-agent"]


def test_a_string_command_is_split_and_a_list_is_taken_as_given():
    assert cli.session_factory({"agent_command": "a b c"})().argv == ["a", "b", "c"]
    assert cli.session_factory({"agent_command": ["a b", "c"]})().argv == ["a b", "c"]


def test_one_process_per_ask_and_the_order_goes_in_on_stdin(tmp_path):
    """The session boundary made physical: nothing survives the ask, because the process does not."""
    script = tmp_path / "agent.py"
    script.write_text("import json,sys; print(json.dumps({'saw': json.load(sys.stdin)['node_id']}))",
                      encoding="utf-8")
    session = cli._Process([sys.executable, str(script)], timeout=60)
    answer = session.ask({"node_id": "pm_plan", "role": "pm"})
    assert answer["exit_code"] == 0
    assert json.loads(answer["stdout"])["saw"] == "pm_plan"


# --------------------------------------------------------------------------------------
# flow and policy
# --------------------------------------------------------------------------------------

def test_flow_prints_every_node_and_agrees_with_the_graph(capsys):
    assert cli.main(["flow"]) == 0
    out = capsys.readouterr().out
    for node in graph.NODES:
        assert node.id in out
    assert f"{len(graph.NODES)} nodes" in out


def test_policy_prints_every_gate_at_every_risk_grade(capsys):
    assert cli.main(["policy"]) == 0
    out = capsys.readouterr().out
    for gate, grades in policy.GATES.items():
        assert gate in out
        for risk in policy.RISKS:
            assert f"{risk}:{grades[risk]}" in out


def test_policy_marks_which_seat_can_veto(capsys):
    cli.main(["policy"])
    out = capsys.readouterr().out
    for seat in policy.SEATS:
        assert seat.name in out
    assert "veto" in out


def test_no_subcommand_prints_the_flow(capsys):
    assert cli.main([]) == 0
    assert "intake" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------

def test_run_without_a_plan_refuses_rather_than_inventing_one(capsys):
    assert cli.main(["run"]) == 2
    assert "needs --plan" in capsys.readouterr().out


def test_a_run_walks_the_flow_and_reports_where_it_stopped(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    code = cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path),
                     "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0
    assert "stopped at:    done" in out


def test_the_panel_result_is_reported_with_every_seats_verdict(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path), "--confirm", "merge"])
    out = capsys.readouterr().out
    assert "panel:         lead_review → pass" in out
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_confirm_reaches_the_engine_and_is_reported(tmp_path, py_stub, capsys):
    """A `--confirm` the engine never sees is a switch wired to nothing."""
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run",
              "--plan", _plan_file(tmp_path, risk="medium"), "--confirm", "plan_confirmed"])
    out = capsys.readouterr().out
    assert "confirmed:" in out and "plan_confirmed" in out
    # One gate confirmed is one gate confirmed: the next one still stops the run.
    assert "stopped at:    lead_assess" in out


def test_without_the_confirmation_the_same_run_stops_at_the_first_gate(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path, risk="medium")])
    assert "stopped at:    pm_confirm" in capsys.readouterr().out


def test_a_plans_operations_reach_the_permanent_halts(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    plan = _plan_file(tmp_path, operations={"engineer_build": ["deploy it to production"]})
    cli.main(["--config", str(config), "run", "--plan", plan])
    out = capsys.readouterr().out
    assert "stopped at:    engineer_build" in out
    assert "production deploy" in out


def test_an_engine_error_is_reported_rather_than_raised(tmp_path, capsys):
    """A plan whose branches do not cover the flow is the operator's mistake, and they get told."""
    plan = _plan_file(tmp_path, decisions={})
    assert cli.main(["run", "--plan", plan]) == 10
    assert "halted:" in capsys.readouterr().out


def test_the_journal_is_written_where_the_flag_says(tmp_path, py_stub):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    journal = tmp_path / "asks"

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--ask-journal", str(journal)])
    entries = sorted(journal.glob("*.json"))
    assert entries
    assert all(json.loads(p.read_text(encoding="utf-8"))["status"] == "answered" for p in entries)


# --------------------------------------------------------------------------------------
# seats and the floor
# --------------------------------------------------------------------------------------

def test_fewer_seats_than_the_floor_asks_before_relaxing_it(tmp_path, py_stub, monkeypatch, capsys):
    """The floor is the default and the bypass is the user's, in the GUI — but it is never silent."""
    monkeypatch.setattr("ai_sdlc_runner.tui.confirm_high_risk", lambda requested, floor: True)
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--review-seats", "1"])
    out = capsys.readouterr().out
    assert "relaxation:" in out
    assert "below the floor" in out


def test_declining_the_bypass_puts_the_floor_back(tmp_path, py_stub, monkeypatch, capsys):
    monkeypatch.setattr("ai_sdlc_runner.tui.confirm_high_risk", lambda requested, floor: False)
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--review-seats", "1"])
    out = capsys.readouterr().out
    assert "relaxation:" not in out
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_the_flag_alone_relaxes_the_floor_without_a_prompt(tmp_path, py_stub, monkeypatch, capsys):
    """`--high-risk-mode` *is* the decision, so asking again would be theatre."""
    def refuse(requested, floor):
        raise AssertionError("the operator was asked despite passing --high-risk-mode")

    monkeypatch.setattr("ai_sdlc_runner.tui.confirm_high_risk", refuse)
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path), "--confirm", "merge",
              "--review-seats", "1", "--high-risk-mode"])
    assert "relaxation:" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# effects
# --------------------------------------------------------------------------------------

def test_a_plan_with_no_ship_block_has_no_effects():
    assert cli.effects_provider(_plan()) is None


def test_the_ship_sequence_is_attached_to_the_pr_node_only(tmp_path):
    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b",
        "message": "CHG-20260823-01 do the thing", "chg_body": "# CHG-20260823-01\n",
    }))
    assert provider is not None
    assert [e.name for e in provider("pr")] == ["record-intent", "branch", "commit", "push", "pr"]
    assert provider("record_module") == ()


def test_every_effect_in_the_sequence_carries_a_probe_and_a_postcondition(tmp_path):
    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
        "chg_body": "# CHG\n",
    }))
    for effect in provider("pr"):
        assert callable(effect.probe)
        assert effect.postcondition


def test_shipping_without_the_intent_written_down_is_refused(tmp_path):
    """Intent first: a record written after the fact is one a crash can lose while what it describes
    has already landed."""
    from ai_sdlc_runner import ship

    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
    }))
    record_intent = provider("pr")[0]
    with pytest.raises(ship.ShipError) as exc:
        record_intent.apply()
    assert "chg_body" in str(exc.value)


def test_effects_run_at_their_node_and_are_reported(tmp_path):
    """The engine's hook, end to end: `record_module` says it carries out ordered effects, and now
    it does. Kept off the real git plumbing — this is about the wiring, not about git."""
    applied = []

    def provider(node_id):
        from ai_sdlc_runner import effects

        if node_id != "record_module":
            return ()
        return [effects.Effect(name="tick", probe=lambda: "tick" in applied,
                               apply=lambda: applied.append("tick"),
                               postcondition="the task is ticked")]

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none"], "feedback": "done"},
        risk="low", confirmed=("merge",), effects=provider)

    def dispatch(order):
        if order.get("seat"):
            return {"verdict": "pass"}
        branch = ANSWERS.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    report = engine.walk(cfg, dispatch, enabled=True)
    assert report.halted_at == "done"
    assert applied == ["tick"]
    assert report.effects["record_module"]["applied"] == ["tick"]


def test_an_effect_that_does_not_establish_its_postcondition_halts_the_run():
    """Marching past a step that silently did nothing is how a run reports green having done half
    the work."""
    def provider(node_id):
        from ai_sdlc_runner import effects

        if node_id != "record_module":
            return ()
        return [effects.Effect(name="tick", probe=lambda: False, apply=lambda: None,
                               postcondition="the task is ticked")]

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none"], "feedback": "done"},
        risk="low", confirmed=("merge",), effects=provider)

    report = engine.walk(cfg, lambda order: (
        {"verdict": "pass"} if order.get("seat")
        else ({"verdict": ANSWERS[order["node_id"]]} if order["node_id"] in ANSWERS
              else {"ok": True})), enabled=True)
    assert report.halted_at == "record_module"
    assert "effect failed" in report.halt_reason


# --------------------------------------------------------------------------------------
# the backend's answer has to be an answer
# --------------------------------------------------------------------------------------

def test_the_agents_json_reply_becomes_the_answer(tmp_path):
    """Capturing stdout is not answering: the engine routes on what the reply *said*."""
    script = tmp_path / "agent.py"
    script.write_text("import json,sys; json.load(sys.stdin); print(json.dumps({'verdict':'fail'}))",
                      encoding="utf-8")
    answer = cli._Process([sys.executable, str(script)], timeout=60).ask({"node_id": "qa_accept"})
    assert answer["verdict"] == "fail"


def test_the_agents_keys_win_over_the_process_metadata(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(
        "import json,sys; json.load(sys.stdin); print(json.dumps({'stderr':'mine','verdict':'pass'}))",
        encoding="utf-8")
    answer = cli._Process([sys.executable, str(script)], timeout=60).ask({"node_id": "qa_accept"})
    assert answer["stderr"] == "mine"


def test_a_reply_that_is_not_json_is_kept_rather_than_guessed_at(tmp_path):
    """The engine will refuse it for naming no branch, which names the node — better than this
    layer inventing a verdict out of prose."""
    script = tmp_path / "agent.py"
    script.write_text("import json,sys; json.load(sys.stdin); print('looks fine to me')",
                      encoding="utf-8")
    answer = cli._Process([sys.executable, str(script)], timeout=60).ask({"node_id": "qa_accept"})
    assert answer["stdout"].strip() == "looks fine to me"
    assert "verdict" not in answer


def test_an_agent_that_fails_answered_nothing_and_says_so(tmp_path):
    """A non-zero exit is a lost session, not a silent pass — and the journal keeps the question
    pending so it can be asked again."""
    script = tmp_path / "agent.py"
    script.write_text("import sys; sys.stderr.write('out of quota'); sys.exit(3)",
                      encoding="utf-8")
    with pytest.raises(cli.CliError) as exc:
        cli._Process([sys.executable, str(script)], timeout=60).ask({"node_id": "qa_accept"})
    assert "exited 3" in str(exc.value)
    assert "out of quota" in str(exc.value)


def test_a_lost_backend_leaves_the_question_on_disk(tmp_path, py_stub):
    """Session loss for a real backend, end to end: the ask is still pending afterwards."""
    argv = py_stub("import sys; sys.exit(1)")
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    journal = tmp_path / "asks"

    with pytest.raises(cli.CliError):
        cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path),
                  "--ask-journal", str(journal)])
    pending = engine.AskJournal(journal).pending()
    assert len(pending) == 1
    assert pending[0]["node_id"] == "pm_plan"


def test_the_fallback_reader_parses_an_inline_list(tmp_path, monkeypatch):
    """`agent_command` is documented as a list, and PyYAML is optional. A reader that split it on
    whitespace produced an argv beginning `["python",` — green on every developer machine, red on
    every CI runner, which is exactly where it happened."""
    path = tmp_path / "runner.yaml"
    path.write_text('agent_command: ["python", "agent.py", "--json"]\n', encoding="utf-8")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", no_yaml)
    assert cli.load_config(str(path))["agent_command"] == ["python", "agent.py", "--json"]


def test_a_malformed_inline_list_is_kept_as_text_rather_than_dropped(tmp_path, monkeypatch):
    path = tmp_path / "runner.yaml"
    path.write_text('agent_command: [oops\n', encoding="utf-8")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def no_yaml(name, *a, **kw):
        if name == "yaml":
            raise ImportError("no yaml")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", no_yaml)
    assert cli.load_config(str(path))["agent_command"] == "[oops"
