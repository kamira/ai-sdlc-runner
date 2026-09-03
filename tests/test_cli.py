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

import ast
import contextlib
import io
import json
import pathlib
import inspect
import re
import sys
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, conversations as conv_mod, engine, graph, policy, settings as settings_mod, workorder

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

    code = cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
                     "--confirm", "merge"])
    out = capsys.readouterr().out
    assert code == 0
    assert "stopped at:    done" in out


def test_the_panel_result_is_reported_with_every_seats_verdict(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--confirm", "merge"])
    out = capsys.readouterr().out
    assert "panel:         lead_review → pass" in out
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_confirm_reaches_the_engine_and_is_reported(tmp_path, py_stub, capsys):
    """A `--confirm` the engine never sees is a switch wired to nothing."""
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow",
              "--plan", _plan_file(tmp_path, risk="medium"), "--confirm", "plan_confirmed"])
    out = capsys.readouterr().out
    assert "confirmed:" in out and "plan_confirmed" in out
    # One gate confirmed is one gate confirmed: the next one still stops the run.
    assert "stopped at:    lead_assess" in out


def test_without_the_confirmation_the_same_run_stops_at_the_first_gate(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path, risk="medium")])
    assert "stopped at:    pm_confirm" in capsys.readouterr().out


def test_a_plans_operations_reach_the_permanent_halts(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    plan = _plan_file(tmp_path, operations={
        "engineer_build": [{"description": "promote the build to live", "kind": "deploy"}]})
    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", plan])
    out = capsys.readouterr().out
    assert "stopped at:    engineer_build" in out
    assert "production deploy" in out


def test_risk_on_the_command_line_overrides_the_plan(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--risk", "medium"])
    assert "stopped at:    pm_confirm" in capsys.readouterr().out


def test_a_seat_model_on_the_command_line_routes_that_seat(tmp_path, py_stub, capsys):
    """FR-14 from the command line: the same question, a different answerer. The docs claimed this
    flag before it existed, which a verifier caught."""
    argv = py_stub(AGENT)
    other = py_stub(AGENT, name="other.py")
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    code = cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
                     "--confirm", "merge", "--seat-model", f"conformance={' '.join(other)}"])
    assert code == 0
    assert "panel:         lead_review → pass" in capsys.readouterr().out


def test_a_seat_model_naming_an_unknown_seat_is_refused(tmp_path, capsys):
    code = cli.main(["run", "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--seat-model", "nobody=x"])
    assert code == 2
    assert "no seat 'nobody'" in capsys.readouterr().out


def test_a_seat_model_without_a_command_is_refused(tmp_path, capsys):
    code = cli.main(["run", "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--seat-model", "conformance"])
    assert code == 2
    assert "SEAT=COMMAND" in capsys.readouterr().out


def test_seats_is_accepted_as_well_as_review_seats(tmp_path, py_stub, monkeypatch, capsys):
    monkeypatch.setattr("ai_sdlc_runner.tui.confirm_high_risk", lambda requested, floor: True)
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--seats", "1"])
    assert "relaxation:" in capsys.readouterr().out


def test_the_order_reaches_the_backend_deterministically_serialised(tmp_path):
    """`workorder.to_json` had no caller at all — sorted keys and LF are the point of it, and the
    dispatcher is where an order becomes bytes."""
    script = tmp_path / "agent.py"
    script.write_text(
        "import json, sys\n"
        "raw = sys.stdin.read()\n"
        "print(json.dumps({'verdict': 'pass', 'raw_len': len(raw)}))\n",
        encoding="utf-8")
    session = cli._Process([sys.executable, str(script)], timeout=60)
    order = workorder.render(graph.BY_ID["engineer_build"], SPEC,
                             policy.verdict("self_verify", "low"))
    assert session.ask(order)["raw_len"] == len(workorder.to_json(order))


def test_the_agent_reads_the_order_in_the_codec_it_was_written_in(tmp_path, monkeypatch):
    """The order goes out as UTF-8, so the agent has to be told to read UTF-8 (CHG-20260828-16).

    Left to itself a Python child decodes stdin with the machine's locale. On cp950 the CJK in this
    order's `role_label` came back as six characters where three were sent — no error anywhere, and
    an agent answering a question subtly different from the one asked.

    The environment is cleared first because inheriting it would make this assert something about
    whoever ran the test rather than about the dispatcher.
    """
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    script = tmp_path / "agent.py"
    script.write_text(
        "import json, sys\n"
        "raw = sys.stdin.read()\n"
        "print(json.dumps({'verdict': 'pass', 'wide': sum(1 for c in raw if ord(c) > 127)}))\n",
        encoding="utf-8")
    session = cli._Process([sys.executable, str(script)], timeout=60)
    order = workorder.render(graph.BY_ID["engineer_build"], SPEC,
                             policy.verdict("self_verify", "low"))
    sent = sum(1 for c in workorder.to_json(order) if ord(c) > 127)
    assert sent, "the order stopped carrying any non-ASCII, so this test proves nothing"
    assert session.ask(order)["wide"] == sent


def test_an_engine_error_is_reported_rather_than_raised(tmp_path, capsys):
    """A plan whose branches do not cover the flow is the operator's mistake, and they get told."""
    plan = _plan_file(tmp_path, decisions={})
    assert cli.main(["run", "--undeclared", "allow", "--plan", plan]) == 10
    assert "halted:" in capsys.readouterr().out


def test_the_journal_is_written_where_the_flag_says(tmp_path, py_stub):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    journal = tmp_path / "asks"

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
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

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--review-seats", "1"])
    out = capsys.readouterr().out
    assert "relaxation:" in out
    assert "below the floor" in out


def test_declining_the_bypass_puts_the_floor_back(tmp_path, py_stub, monkeypatch, capsys):
    monkeypatch.setattr("ai_sdlc_runner.tui.confirm_high_risk", lambda requested, floor: False)
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path),
              "--confirm", "merge", "--review-seats", "1"])
    out = capsys.readouterr().out
    # An undeclared dry run reports its own relaxation, so look for the *seat* one specifically.
    assert "below the floor" not in out
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

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--confirm", "merge",
              "--review-seats", "1", "--high-risk-mode"])
    assert "relaxation:" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# effects
# --------------------------------------------------------------------------------------

def test_a_plan_with_no_ship_block_has_no_effects():
    assert cli.effects_provider(_plan()) is None


def test_the_ship_sequence_is_attached_to_the_pr_node(tmp_path):
    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b",
        "message": "CHG-20260823-01 do the thing", "chg_body": "# CHG-20260823-01\n",
    }))
    assert provider is not None
    assert [e.name for e in provider("pr")] == ["record-intent", "branch", "commit", "push", "pr"]
    assert provider("qa_verify") == ()


def test_record_module_carries_effects_when_the_plan_names_a_task(tmp_path):
    """The node's own note says it ticks and records. Until `ship.record_effects` existed, that
    sentence was a comment on a node that did nothing, and `probes.task_ticked` had no caller."""
    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
        "chg_body": "# CHG\n", "task": "3", "acc_id": "ACC-20260823-01", "acc_body": "# ACC\n",
    }))
    assert [e.name for e in provider("record_module")] == ["tick", "acceptance"]


def test_without_a_task_record_module_carries_none(tmp_path):
    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
        "chg_body": "# CHG\n",
    }))
    assert provider("record_module") == []


def test_the_runner_will_not_tick_a_task_on_the_leads_behalf(tmp_path):
    """A tick is a judgement written into the ledger. The probe reads the file, so a resumed run
    finds it done — but the runner does not write it."""
    from ai_sdlc_runner import ship

    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
        "chg_body": "# CHG\n", "task": "3",
    }))
    with pytest.raises(ship.ShipError) as exc:
        provider("record_module")[0].apply()
    assert "not something this runner writes" in str(exc.value)


def test_an_acceptance_record_with_no_evidence_is_refused(tmp_path):
    from ai_sdlc_runner import ship

    provider = cli.effects_provider(_plan(ship={
        "repo": str(tmp_path), "chg_id": "CHG-20260823-01", "branch": "b", "message": "m",
        "chg_body": "# CHG\n", "task": "3", "acc_id": "ACC-20260823-01",
    }))
    with pytest.raises(ship.ShipError) as exc:
        provider("record_module")[1].apply()
    assert "false green" in str(exc.value)


def test_the_commit_effect_is_not_done_while_the_tree_is_dirty(tmp_path, monkeypatch):
    """A commit that exists while changes are still uncommitted did not finish recording the
    change, and a resume that treats it as done pushes half of it."""
    from ai_sdlc_runner import probes, ship

    monkeypatch.setattr(probes, "commit_exists_for", lambda *a, **kw: True)
    monkeypatch.setattr(probes, "working_tree_clean", lambda *a, **kw: False)
    sequence = ship.effects_for(repo=str(tmp_path), chg_id="CHG-1", branch="b", message="m",
                                write_chg=lambda: None)
    commit = next(e for e in sequence if e.name == "commit")
    assert commit.probe() is False


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
        risk="low", confirmed=("merge",), effects=provider, undeclared="allow",
        operations={"record_module": [{"description": "tick the box", "kind": "ordinary"}]})

    def dispatch(order):
        if order.get("seat"):
            return {"verdict": "pass"}
        if order["node_id"] == "engineer_build":
            # A builder says what it built (CHG-20260828-15) — `record_module` is reached only
            # through `module_built`, and this test is about the node running.
            return {"module": "alpha"}
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
        risk="low", confirmed=("merge",), effects=provider, undeclared="allow",
        operations={"record_module": [{"description": "tick the box", "kind": "ordinary"}]})

    # A builder says what it built (CHG-20260828-15). `record_module` is reached only through
    # `module_built`, so a stub reporting nothing takes the empty path — and this test is about
    # what happens when the node's effect runs and fails.
    report = engine.walk(cfg, lambda order: (
        {"verdict": "pass"} if order.get("seat")
        else {"module": "alpha"} if order["node_id"] == "engineer_build"
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


def test_a_lost_backend_leaves_the_question_on_disk(tmp_path, py_stub, capsys):
    """Session loss for a real backend, end to end: the ask is still pending afterwards, and the
    run says so. `AskJournal.pending()` had no reader outside the tests until it did — a question
    preserved where nobody looks is preserved the way a backup nobody restores is."""
    argv = py_stub("import sys; sys.exit(1)")
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    journal = tmp_path / "asks"

    code = cli.main(["--config", str(config), "run", "--undeclared", "allow",
                     "--plan", _plan_file(tmp_path), "--ask-journal", str(journal)])
    out = capsys.readouterr().out
    assert code == 10
    assert "halted:" in out
    assert "still to ask:  intake_review" in out

    pending = engine.AskJournal(journal).pending()
    assert len(pending) == 1
    # `intake_review` asks first now, so it is the question left on disk.
    assert pending[0]["node_id"] == "intake_review"


def test_a_run_that_finishes_has_nothing_left_to_ask(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    journal = tmp_path / "asks"

    cli.main(["--config", str(config), "run", "--undeclared", "allow",
              "--plan", _plan_file(tmp_path), "--confirm", "merge", "--ask-journal", str(journal)])
    assert "still to ask:" not in capsys.readouterr().out


def test_undeclared_defaults_to_refusing(tmp_path, py_stub, capsys):
    """The command line's default is the engine's default: silence is not a declaration."""
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--plan", _plan_file(tmp_path)])
    out = capsys.readouterr().out
    assert "stopped at:    intake_review" in out
    assert "declares no operations" in out


# --------------------------------------------------------------------------------------
# settings, from the command line
# --------------------------------------------------------------------------------------

def test_settings_show_prints_the_current_state(capsys, tmp_path):
    assert cli.main(["--settings", str(tmp_path / "none.json"), "settings", "--show"]) == 0
    out = capsys.readouterr().out
    assert "review seats: 3" in out
    assert "high-risk mode: off" in out


def test_settings_show_warns_when_running_below_the_floor(capsys, tmp_path):
    """A bypass has to be visible to somebody who never opens a menu — in CI, in a log, in a review
    of what this project is configured to do."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": 1, "high_risk_mode": True}), encoding="utf-8")
    cli.main(["--settings", str(path), "settings", "--show"])
    out = capsys.readouterr().out
    assert "high-risk mode: ON" in out
    assert "warning:" in out and "below the review floor" in out


def test_a_broken_settings_file_stops_the_command_rather_than_defaulting(capsys, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    assert cli.main(["--settings", str(path), "settings", "--show"]) == 2
    assert "not valid JSON" in capsys.readouterr().out


def test_a_broken_settings_file_stops_a_run_too(capsys, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    assert cli.main(["--settings", str(path), "run", "--plan", _plan_file(tmp_path)]) == 2
    assert "not valid JSON" in capsys.readouterr().out


def test_a_run_reads_the_saved_settings(tmp_path, py_stub, capsys):
    """The point of persisting them: the seat count is a property of the project, not something
    retyped every run."""
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"review_seats": 1, "high_risk_mode": True}),
                             encoding="utf-8")

    cli.main(["--config", str(config), "--settings", str(settings_file), "run",
              "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--confirm", "merge"])
    out = capsys.readouterr().out
    assert "relaxation:" in out and "below the floor" in out


def test_a_flag_beats_the_saved_settings(tmp_path, py_stub, capsys):
    """Someone typing `--seats` now is deciding about this run; the file is the standing decision.
    Neither is silent — whichever produces a floor crossing, the run records it."""
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"review_seats": 1, "high_risk_mode": True}),
                             encoding="utf-8")

    cli.main(["--config", str(config), "--settings", str(settings_file), "run",
              "--undeclared", "allow", "--plan", _plan_file(tmp_path), "--confirm", "merge",
              "--seats", "3"])
    out = capsys.readouterr().out
    # An undeclared dry run has relaxations of its own, so look for the *seat* one specifically.
    assert "below the floor" not in out
    for seat in policy.seat_names(policy.SEAT_FLOOR):
        assert f"{seat}=pass" in out


def test_an_unverified_operation_is_printed(tmp_path, py_stub, capsys):
    argv = py_stub(AGENT)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    plan = _plan_file(tmp_path, operations={
        "engineer_build": [{"description": "rename a variable", "kind": "ordinary"}]})

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", plan,
              "--confirm", "merge"])
    assert "unverified:" in capsys.readouterr().out


def _docstring_nodes(tree):
    """Every string node that is a docstring, so prose about the runner is not read as an order."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                yield body[0].value


def test_every_command_the_cli_tells_you_to_run_exists():
    """A refusal that names a command nobody can run is worse than one that names none.

    Three refusals in one round pointed somewhere they did not go: a secret scan naming the query
    string for a credential in the fragment, a ledger lint offering "say the test was removed"
    when saying so was still refused, and this file telling an operator whose console will not
    start to run `runner models`, which has never been a subcommand (CHG-20260831-03).

    Backticked only, like the ledger lint's test-name pointer: prose that mentions the runner in
    passing is not an instruction, and this file discusses the runner constantly.
    """
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    docstrings = {id(d) for d in _docstring_nodes(tree)}

    # Backticked prose **and** every string literal that is not a docstring. Backticks alone read
    # two mentions in comments and missed all eight subcommands the file actually prints, including
    # `cli.py`'s own `runner emergencies --reviewed ID --by NAME` — so the check could not see the
    # shape it exists for: an instruction an operator is handed (CHG-20260831-04, defect seat).
    named = set(re.findall(r"`runner ([a-z][a-z-]*)",
                           Path(cli.__file__).read_text(encoding="utf-8")))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            # Line start only. An arm matching anywhere on a line that also carries a `--` was
            # added for a mid-sentence instruction and was measured **dead** — it contributed no
            # name the other two did not already have — while its comment cited a string that is
            # not in this file, and it read ordinary prose as commands: `"the runner writes each
            # answer; pass --ask-journal"` yielded `['writes']` (CHG-20260831-06, defect and risk
            # seats). Removed rather than tuned: a heuristic that fires on prose turns this test
            # into a tax on writing refusals, which is the opposite of what it is for.
            #
            # The gap it leaves is disclosed, not closed: an instruction printed mid-sentence and
            # unbackticked is invisible here. Backtick it, or start its line with it.
            named |= set(re.findall(r"^\s*runner ([a-z][a-z-]*)", node.value, re.MULTILINE))
    named = sorted(named)
    # Three is what the file names today, and the guard exists so a scan that has silently
    # stopped reading anything is not mistaken for a clean result. Backticks alone yielded two —
    # `conversations`, from a printed refusal rather than a comment, and `run` — and missed the
    # printed `runner emergencies --reviewed ID --by NAME` entirely, which is what the line-start
    # arm is for (CHG-20260831-05, defect and idiom seats).
    assert len(named) >= 3, f"the scan sees only {named}, so it has stopped reading"

    parser = cli.build_parser()
    real = set(next(a.choices for a in parser._actions if a.choices))
    ghosts = [c for c in named if c not in real]
    assert not ghosts, (
        f"cli.py tells the operator to run {ghosts}, and {sorted(real)} is every command there is")


def test_a_stored_model_a_widened_rule_refuses_stops_serve_with_a_remedy(tmp_path, capsys):
    """The third of CHG-20260831-03's three refusals, and the one that had no test on its message.

    `store.load_registry` rebuilds a `Registry`, and `__post_init__` re-validates every row — so a
    refusal widened after a model was stored fires on **load**. `ModelError` is not a `StoreError`,
    so it used to leave `cmd_serve` as a traceback. The handler was added with a source-grep test
    that never executed it; this drives it (CHG-20260831-04, conformance seat, VETO).

    The row is written straight into sqlite because that is the only way to reach the state: no
    version of `validate` would accept it, which is also why the refusal must not claim the rule was
    widened after this particular row was written.
    """
    from ai_sdlc_runner import store as store_mod

    db_path = tmp_path / "config.sqlite"
    db = store_mod.connect(db_path)
    db.execute(
        "INSERT INTO models (id, vendor, name, transport, command_json, endpoint, key_env, note) "
        "VALUES ('svc', 'v', 'n', 'api', '[]', 'https://svc-token@gpu-box/v1', 'K', '')")
    db.commit()

    code = cli.main(["serve", "--plan", _plan_file(tmp_path),
                     "--assignment-store", str(db_path),
                     "--token-dir", str(tmp_path / "tok")])
    said = capsys.readouterr().out

    assert code == 2, said
    assert str(db_path) in said, f"the remedy has to name the file that holds the row: {said!r}"
    assert "svc" in said, "and which model"
    # The **table names**, not the word "assignment" — which the fourth sentence of the message
    # contains anyway, so the loop that stood here passed with the warning's names replaced by
    # nonsense (CHG-20260831-05, conformance seat). And they are the real tables: the first draft
    # named `seat_models` and `node_models`, which are function names in `store.py`, so an operator
    # following it got `no such table` (risk seat).
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("seat_assignments", "node_assignments"):
        assert table in tables, f"{table} is not a table in this store; the remedy would misdirect"
        assert table in said, (
            f"deleting the row orphans {table} rows pointing at it, and the console then starts "
            f"clean and says nothing. The remedy has to name the table: {said!r}")


#: Answers `intake_review` with an aspect this runner does not define. Everything else behaves.
INTAKE_STRANGER = """
import json, sys
order = json.load(sys.stdin)
if order["node_id"] == "intake_review":
    print(json.dumps({"missing": ["database"], "seat": order.get("seat")}))
elif order.get("seat"):
    print(json.dumps({"verdict": "pass", "seat": order["seat"]}))
else:
    print(json.dumps({"ok": True}))
"""


def test_a_requirement_naming_an_undefined_aspect_is_reported_rather_than_raised(
        tmp_path, py_stub, capsys):
    """`IntakeError` was not in `cmd_run`'s except tuple, so it left as a traceback.

    A seat saying `"database"` is missing has answered a question this runner did not ask —
    `intake.collect` refuses it with a sentence written for a person. `cmd_run` caught
    `EngineError`, `PolicyError`, `CliError`, `SandboxError` and `WorktreeError`, and `IntakeError`
    is a bare `Exception`, so the run died with a Python stack on stderr and **exit 1**
    (CHG-20260901-17, defect seat).

    Exit 10 matters beyond tidiness: it is the one halt code this CLI returns, and the skipped
    branch is also where `_report_pending` and `_close_trees(..., keep=True)` live — so a
    `--worktree` run leaked its trees on the one path whose own comment says the tree is where the
    evidence is.
    """
    argv = py_stub(INTAKE_STRANGER)
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    plan = _plan_file(tmp_path)

    code = cli.main(["--config", str(config), "run", "--plan", plan, "--risk", "low",
                     "--undeclared", "allow", "--ask-journal", str(tmp_path / "asks")])

    out = capsys.readouterr().out
    assert code == 10, f"expected the halt code, got {code}"
    assert "halted:" in out, out
    assert "database" in out, "the message must name the aspect the seat invented"


# ── one subcommand shadowed a global flag and threw away what the operator typed ────────────────


def _parser():
    return cli.build_parser() if hasattr(cli, "build_parser") else cli._parser()


def test_the_settings_flag_reaches_every_subcommand_that_takes_one():
    """`serve` re-declared `--settings` with a default, applied after the global, so:

        runner --settings /tmp/CUSTOM.json settings  ->  /tmp/CUSTOM.json
        runner --settings /tmp/CUSTOM.json run       ->  /tmp/CUSTOM.json
        runner --settings /tmp/CUSTOM.json serve     ->  config/settings.json

    The shadow was added for a real reason — `default=None` reached `Path(None)` and killed
    `runner serve` in its plainest form — and the fix reached for the wrong constant. Every
    subcommand, not the one that broke, because one shadowed subparser was enough to lose it
    (CHG-20260903-28, found by the defect seat).
    """
    parser = _parser()
    chosen = "/tmp/CUSTOM.json"

    for sub in ("settings", "run", "serve"):
        namespace = parser.parse_args(["--settings", chosen, sub])
        assert getattr(namespace, "settings", None) == chosen, sub


def test_the_plainest_form_still_gets_the_default_and_a_later_flag_still_wins():
    """Both halves of what the shadow existed to protect, so the fix cannot regress into either."""
    parser = _parser()

    assert str(parser.parse_args(["serve"]).settings) == str(settings_mod.DEFAULT_PATH)
    assert parser.parse_args(["serve", "--settings", "/tmp/AFTER.json"]).settings == "/tmp/AFTER.json"


# ── every edge in the graph reaches the operator (CHG-20260903-31) ─────────────────────────────


def test_runner_flow_prints_every_edge_the_graph_has():
    """`cmd_flow` iterated `node.branches` only, so 15 of the graph's 40 edges were invisible.

    A node with no branches printed a line with no successor at all, leaving the reader to infer
    one from the **listing order** — which disagrees with the graph at three nodes:

        pm_plan         read as pm_confirm    goes to plan_scope
        record_module   read as fix_pass      goes to next_module
        review_failed   read as qa_verify     goes to change_retry

    This command's own help calls it the fastest way to see what the runner will actually do
    (CHG-20260903-31, found by the defect seat).
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cli.main(["flow"])
    printed = buffer.getvalue()

    in_graph = (sum(len(node.branches) for node in graph.NODES)
                + sum(1 for node in graph.NODES if getattr(node, "next", None)))
    drawn = sum(1 for line in printed.splitlines() if "\u2192" in line)

    assert drawn == in_graph, f"the graph has {in_graph} edges and `flow` printed {drawn}"


def test_the_three_nodes_that_read_backwards_now_name_their_successor():
    """Named, because the count above would pass if `flow` printed fifteen edges of any kind.

    These are the three whose printed position implied the wrong node.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cli.main(["flow"])
    printed = buffer.getvalue()

    lines = printed.splitlines()
    for node_id, goes_to in (("pm_plan", "plan_scope"),
                             ("record_module", "next_module"),
                             ("review_failed", "change_retry")):
        at = next(i for i, line in enumerate(lines) if line.startswith(node_id + " "))
        follows = " ".join(lines[at + 1:at + 4])
        assert goes_to in follows, (
            f"{node_id} does not name {goes_to}; it is followed by {follows!r}")


# ── every export format the runner has is named where a person looks (CHG-20260903-32) ─────────


def test_every_export_format_is_named_in_the_help():
    """`--help` advertised *"JSON, Markdown or CSV"* against a five-entry `FORMATS`.

    The two it hid — `html` and `playback` — are the only two that render the walk. Derived from
    the tuple now, so the sentence cannot drift from it again.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            _parser().parse_args(["--help"])
        except SystemExit:
            pass
    printed = buffer.getvalue()

    missing = [name for name in conv_mod.FORMATS if name not in printed]

    assert missing == [], f"these formats work and `runner --help` does not name them: {missing}"


# ── the grade a panel decides reaches the terminal (CHG-20260903-48) ─────────────────────

def test_two_panels_that_graded_differently_do_not_print_the_same_line():
    """**The defect, as a person at the terminal met it** (CHG-20260903-48, defect seat L-14).

    `adjudicate_grade` returns `outcome="pass"` for **every** grade it settles, and the footer
    printed `outcome` alone — so a run whose panel graded the change `high` and one graded `low`
    produced byte-identical output. CHG-20260901-18's own title is *"the grade a panel decides
    reached nothing that names it"*; the console was fixed and the terminal was not.

    Asserting the two lines **differ** rather than pinning either wording: the claim is that the
    grade is distinguishable, not that it is spelled any particular way.
    """
    from ai_sdlc_runner import policy

    high = policy.adjudicate_grade({"m1": "high", "m2": "high"})
    low = policy.adjudicate_grade({"m1": "low", "m2": "low"})
    assert high["outcome"] == low["outcome"] == "pass", (
        "this test exists because the outcomes are identical; if they differ now, the footer "
        "could print `outcome` again and this test would stop meaning anything")

    def line(decision):
        said = decision.get("grade") or decision.get("outcome") or "?"
        return f"panel:         lead_assess → {said}"

    assert line(high) != line(low), (
        "a panel that graded the change high and one that graded it low print the same line")
    assert "high" in line(high) and "low" in line(low)


def test_the_terminal_and_the_console_name_the_same_thing():
    """**One adjudication, two surfaces, one answer.**

    The console has read `a.grade || a.outcome` since CHG-20260901-18. The terminal read `outcome`
    alone until this record. They are different languages, so the guard is that both carry the same
    precedence rather than that both call one function.
    """
    page = (pathlib.Path(cli.__file__).parent / "console" / "index.html").read_text(
        encoding="utf-8")
    assert "a.grade || a.outcome" in page, (
        "the console stopped preferring the grade; if that is deliberate the terminal is the other "
        "half to change")

    source = inspect.getsource(cli)
    assert 'decision.get("grade") or decision.get("outcome")' in source, (
        "the terminal no longer prefers the grade the way the console does")


def test_the_settled_grade_reaches_a_terminal_line():
    """`risk_settled` reached `--json` and the console and no terminal line at all — `cli.py` named
    `risk_agreed`, `risk_settled` and `risk_proposed` zero times (CHG-20260903-48).

    **Checked as the condition, not as the text.** The first version of this asserted
    `"risk_settled" in inspect.getsource(cli)`, and the mutation that replaced the guarding `if`
    with `if False` left it **green**: the string was still there and could never be reached. That
    is the wording-instead-of-property trap, written ten minutes after ACC-20260903-47 recorded the
    fourth instance of it. A behavioural version needs a grading panel driven through the CLI with
    a model registry; this asserts the weaker but honest thing — the line is conditioned on the
    value it reports, so a constant condition fails.
    """
    import ast

    fn = next(n for n in ast.walk(ast.parse(pathlib.Path(cli.__file__).read_text(
        encoding="utf-8"))) if isinstance(n, ast.FunctionDef) and n.name == "cmd_run")

    guarded = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        prints = any(isinstance(c, ast.Call) and getattr(c.func, "id", None) == "print"
                     and "risk_settled" in ast.dump(c) for c in ast.walk(node))
        if prints:
            guarded.append(any(isinstance(a, ast.Attribute) and a.attr == "risk_settled"
                               for a in ast.walk(node.test)))

    assert guarded, "no terminal line reports the grade the run ended up governed by"
    assert all(guarded), (
        "the line reporting the settled grade is behind a condition that does not mention it — a "
        "constant condition prints never or always, and neither is reporting")


def test_the_old_guards_could_not_have_caught_this():
    """Recorded as a measurement rather than a claim: the two tests that pin the footer's panel line
    both use `lead_review`, a **seat** panel, whose adjudication carries no `grade` — so they were
    green either way. A guard over the shape a defect cannot reach is not a guard against it."""
    from ai_sdlc_runner import policy

    seat_panel = policy.adjudicate({s.name: "pass" for s in policy.SEATS[:2]})
    assert "grade" not in seat_panel, (
        "a seat panel now carries a grade, so the existing footer tests do exercise this path and "
        "this note should be revisited")


# ── the terminal reads all three suspension shapes (CHG-20260904-02) ──────────────────────────

def _incomplete_stop():
    """A run that ends waiting for a requirement nobody has finished."""
    from test_flow import DECISIONS, SPEC

    def factory(seat=None, model=None, **_):
        class Session(engine.Session):
            def ask(self, order):
                if order["node_id"] == "intake_review":
                    return {"missing": ["architecture"], "problems": []}
                return {"verdict": "pass"} if seat else {"ok": True}

            def close(self):
                pass
        return Session()

    cfg = engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                           decisions=dict(DECISIONS), risk="low", undeclared="allow")
    return engine.walk(cfg, factory, enabled=True)


def test_the_terminal_does_not_offer_a_control_that_cannot_answer_the_question():
    """**Three shapes, not two** (CHG-20260904-02, defect seat L-17).

    `intake_review.gate` is `None`, so the gate branch printed `--resume --confirm None` at an
    incomplete stop and the engine answered *"confirmed gate 'None' does not exist"*. The tie
    branch three lines above carries the objection verbatim: *"Offering `--confirm` here would be
    offering a control that cannot answer what is being asked."*

    Asserted as the **round trip** — whatever the terminal tells the operator to type is handed
    back to the engine — rather than as a wording, because the claim is that the advice works.
    """
    report = _incomplete_stop()
    stop = report.suspended or {}
    assert stop.get("incomplete") and stop.get("gate") is None, (
        f"this test needs the third shape; got {stop}")

    source = inspect.getsource(cli)
    assert 'elif stop.get("incomplete"):' in source, (
        "the terminal reads two suspension shapes again")

    # The round trip: the engine refuses the command the old branch printed.
    from test_flow import DECISIONS, SPEC
    with pytest.raises(engine.EngineError, match="does not exist"):
        engine.walk(engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions=dict(DECISIONS), risk="low", undeclared="allow",
            confirmed=(str(stop.get("gate")),)), lambda **_: None, enabled=True)


def test_the_incomplete_branch_says_what_is_missing_and_offers_no_gate(tmp_path, py_stub, capsys):
    """What the operator is actually told, read off the terminal rather than out of the source.

    The first version of this asserted strings against `inspect.getsource(cli)` — the
    wording-instead-of-property trap this ledger has corrected five times, written into the guard
    for a defect that is *about* what a person reads. This runs the command.
    """
    stub = py_stub("""
import json, sys
order = json.load(sys.stdin)
if order["node_id"] == "intake_review":
    print(json.dumps({"missing": ["architecture"], "problems": []}))
elif order.get("seat"):
    print(json.dumps({"verdict": "pass", "seat": order["seat"]}))
else:
    print(json.dumps({"ok": True}))
""")
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(stub)}\n", encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow",
              "--plan", _plan_file(tmp_path)])
    out = capsys.readouterr().out

    assert "--confirm None" not in out, (
        f"the terminal told the operator to type a command the engine refuses:\n{out}")
    assert "a decision on None" not in out, out
    # **The line, not the word.** `architecture` also appears in the `reason` line this branch
    # prints, so `"architecture" in out` passed even with the "waiting for" line reduced to
    # "the requirement" — the mutation found it (CHG-20260904-02).
    waiting = [line for line in out.splitlines() if line.startswith("waiting for:")]
    assert waiting, f"the terminal says nothing about what it is waiting for:\n{out}"
    assert "architecture" in waiting[0], (
        f"the line that says what the run is waiting for does not name the missing aspect: "
        f"{waiting[0]!r}")
    assert "no gate here to confirm" in out, (
        f"the terminal does not say why `--confirm` is not the control here:\n{out}")
