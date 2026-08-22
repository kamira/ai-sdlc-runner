"""A panel that is secretly one model has to say so (CHG-20260823-09).

The requirement asks for 多模型互審 — cross-model review — and gives the reason plainly: one model
cannot be relied on to see its own blind spots, so several review and their verdicts are adjudicated.

The mechanism was built (`--seat-model SEAT=COMMAND`) and it works. But a verifier pointed out what
happens when nobody uses it:

> 不給 `--seat-model` 時三席是同一個 command 答三次(session 獨立、模型不獨立),
> 沒有任何提示或紀錄說明本次面板是單模型。

Three sessions of one model are independent of each other's **context** and not of its **blind
spots**, and the blind spots are most of what the seats were bought for. Running that way is a
legitimate choice — it is the default, and it costs nothing. Running that way while the report reads
exactly like a cross-model panel is the false assurance this whole design exists against.

So it is **stated**, not refused: the run says which panels were answered by a single backend, and
the CLI prints it.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import engine, graph, policy

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _answer(order):
    if order.get("seat"):
        return {"verdict": "pass"}
    branch = ANSWERS.get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


class _Backend:
    """A factory whose sessions describe themselves, the way `cli._Process` does."""

    def __init__(self, per_seat=None, default="one-model"):
        self.per_seat, self.default = per_seat or {}, default

    def __call__(self, seat=None):
        name = self.per_seat.get(seat, self.default)

        class _S:
            def ask(self, order):
                return _answer(order)

            def close(self):
                pass

            def describe(self):
                return name

        return _S()


class _Undescribed:
    """A backend with no `describe()` — the fallback is the class name, which is still a signal."""

    def __call__(self, seat=None):
        class _S:
            def ask(self, order):
                return _answer(order)

            def close(self):
                pass

        return _S()


def _cfg(**kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow", confirmed=("merge",))
    base.update(kw)
    return engine.RunConfig(**base)


def test_one_backend_answering_every_seat_is_recorded():
    report = engine.walk(_cfg(), _Backend(), enabled=True)
    assert report.halted_at == "done"
    assert report.single_model_panels
    assert "lead_review" in report.single_model_panels[0]
    assert "the model was not" in report.single_model_panels[0]


def test_the_note_says_how_to_fix_it():
    """A disclosure that does not say what to do about it is a complaint."""
    report = engine.walk(_cfg(), _Backend(), enabled=True)
    assert "--seat-model" in report.single_model_panels[0]


def test_different_backends_per_seat_are_not_recorded():
    seats = policy.seat_names(policy.SEAT_FLOOR)
    per_seat = {seat: f"model-{i}" for i, seat in enumerate(seats)}
    report = engine.walk(_cfg(), _Backend(per_seat=per_seat), enabled=True)
    assert report.single_model_panels == []


def test_two_of_three_seats_sharing_a_model_is_not_flagged():
    """The note is about a panel with **no** diversity at all. Partial overlap is a judgement call
    the runner does not have the standing to make, and crying wolf about it would train people to
    ignore the line that matters."""
    seats = list(policy.seat_names(policy.SEAT_FLOOR))
    per_seat = {seats[0]: "model-a", seats[1]: "model-a", seats[2]: "model-b"}
    report = engine.walk(_cfg(), _Backend(per_seat=per_seat), enabled=True)
    assert report.single_model_panels == []


def test_a_backend_without_describe_still_gets_a_verdict():
    """Falling back to the class name means an unusual backend is not silently exempt."""
    report = engine.walk(_cfg(), _Undescribed(), enabled=True)
    assert report.single_model_panels


def test_the_note_does_not_change_the_panels_decision():
    """It is a disclosure, not a gate. A single-model panel still passes or fails on its verdicts —
    refusing to run would make the honest default unusable, and the requirement asks for the count
    to be the user's."""
    report = engine.walk(_cfg(), _Backend(), enabled=True)
    assert report.adjudications[0]["outcome"] == "pass"
    assert "qa_verify" in report.visited


def test_it_survives_into_the_reports_dict():
    report = engine.walk(_cfg(), _Backend(), enabled=True)
    assert report.as_dict()["single_model_panels"] == report.single_model_panels


def test_a_one_seat_panel_is_not_called_single_model():
    """One seat is a seat count the user chose and the run already records the floor bypass. Calling
    it "single model" as well would be two names for one fact."""
    report = engine.walk(_cfg(review_seats=1, high_risk_mode=True), _Backend(), enabled=True)
    assert report.single_model_panels == []
    assert any("below the floor" in r for r in report.relaxations)


# --------------------------------------------------------------------------------------
# the CLI carries it too
# --------------------------------------------------------------------------------------

def test_the_cli_prints_it(tmp_path, py_stub, capsys):
    import json

    from ai_sdlc_runner import cli

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
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low"}), encoding="utf-8")

    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", str(plan),
              "--confirm", "merge"])
    out = capsys.readouterr().out
    assert "single model:" in out
    assert "--seat-model" in out


def test_the_cli_does_not_print_it_when_seats_are_routed(tmp_path, py_stub, capsys):
    import json

    from ai_sdlc_runner import cli

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
    other = py_stub(agent, name="other.py")
    third = py_stub(agent, name="third.py")
    config = tmp_path / "runner.yaml"
    config.write_text(f"agent_command: {json.dumps(argv)}\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({
        "node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
        "decisions": {"next_module": ["module", "none"], "feedback": "done"},
        "risk": "low"}), encoding="utf-8")

    seats = list(policy.seat_names(policy.SEAT_FLOOR))
    cli.main(["--config", str(config), "run", "--undeclared", "allow", "--plan", str(plan),
              "--confirm", "merge",
              "--seat-model", f"{seats[1]}={' '.join(other)}",
              "--seat-model", f"{seats[2]}={' '.join(third)}"])
    assert "single model:" not in capsys.readouterr().out
