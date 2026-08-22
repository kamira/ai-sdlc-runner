"""The engine's CLI flag and the GUI toggle that guards the seat floor (CHG-20260822-04 task 6).

Two things are checked here that the engine's own tests cannot: that the opt-in flag really is
opt-in at the command line, and that going below the shipped seat floor is a **decision the operator
sees themselves making** rather than a value in a file.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, engine, graph, tui

REPO_ROOT = Path(__file__).resolve().parents[1]
STORE = REPO_ROOT / "skills" / "v1.64.0"
TREE = REPO_ROOT / "elements" / "v1.64.0"

pytestmark = pytest.mark.skipif(
    not (STORE / "assets").is_dir() or not TREE.is_dir(),
    reason="vendored store or element tree not present in this checkout",
)

SPEC = {"scope": "src/", "objective": "o", "done_criteria": ["d"], "input_artifacts": [],
        "expected_outputs": [], "acceptance_predicate": "p", "idempotence_probes": [],
        "workdir": "."}
VERDICT = {"checkpoint": "halt:before_implement", "risk": "medium", "verdict": "auto",
           "source": "assets/halt_policy.json"}


def _plan(tmp_path, **overrides):
    plan = {
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "verdicts": {n.id: dict(VERDICT) for n in graph.NODES if n.role},
        "decisions": {"chg_confirmed": "yes", "plan_check": "pass", "next_task": "none",
                      "task_review": "pass", "re_review": "pass", "acceptance": "pass"},
        "languages": ["en"],
    }
    plan.update(overrides)
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return str(path)


def _argv(tmp_path, *extra):
    return ["run", ".", "--engine", "--plan", _plan(tmp_path),
            "--elements", str(TREE), "--skill-path", str(STORE), *extra]


# --------------------------------------------------------------------------------------
# the flag is genuinely opt-in
# --------------------------------------------------------------------------------------

def test_run_without_the_flag_does_not_enter_the_engine(monkeypatch):
    """D7: the four-stage path stays the default. If `--engine` is absent the engine is not even
    consulted, so turning it on has to be a deliberate act."""
    called = []
    monkeypatch.setattr(cli, "cmd_engine_run", lambda args: called.append(args) or 0)
    parser = cli.build_parser()
    args = parser.parse_args(["run", "."])
    assert args.engine is False


def test_the_flag_routes_into_the_engine(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(cli, "cmd_engine_run", lambda args: called.append(args) or 0)
    assert cli.main(_argv(tmp_path)) == 0
    assert len(called) == 1


def test_the_engine_needs_a_plan_and_says_why(capsys, tmp_path):
    """Refusing with a reason beats inventing per-node objectives the store cannot supply."""
    assert cli.main(["run", ".", "--engine", "--skill-path", str(STORE)]) == 2
    out = capsys.readouterr().out
    assert "--plan" in out and "task 7 reads them from the CHG" in out


# --------------------------------------------------------------------------------------
# a full walk through the command line
# --------------------------------------------------------------------------------------

def test_a_plan_walks_the_graph_to_close_out(capsys, tmp_path):
    assert cli.main(_argv(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "halted at:     close_out" in out
    assert "asks:" in out


def test_every_ask_is_journalled_when_a_journal_is_given(capsys, tmp_path):
    journal_dir = tmp_path / "journal"
    assert cli.main(_argv(tmp_path, "--ask-journal", str(journal_dir))) == 0
    written = sorted(p.name for p in journal_dir.glob("*.json"))
    assert written
    # each review seat has its own entry — three seats, three questions, three sessions
    seat_entries = [n for n in written if "branch_review" in n]
    assert len(seat_entries) == engine.seat_floor(STORE)
    assert len(set(seat_entries)) == len(seat_entries)


def test_an_engine_error_exits_ten_rather_than_pretending_to_succeed(capsys, tmp_path):
    plan = _plan(tmp_path, decisions={"chg_confirmed": "yes"})
    assert cli.main(["run", ".", "--engine", "--plan", plan, "--elements", str(TREE),
                     "--skill-path", str(STORE)]) == 10
    assert "engine:" in capsys.readouterr().out


# --------------------------------------------------------------------------------------
# the GUI toggle: the operator sees what going below the floor costs
# --------------------------------------------------------------------------------------

def test_the_toggle_defaults_to_keeping_the_floor():
    out = io.StringIO()
    assert tui.confirm_high_risk(1, 3, input_fn=lambda _p: "1", stream_out=out) is False
    assert "floor is 3" in out.getvalue()


def test_the_toggle_enables_high_risk_mode_only_when_chosen():
    out = io.StringIO()
    assert tui.confirm_high_risk(1, 3, input_fn=lambda _p: "2", stream_out=out) is True
    assert "below the floor" in out.getvalue()
    assert "records that it did" in out.getvalue()


def test_cancelling_the_toggle_is_a_no():
    """Cancel means the floor stands. A relaxation nobody chose is not a relaxation."""
    out = io.StringIO()
    assert tui.confirm_high_risk(1, 3, input_fn=lambda _p: "", stream_out=out) is False


def test_the_cli_flag_reaches_the_engine_without_the_prompt(capsys, tmp_path):
    """`--high-risk-mode` is the non-interactive equivalent, and the run still records it."""
    assert cli.main(_argv(tmp_path, "--review-seats", "1", "--high-risk-mode")) == 0
    out = capsys.readouterr().out
    assert "relaxation:" in out
    assert "below the shipped floor" in out


def test_more_seats_than_the_floor_needs_no_toggle(capsys, tmp_path):
    assert cli.main(_argv(tmp_path, "--review-seats", "3")) == 0
    assert "relaxation:" not in capsys.readouterr().out
