"""A module was recorded on the lap the engineer said there was nothing to build
(CHG-20260828-15).

`ACC-20260823-51` reservation 2 named it and marked it **Unchanged**; CHG-20260828-12 reproduced it
and handed on the design choice rather than picking one. The operator chose: **the flow branches.**

An engineer answering `{"module": ""}` used to walk
`engineer_build → engineer_selfverify → lead_task_review → record_module`, and `record_module`'s
effects are *"tick, commit, update the worklog"*. A worklog entry would claim a module that was
never built — and `examples/weather-spa` declares those operations, so it was live, not latent.

## Why a node and not a condition in the engine

The alternative was to make `record_module`'s effects conditional inside `engine`, which is the
id-matching this repository argues against everywhere else — *"declared here rather than matched on
the node's id in the engine"*. A branch says it in the graph, where the flow can be read.

## Nobody is asked

What the engineer said is a **fact in the run's record**, and reading a fact is not a judgement —
the same reason `reconcile` has no role. So `module_built` is a runner decision, and no answer can
supply it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from ai_sdlc_runner import engine, graph  # noqa: E402
from test_flow import ANSWERS, DECISIONS, SPEC, THROUGH  # noqa: E402


def _walk(build_answer):
    def dispatch(order):
        node = order["node_id"]
        if order.get("seat"):
            return {"verdict": "pass"}
        if node == "pm_plan":
            return {"modules": ["alpha"]}
        if node == "engineer_build":
            return build_answer
        branch = ANSWERS.get(node)
        return {"verdict": branch} if branch else {"ok": True}

    cfg = engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                           decisions=dict(DECISIONS), risk="low", undeclared="allow",
                           confirmed=THROUGH)
    return engine.walk(cfg, dispatch, enabled=True)


# ── the shape in the graph ──────────────────────────────────────────────────────────────────────

def test_both_pass_edges_go_through_the_guard():
    """A fix pass that built nothing must be caught too, so `re_review` routes through it as well."""
    assert graph.BY_ID["lead_task_review"].branches["pass"] == "module_built"
    assert graph.BY_ID["re_review"].branches["pass"] == "module_built"


def test_the_guard_is_the_only_way_in_to_record_module():
    """If any edge reached `record_module` directly the guard would be decoration."""
    ways_in = [n.id for n in graph.NODES
               if n.next == "record_module" or "record_module" in n.branches.values()]
    assert ways_in == ["module_built"], ways_in


def test_nobody_is_asked():
    node = graph.BY_ID["module_built"]
    assert node.role is None
    assert node.mode == graph.RUNNER
    assert node.gate is None
    assert set(node.branches) == {"yes", "no"}


# ── the decision ────────────────────────────────────────────────────────────────────────────────

def test_a_lap_that_built_something_records_it():
    report = _walk({"module": "alpha"})
    assert "record_module" in report.visited


def test_a_lap_that_built_nothing_does_not():
    """The defect. `record_module` applies effects, and an empty lap would apply them."""
    report = _walk({"module": ""})
    assert "module_built" in report.visited, "the guard must be reached to refuse"
    assert "record_module" not in report.visited


def test_an_answer_with_no_module_key_is_not_a_build():
    """Silence is not a build. `_frontier` draws the same line for the same reason: an agent that
    crashed or replied with prose has not reported building anything."""
    assert "record_module" not in _walk({"ok": True}).visited


def test_the_run_cannot_answer_the_question_itself():
    """A run that could say `yes` could record a module it never built — the whole point."""
    report = engine.RunReport()
    report.asks.append(engine.Ask(node_id="engineer_build", role="engineer",
                                  result={"module": ""}))
    cfg = engine.RunConfig(node_specs={}, decisions={"module_built": "yes"})
    assert engine._choose(cfg, graph.BY_ID["module_built"], {}, report) == "no"


def test_the_most_recent_build_is_what_counts():
    """A second lap's empty answer must not be overruled by the first lap's module."""
    report = engine.RunReport()
    report.asks.append(engine.Ask(node_id="engineer_build", role="engineer",
                                  result={"module": "alpha"}))
    report.asks.append(engine.Ask(node_id="engineer_build", role="engineer",
                                  result={"module": ""}))
    assert engine._module_built(report) == "no"


# ── the isolation boundary this change moved ────────────────────────────────────────────────────

def test_the_module_cycle_did_not_escape_through_the_new_edge():
    """`module_built --no--> next_module` opened a path out of the loop, and `graph.module_cycle()`
    followed it — sweeping in `merge`, `pr` and `lead_review`, which would have put the whole
    change's review inside one module's worktree.

    Caught because the cycle is **derived** from the edges. A hand-written list of five ids would
    have gone on looking correct while the graph moved underneath it.
    """
    assert graph.module_cycle() == ["engineer_build", "engineer_selfverify", "fix_pass",
                                    "lead_task_review", "re_review"]
    assert "merge" not in engine._MODULE_CYCLE
    assert "lead_review" not in engine._MODULE_CYCLE
