"""One grade for a whole programme flattens what the gates are for (CHG-20260827-18).

`RunConfig.risk` was one scalar and `resolve_verdict` read it for **every** gate. At small scale that
is right: one change, one grade. At the shape now targeted, one instruction becomes several
workstreams — a schema change, a copy tweak and a payment path are not the same risk.

## The two failures, and why they mean the shape is wrong rather than the value

With one scalar, either

* the copy tweak drags the whole run to `high` — ceremony nobody needed, and the kind that gets
  routed around; or
* the schema change rides along at `low` — the gate that exists for exactly it never fires.

They fail in **opposite directions**. No single value fixes both, which is the sign the scalar is
the wrong shape.

## The rule for what belongs to no workstream

`pr`, `merge`, `close_out` and everything before the split belong to none. They read the
**strictest** of the workstreams, never the loosest: a programme is as risky as its riskiest part at
the point where all of it merges, and reading the loosest would let a `low` copy tweak set the height
of the gate the whole change passes through.

## How this composes with CHG-20260827-17

Until the grade is ratified there is no "this node's grade" to read, so the unsettled rule wins and
everything is protected at the strictest candidate — workstreams included. Per-node grades only
apply once somebody has signed off.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import engine, graph, plan, policy  # noqa: E402

WORKSTREAMS = {"schema": "high", "copy": "low", "payments": "medium"}
ASSIGNED = {"engineer_build": "copy", "lead_review": "schema", "qa_verify": "payments"}


def _grade(node=None, *, settled="medium", **kw):
    cfg = engine.RunConfig(node_specs={}, decisions={}, **kw)
    report = engine.RunReport()
    report.risk_settled = settled
    return engine._grade_in_force(cfg, report, node)


# ── a node reads its own workstream ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node_id,expected", [
    ("engineer_build", "low"),
    ("lead_review", "high"),
    ("qa_verify", "medium"),
])
def test_a_node_reads_its_workstreams_grade(node_id, expected):
    """The copy tweak is `low` while the schema change is `high`, in the same run."""
    assert _grade(graph.BY_ID[node_id], risk="medium",
                  workstreams=WORKSTREAMS, node_workstream=ASSIGNED) == expected


@pytest.mark.parametrize("node_id", ["merge", "pr", "close_out", "intake"])
def test_a_node_in_no_workstream_reads_the_strictest(node_id):
    """Task 4, and the half that is easy to get backwards. `merge` belongs to no workstream; reading
    the loosest would let a `low` copy tweak set the height of the gate the whole change passes
    through."""
    assert _grade(graph.BY_ID[node_id], risk="low",
                  workstreams=WORKSTREAMS, node_workstream=ASSIGNED) == "high"


def test_merge_is_high_when_any_workstream_is_high():
    """Task 3, stated as the proposal states it."""
    verdict = engine.resolve_verdict(
        graph.BY_ID["merge"],
        _grade(graph.BY_ID["merge"], risk="low",
               workstreams={"a": "low", "b": "high"}, node_workstream={}))
    assert verdict["risk"] == "high"
    assert verdict["verdict"] in policy.STOPPING


# ── the compatibility path ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("node_id", ["merge", "engineer_build", "lead_review"])
def test_a_plan_with_no_workstreams_behaves_exactly_as_before(node_id):
    """The default, and the rollback story. No workstreams means one grade for every node."""
    assert _grade(graph.BY_ID[node_id], risk="medium", settled="medium") == "medium"


# ── the operator's override ─────────────────────────────────────────────────────────────────────

def test_the_operator_override_applies_to_every_workstream():
    """Task 5. `--risk high` is a person saying what this run is, not a proposal to be weighed
    against a workstream's `low`."""
    for node_id in ("engineer_build", "lead_review", "merge"):
        assert _grade(graph.BY_ID[node_id], risk="low", risk_override="high",
                      workstreams=WORKSTREAMS, node_workstream=ASSIGNED) == "high"


def test_the_override_is_not_merely_the_plans_grade():
    """`risk` and `risk_override` were the same string before this change and nothing could tell
    them apart. A plan grading itself `low` must not be able to lower a workstream that says
    `high`; an operator saying `low` deliberately can."""
    assert _grade(graph.BY_ID["lead_review"], risk="low",
                  workstreams=WORKSTREAMS, node_workstream=ASSIGNED) == "high"
    assert _grade(graph.BY_ID["lead_review"], risk="low", risk_override="low",
                  workstreams=WORKSTREAMS, node_workstream=ASSIGNED) == "low"


# ── composing with CHG-20260827-17 ──────────────────────────────────────────────────────────────

def test_an_unratified_grade_still_wins_over_per_node_grades():
    """Until somebody signs off there is no "this node's grade" to read. A `low` workstream must
    not lower a gate while the run's own grade is still an open question."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="low",
                           workstreams=WORKSTREAMS, node_workstream=ASSIGNED)
    report = engine.RunReport()
    report.risk_proposed.update({"a": "high"})
    assert report.risk_settled is None
    assert engine._grade_in_force(cfg, report, graph.BY_ID["engineer_build"]) == "high"


def test_a_workstream_grade_is_a_candidate_while_the_grade_is_open():
    """The strictest-candidate rule reads workstreams too — a declared `high` workstream protects
    the run before anybody has graded it."""
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="low", workstreams={"schema": "high"})
    assert engine._grade_in_force(cfg, engine.RunReport(), graph.BY_ID["merge"]) == "high"


# ── the report says which grade each node used ──────────────────────────────────────────────────

def test_the_report_says_which_grade_each_node_used():
    """Task 6. `resolve_verdict` already carries the grade it resolved at, and the walk stores that
    per node — so this is asserted rather than added, and the assertion is what makes it a
    guarantee instead of a coincidence."""
    verdict = engine.resolve_verdict(graph.BY_ID["merge"], "high")
    assert verdict["risk"] == "high"
    assert set(verdict) == {"gate", "risk", "verdict", "source", "tightened"}


# ── refused at the door ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("payload,fragment", [
    ({"workstreams": {"x": "catastrophic"}}, "grades are"),
    ({"workstreams": {"": "low"}}, "no name"),
    ({"workstreams": {"a": "low"}, "node_workstream": {"n": "b"}}, "does not declare"),
])
def test_a_broken_workstream_declaration_is_refused_at_the_door(payload, fragment):
    """The same reason `risk` is validated here: accepted at the door, a grade this runner does not
    recognise reaches the first gate as a crash or as a halt about something the plan could have
    been refused for."""
    with pytest.raises(plan.PlanError) as exc:
        plan.check({"node_specs": {}, **payload})
    assert fragment in str(exc.value)


def test_a_node_in_an_undeclared_workstream_would_have_been_safe_and_wrong():
    """Why that last refusal exists rather than a fallback.

    A node pointing at a workstream nobody declared falls back to the strictest grade — which is
    *safe*, and silently not what the plan meant. Refusing it at the door is the difference between
    a plan that is wrong and a plan that is wrong and running.
    """
    cfg = engine.RunConfig(node_specs={}, decisions={}, risk="low",
                           workstreams={"schema": "high"},
                           node_workstream={"engineer_build": "typo"})
    report = engine.RunReport()
    report.risk_settled = "low"
    assert engine._grade_in_force(cfg, report, graph.BY_ID["engineer_build"]) == "high"


# ── end to end, through the real CLI ─────────────────────────────────────────────────────────────

AGENT = """
import json, sys
order = json.load(sys.stdin)
node, seat = order["node_id"], order.get("seat")


def say(obj):
    print(json.dumps(obj))
    raise SystemExit(0)


if seat:
    if node == "intake_review":
        say({"missing": [], "problems": [], "unsafe": []})
    say({"verdict": "pass", "why": "nothing found"})
if node == "pm_plan":
    say({"modules": ["alpha"]})
if node == "lead_assess":
    say({"risk": "low"})
if node == "engineer_build":
    say({"module": "alpha"})
branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
          "re_review": "pass", "qa_accept": "pass"}.get(node)
say({"verdict": branch} if branch else {"summary": (node or "?") + " done"})
"""


def test_a_workstreamed_plan_reaches_the_run_through_the_cli(tmp_path):
    """The seam nothing else covers: `plan.get("workstreams")` reaching `cfg.workstreams`.

    The plan grades the change `low` and the lead's panel agrees, so **every** gate would be `auto`
    and the run would finish — except that a `high` workstream is declared. `pm_signoff` belongs to
    no workstream, so it reads the strictest, which is `high`, and `before_dispatch: high` halts.

    `--confirm merge` is passed on purpose. The first draft omitted it, so the run stopped at the
    merge gate waiting for a person **whether or not workstreams reached it** — and a mutation that
    deleted the wiring outright left the test green. "It did not finish" was true for a reason that
    had nothing to do with the thing under test.
    """
    import json
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    (tmp_path / "agent.py").write_text(AGENT, encoding="utf-8")
    (tmp_path / "runner.yaml").write_text(
        'agent_command: ["python3", "agent.py"]\nagent_timeout: 60\n', encoding="utf-8")

    def run(workstreams):
        payload = json.loads((root / "examples/minimal/plan.json").read_text(encoding="utf-8"))
        payload["risk"] = "low"
        if workstreams:
            payload["workstreams"] = workstreams
        where = tmp_path / ("with" if workstreams else "without")
        where.mkdir()
        (where / "plan.json").write_text(json.dumps(payload), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "ai_sdlc_runner.cli",
             "--config", str(tmp_path / "runner.yaml"),
             "run", "--plan", str(where / "plan.json"),
             "--confirm", "merge",
             "--ask-journal", str(where / "asks")],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=900)
        return (proc.stdout or "") + (proc.stderr or "")

    # The control: same plan, no workstreams. `low` everywhere, merge confirmed, so it finishes.
    plain = run(None)
    assert "state:         finished" in plain, (
        f"the control run did not finish, so the comparison below proves nothing:\n{plain[-900:]}")

    # The subject: one `high` workstream, nothing else changed.
    graded = run({"schema": "high"})
    assert "state:         finished" not in graded, (
        f"a declared `high` workstream did not raise any gate. The plan's `low` reached "
        f"`before_dispatch`, which means `workstreams` is not reaching `RunConfig`:\n"
        f"{graded[-900:]}")
    # The observable that proves it: a gate resolved AT `high`. Naming a node would be guessing at
    # which gate trips first — the first draft said `pm_signoff`, and the run correctly halted
    # earlier at `pm_confirm`, because `plan_confirmed` is also `halt` at high. The grade is the
    # claim; which gate notices it first is not.
    assert "at risk high" in graded, (
        "the run stopped, but not at a gate resolved from `high` — so the workstream is not what "
        "stopped it:\n" + graded[-900:])


# ── a workstream may only grade the work it is a workstream of (CHG-20260902-19) ──────────────

def test_a_workstream_cannot_be_assigned_to_a_node_the_whole_change_passes_through():
    """`_grade_in_force` states the rule and nothing enforced it.

    > a node in a workstream reads that workstream's grade. A node in none — `pr`, `merge`,
    > `close_out`, and everything before the split — reads the **strictest** of them: a programme is
    > as risky as its riskiest part **at the point where all of it merges**.

    `plan.check` validated only that the workstream *name* was declared; the node id was never
    checked at all. So a plan could put `qa_accept` in a `low` workstream on a run settled at
    `high`, and `acceptance` — the one `halt_independent` cell in the entire table — resolved
    `auto`, on the grade `README.md` says "always stops for a person".
    """
    from ai_sdlc_runner import plan as plan_mod

    base = {"risk": "high", "workstreams": {"w1": "low"}, "decisions": {}}
    for node_id in ("qa_accept", "merge", "pr", "lead_review", "qa_verify"):
        with pytest.raises(plan_mod.PlanError) as caught:
            plan_mod.check(dict(base, node_workstream={node_id: "w1"}))
        assert "not part of a module's work" in str(caught.value), node_id

    # The nodes a workstream IS about are still assignable, or this refusal has eaten the feature.
    for node_id in sorted(graph.module_cycle()):
        plan_mod.check(dict(base, node_workstream={node_id: "w1"}))


def test_a_workstream_assignment_naming_no_node_is_refused():
    """The id was never checked against the flow either. A misspelt one is silently ignored by the
    engine, so the workstream the plan meant to grade runs at the strictest grade instead — safe,
    and not what the plan said."""
    from ai_sdlc_runner import plan as plan_mod

    with pytest.raises(plan_mod.PlanError) as caught:
        plan_mod.check({"risk": "high", "workstreams": {"w1": "low"}, "decisions": {},
                        "node_workstream": {"enginer_build": "w1"}})
    assert "no such node" in str(caught.value)


def test_the_assignable_set_is_read_from_the_graph_rather_than_listed():
    """`engine._workspace` reads `graph.module_cycle()` for the same reason: a node added to the
    loop later is inside the rule instead of quietly outside it. If this ever becomes a literal
    list, this test is what should stop it."""
    assert graph.module_cycle(), "an empty module cycle would refuse every assignment"
    assert "engineer_build" in graph.module_cycle()
    assert "qa_accept" not in graph.module_cycle()
