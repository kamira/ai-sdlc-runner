"""What the module loop does after an engineer says there is nothing left (CHG-20260823-51).

Both review seats returned `not sound` on CHG-20260823-47..50. This file holds what they found in
the frontier, and it is written the way it is because of *how* the previous attempt went wrong.

## The test this replaces asserted over a history the flow cannot produce

CHG-20260823-50 claimed, with a ticked task box, that "nothing left" is not a latch. Its test:

    assert _frontier_over([
        ("pm_plan",        {"modules": ["markup"]}),
        ("engineer_build", {"module": "markup"}),
        ("engineer_build", {"module": ""}),
        ("pm_plan",        {"modules": ["markup", "charts"]}),
        ("engineer_build", {"module": "charts"}),      # <- appended by hand
    ]) == "none"

Reaching `engineer_build` in the shipped graph requires `next_module` to answer `"module"` — the
very thing under test. So the last entry is an ask no run can produce, and the assertion never
examines the reopening moment at all. A seat drove the real CLI instead and found the opposite: the
empty answer was **permanent**. `next_module` is the only ordinary route into `engineer_build`
(`engineer_selfverify.rejects_to` needs the builder to have just run), so once the engineer said
`{"module": ""}` it could never be asked again — a second instruction planning two more modules
produced `lead_review → pass`, `state: finished`, and nothing on disk.

**So the latch test here drives the real CLI through a real re-plan.** A unit test over a
hand-built history is what shipped the defect; it is not what pins the fix.

## And an empty answer carrying failure evidence is not "finished"

The other seat drove `{"module": "", "error": "compiler failed"}` to `merge` and `finished` with
the planned module never written. `lead_review` and `qa_verify` do not catch it — neither compares
`pm_plan.modules`, `expected_outputs`, or the filesystem — so CHG-20260823-50's claim that review
"stands between a silently empty build and a merge" was false. Refused by name now.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: An agent that builds `alpha`, then reports nothing left, then — after a second instruction — is
#: asked again and builds whatever the current plan added. Written to a file because the run
#: dispatches one process per ask.
AGENT = '''
import json, os, sys

order = json.load(sys.stdin)
node, seat = order["node_id"], order.get("seat")
state = os.path.join(os.path.dirname(os.path.abspath(__file__)), "built.json")
built = json.load(open(state)) if os.path.exists(state) else []
plans = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plans.json")
rounds = json.load(open(plans)) if os.path.exists(plans) else []


def say(obj):
    print(json.dumps(obj))
    raise SystemExit(0)


if seat:
    # Seats first, exactly as the shipped example does. Without this, `lead_review` never reaches a
    # verdict, routes to `review_failed`, and the run spins between `next_module` and the panel --
    # a cycle that has nothing to do with what these tests are about. The first draft of this file
    # omitted it and the step cap caught it, naming `next_module x64, lead_review x63,
    # review_failed x63`, which is the message CHG-20260823-50 rewrote.
    if node == "intake_review":
        say({"missing": [], "problems": [], "unsafe": []})
    say({"verdict": "pass", "why": seat + ": nothing found"})

if node == "pm_plan":
    rounds.append(1)
    json.dump(rounds, open(plans, "w"))
    say({"modules": ["alpha"] if len(rounds) == 1 else ["alpha", "beta"]})

if node == "engineer_build":
    wanted = ["alpha"] if len(rounds) <= 1 else ["alpha", "beta"]
    todo = [m for m in wanted if m not in built]
    if not todo:
        say({"module": "", "note": "every module already matches the brief"})
    built.append(todo[0])
    json.dump(built, open(state, "w"))
    say({"module": todo[0], "wrote": todo[0]})

branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
          "re_review": "pass", "qa_accept": "pass"}.get(node)
say({"verdict": branch} if branch else {"summary": (node or "?") + " done"})
'''


def _project(tmp_path, agent_source=AGENT, feedback=("more", "done")):
    """A runnable project: a plan, a runner.yaml, and an agent, all in one directory."""
    plan = json.loads((ROOT / "examples/minimal/plan.json").read_text(encoding="utf-8"))
    plan["decisions"] = {"next_module": "frontier", "feedback": list(feedback)}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (tmp_path / "runner.yaml").write_text(
        'agent_command: ["python3", "agent.py"]\nagent_timeout: 60\n', encoding="utf-8")
    (tmp_path / "agent.py").write_text(agent_source, encoding="utf-8")
    return tmp_path


def _run(tmp_path, confirms=2):
    """`confirms` merge confirmations, because the `more` branch passes through `merge` once per
    lap. The first draft passed one and the run stopped waiting for a person at the second."""
    merge = []
    for _ in range(confirms):
        merge += ["--confirm", "merge"]
    return subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(tmp_path / "runner.yaml"),
         "run", "--plan", str(tmp_path / "plan.json"),
         "--risk", "low", *merge,
         "--ask-journal", str(tmp_path / "asks")],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}, timeout=900)


def _asks(tmp_path):
    """Every ask the run actually made, in journal order, as (node_id, result)."""
    out = []
    for f in sorted((tmp_path / "asks").glob("*.json")):
        if f.name.startswith("."):
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append((d.get("node_id"), d.get("result") or d.get("answer") or {}))
    return out


def test_a_second_instruction_gets_its_modules_built(tmp_path):
    """The latch, driven through the real CLI rather than asserted over a hand-built history.

    Round one plans `alpha` and builds it; the engineer then reports nothing left. `feedback` takes
    the `more` branch, `pm_plan` runs again and now names `alpha` **and** `beta`. Before this fix
    `next_module` answered `none` for ever, `engineer_build` was never asked again, and the run
    reported `finished` with `beta` unbuilt.
    """
    project = _project(tmp_path)
    # `alpha` already exists, so the engineer answers "nothing left" on its FIRST ask. That is what
    # sets the latch. The first draft of this test did not pre-seed, so round one built `alpha`,
    # `remaining` emptied by the ordinary route, and the engineer was never asked a second time --
    # no empty answer was ever produced and the test passed against the defective code. It was a
    # test for a latch that never reached the latch, which is the same mistake one layer up from
    # the one this file was written to replace. Caught by running it against `origin/main`.
    (project / "built.json").write_text(json.dumps(["alpha"]), encoding="utf-8")

    proc = _run(project)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "state:         finished" in out, out[-900:]

    empty = [r for n, r in _asks(project)
             if n == "engineer_build" and "module" in r and not r["module"]]
    assert empty, "the engineer never said 'nothing left', so the latch was never set"

    asks = _asks(project)
    plans = [n for n, _ in asks].count("pm_plan")
    assert plans >= 2, f"the run never re-planned, so the latch is untested: {[n for n, _ in asks]}"

    modules = [str(r.get("module")) for n, r in asks if n == "engineer_build" and "module" in r]
    assert "beta" in modules, (
        f"a second plan named `beta` and the engineer was never asked to build it. "
        f"engineer_build answered: {modules}")

    built = json.loads((project / "built.json").read_text(encoding="utf-8"))
    assert built == ["alpha", "beta"], f"what the agent actually built: {built}"


def test_an_empty_answer_still_ends_one_plans_loop_without_cycling(tmp_path):
    """The case CHG-20260823-50 existed for, kept working: a rerun over artefacts that already exist.

    The first draft of this test expected two `engineer_build` asks under one plan — one real build
    and one "nothing left". That premise was wrong, and running it said so: when everything planned
    gets built, the loop ends by the ordinary route (`remaining` empties) and the engineer is never
    asked again, so no empty answer is ever produced. The only way one plan yields an empty answer
    is when the work already exists before the run starts, which is the rerun. So that is what this
    drives: `built.json` pre-seeded, the engineer reports nothing left on its first ask.
    """
    project = _project(tmp_path, feedback=("done",))
    (project / "built.json").write_text(json.dumps(["alpha"]), encoding="utf-8")

    proc = _run(project, confirms=1)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "state:         finished" in out, out[-900:]
    assert "exceeded" not in out and "cycling" not in out, out[-600:]

    builds = [r for n, r in _asks(project) if n == "engineer_build"]
    assert len(builds) == 1, f"expected exactly one ask, got {len(builds)}: {builds}"
    assert str(builds[0].get("module")) == "", builds[0]


FAILING_AGENT = AGENT.replace(
    '''        say({"module": "", "note": "every module already matches the brief"})''',
    '''        say({"module": "", "error": "compiler failed"})''').replace(
    '''    todo = [m for m in wanted if m not in built]
    if not todo:''',
    '''    todo = []
    if not todo:''')


def test_an_engineer_that_reports_a_failure_is_not_read_as_finished(tmp_path):
    """A seat drove exactly this to `merge` and `finished` with the planned module never written.

    `{"module": "", "error": "compiler failed"}` makes two claims at once — "there is nothing left
    to build" and "I could not build it" — and this runner refuses to choose between them, the same
    way the importer refuses two conversations claiming one id.

    Asserted against the run's **outcome**, not against a message: the point is that it does not
    finish.
    """
    project = _project(tmp_path, agent_source=FAILING_AGENT, feedback=("done",))
    proc = _run(project, confirms=1)
    out = (proc.stdout or "") + (proc.stderr or "")

    assert "state:         finished" not in out, (
        f"an engineer reporting a failure produced a finished run:\n{out[-900:]}")
    assert "two different claims" in out or "will not choose between them" in out, (
        f"the refusal does not say what was contradictory:\n{out[-900:]}")


@pytest.mark.parametrize("evidence", [
    {"error": "compiler failed"},
    {"errors": ["a", "b"]},
    {"failed": True},
    {"traceback": "Traceback (most recent call last): ..."},
])
def test_every_shape_of_failure_evidence_contradicts_an_empty_module(evidence):
    """Unit-level, over the shapes an agent actually uses. `failed: False` must NOT contradict —
    an agent that reports success explicitly is not reporting a failure."""
    from ai_sdlc_runner import engine

    assert engine._went_wrong({"module": "", **evidence}), evidence
    assert not engine._went_wrong({"module": "", "failed": False})
    assert not engine._went_wrong({"module": "", "error": ""})
    assert not engine._went_wrong({"module": "alpha"})


def test_ending_the_loop_on_the_engineers_word_is_recorded(tmp_path):
    """Nothing downstream checks it, so the run must at least say it happened.

    Both seats verified that `lead_review` adjudicates verdict strings only, `qa_verify` is a
    branchless step accepting any JSON object, and no node compares `pm_plan.modules`,
    `expected_outputs` or the filesystem. CHG-20260823-50 claimed review stood between this and a
    merge. It does not — so the report carries the fact instead of implying somebody caught it.
    """
    from ai_sdlc_runner import engine, graph

    class _Ask:
        def __init__(self, node_id, result):
            self.node_id, self.result = node_id, result

    node = graph.BY_ID["next_module"]
    report = engine.RunReport()
    report.asks = [_Ask("pm_plan", {"modules": ["alpha", "beta"]}),
                   _Ask("engineer_build", {"module": ""})]

    assert engine._frontier(node, report) == "none"
    said = " ".join(report.dispatches)
    assert "nothing left to build" in said, report.dispatches
    assert "alpha" in said and "beta" in said, report.dispatches
    assert "no node after this one checks it" in said, report.dispatches
