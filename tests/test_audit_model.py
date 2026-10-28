"""`--audit-model` and the plan's `audit_model` route the auditor (CHG-20261028-01, task 6).

Routed in the CLI only: `session_factory` picks the backend for `role == "auditor"`, the engine never
sees the flag. What the sessions then say they are is recorded as `RunReport.audit_same_backend` and
printed as `audit backend:`.
"""
from __future__ import annotations

import json
import sys

import pytest

from ai_sdlc_runner import cli, engine, models as models_mod, plan as plan_mod
from test_settings import _shipped

AGENT = """
import json, sys
order = json.load(sys.stdin)
if order.get("seat"):
    if order["node_id"] == "intake_review":
        print(json.dumps({"problems": [], "missing": [], "unsafe": []}))
    else:
        print(json.dumps({"verdict": "pass"}))
else:
    print(json.dumps({"ok": True}))
"""


def _line(argv):
    return " ".join(argv)


def _go(tmp_path, py_stub, capsys, *flags, plan_audit=None, extra=()):
    config, settings_file, plan = _shipped(tmp_path, py_stub)
    if plan_audit is not None:
        data = json.loads(open(plan, encoding="utf-8").read())
        data["audit_model"] = plan_audit
        open(plan, "w", encoding="utf-8").write(json.dumps(data))
    code = cli.main(["--config", config, "--settings", settings_file, "run", "--undeclared",
                     "allow", "--plan", plan, "--confirm", "merge", *flags, *extra])
    return code, capsys.readouterr().out


# ── the factory routes the auditor and only the auditor ─────────────────────────────────────────


def test_the_factory_runs_the_auditor_on_the_audit_command_and_nothing_else_on_it():
    config = {"agent_command": ["main", "agent"]}
    factory = cli.session_factory(config, audit_model="other agent --x")
    assert factory(role="auditor").argv == ["other", "agent", "--x"]
    assert factory(role="engineer").argv == ["main", "agent"]
    assert factory(seat="defect", role="seat").argv == ["main", "agent"]


def test_the_factory_resolves_a_registry_id_for_the_auditor():
    registry = models_mod.Registry([models_mod.Model(
        id="alpha", vendor="v", name="n", transport="cli", command=("codex", "exec"))])
    factory = cli.session_factory({"agent_command": ["main"]}, registry=registry,
                                  audit_model="alpha")
    assert factory(role="auditor").argv == ["codex", "exec"]


def test_without_an_audit_model_the_auditor_is_on_the_default_backend():
    factory = cli.session_factory({"agent_command": ["main", "agent"]})
    assert factory(role="auditor").argv == ["main", "agent"]


def test_a_plan_may_name_an_audit_model_and_may_not_name_it_empty():
    assert "audit_model" in plan_mod.FIELDS
    plan_mod.check({"audit_model": "codex exec"})          # accepted
    with pytest.raises(plan_mod.PlanError, match="audit_model"):
        plan_mod.check({"audit_model": ""})
    with pytest.raises(plan_mod.PlanError, match="audit_model"):
        plan_mod.check({"audit_model": ["codex"]})


# ── routed: a different backend counts toward the floor and is not flagged ──────────────────────


def test_a_routed_auditor_sizes_the_default_panel_at_two_and_is_not_flagged(tmp_path, py_stub, capsys):
    other = _line(py_stub(AGENT, "auditor.py"))
    code, out = _go(tmp_path, py_stub, capsys, "--audit-model", other)
    assert code == 0, out
    assert "opening 3 seats" not in out and "risk=pass" not in out
    assert "the auditor ran on the same backend" not in out


def test_the_plans_audit_model_routes_it_the_same_way(tmp_path, py_stub, capsys):
    other = _line(py_stub(AGENT, "auditor.py"))
    code, out = _go(tmp_path, py_stub, capsys, plan_audit=other)
    assert code == 0, out
    assert "opening 3 seats" not in out and "the auditor ran on the same backend" not in out


def test_the_flag_beats_the_plan(tmp_path, py_stub, capsys):
    """The plan names the builder's own backend; the flag names another. The flag decides."""
    main_cmd = json.loads(open(_shipped(tmp_path, py_stub)[0], encoding="utf-8").read()
                          .split("agent_command:", 1)[1])
    other = _line(py_stub(AGENT, "auditor.py"))
    code, out = _go(tmp_path, py_stub, capsys, "--audit-model", other, plan_audit=_line(main_cmd))
    assert code == 0, out
    assert "opening 3 seats" not in out


# ── recorded: the same backend as the builder, or as a seat ─────────────────────────────────────


def test_an_auditor_on_the_builders_backend_is_recorded_and_printed(tmp_path, py_stub, capsys):
    """Cut `_note_audit_backend` (or its print in `cmd_run`) and this finds nothing to match."""
    main_cmd = json.loads(open(_shipped(tmp_path, py_stub)[0], encoding="utf-8").read()
                          .split("agent_command:", 1)[1])
    code, out = _go(tmp_path, py_stub, capsys, "--audit-model", _line(main_cmd))
    assert code == 0, out
    assert "opening 3 seats" in out, "not independent, so the panel is sized up"
    assert "audit backend: the auditor ran on the same backend as the builder" in out


def test_an_auditor_on_a_seats_backend_is_recorded_as_a_seat_and_not_the_builder(
        tmp_path, py_stub, capsys):
    other = py_stub(AGENT, "auditor.py")
    code, out = _go(tmp_path, py_stub, capsys, "--audit-model", _line(other),
                    extra=["--seat-model", f"defect={_line(other)}"])
    assert code == 0, out
    assert "the auditor ran on the same backend as a review seat" in out
    assert "the auditor ran on the same backend as the builder" not in out


def test_the_engine_records_it_from_what_the_sessions_say_they_are():
    """No CLI: sessions that describe themselves. The record follows `describe()`, not the routing."""
    from test_flow import _cfg

    class Same(engine.Session):
        def __init__(self, name):
            self.name = name

        def describe(self):
            return self.name

        def ask(self, order):
            from test_flow import _answer
            return _answer(order)

        def close(self):
            pass

    def factory(seat=None, model=None, role="", **kw):
        return Same("shared-x" if role in ("auditor", "engineer") else "elsewhere")

    report = engine.walk(_cfg(review_seats=3), factory, enabled=True)
    assert any("same backend as the builder" in line for line in report.audit_same_backend)
    assert report.as_dict()["audit_same_backend"] == report.audit_same_backend
