"""Running a finished project again finishes again (CHG-20260823-50).

`examples/weather-spa` built once, then run a second time with its `site/` still on disk:

    first   visited 35 node(s)   asks 26    state: finished
    second  halted: walk exceeded 200 steps — the flow is cycling without progress

Twenty-six asks the first time, **two hundred** the second, and nothing built.

## Why

The example's agent compares content rather than counting files — its own comment says counting was
the first version's bug — so with everything already correct it answers:

    {"module": "", "wrote": "", "note": "every module already matches the brief"}

`_frontier` collected built modules with a trailing `and (ask.result or {}).get("module")`, which
**discards** that answer. `remaining` stayed non-empty for ever, `next_module` said `module`,
`engineer_build` was asked the same question again, and the same answer came back until the step
guard tripped.

The engineer is the only party that knows what is left — the work order never names a module — so
it had said the true thing and the runner could not hear it. The loop was not cycling because of a
bad plan or a confused agent; the runner could not represent an answer its own protocol allows.

## What these tests hold

1. a shipped example runs twice and finishes twice
2. a **missing** `module` key is still not an answer, so a broken agent does not read as "done"
3. when a walk does cycle, the message names the node, the count and the last answer

(2) is the one that keeps (1) from being a shortcut: "treat any falsy module as finished" would pass
(1) and turn every crashed agent into a completed project.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

#: The examples whose agents report a module — the ones the frontier loop applies to. Discovered,
#: so a new example is covered without editing a list here.
BUILDERS = sorted(
    d.name for d in EXAMPLES.iterdir()
    if (d / "runner.yaml").is_file() and (d / "plan.json").is_file()
    and (d / "agent.py").is_file() and '"module"' in (d / "agent.py").read_text(encoding="utf-8"))


def _cli(cwd, *args):
    return subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1"}, timeout=900)


def test_the_discovery_found_the_building_examples():
    """A parametrised test over an empty list passes without running anything."""
    assert len(BUILDERS) >= 2, f"expected the building examples, found {BUILDERS}"


@pytest.mark.parametrize("example", BUILDERS)
def test_a_finished_project_run_again_finishes_again(example, tmp_path):
    """Two runs, two fresh journals, one working tree — the second sees the first's output.

    A fresh journal on purpose: resuming would skip the asks from the journal and prove nothing
    about the loop. This is the case an operator hits by running the same command twice.
    """
    here = tmp_path / example
    shutil.copytree(EXAMPLES / example, here,
                    ignore=shutil.ignore_patterns("__pycache__", "site", "*.pyc", "greet.py"))

    outs = []
    for n in (1, 2):
        proc = _cli(tmp_path,
                    "--config", str(here / "runner.yaml"),
                    "run", "--plan", str(here / "plan.json"),
                    "--risk", "low", "--confirm", "merge",
                    "--ask-journal", str(tmp_path / f"asks{n}"))
        outs.append((proc.stdout or "") + (proc.stderr or ""))

    assert "state:         finished" in outs[0], outs[0][-800:]
    assert "cycling" not in outs[1] and "exceeded" not in outs[1], (
        f"{example} run a second time against its own output looped:\n{outs[1][-800:]}")
    assert "state:         finished" in outs[1], (
        f"{example} did not finish on a second run:\n{outs[1][-800:]}")


def _report(**asks):
    """The smallest thing `_frontier` reads: a report with `asks` that have `node_id` and `result`."""
    from ai_sdlc_runner import engine

    class _Ask:
        def __init__(self, node_id, result):
            self.node_id, self.result = node_id, result

    class _Report:
        def __init__(self, items):
            self.asks = items

    return engine, _Ask, _Report


def _frontier_over(sequence):
    engine, Ask, Report = _report()
    from ai_sdlc_runner import graph
    node = graph.Node("next_module", graph.LOOP, "x", branches={"module": "a", "none": "b"})
    return engine._frontier(node, Report([Ask(nid, res) for nid, res in sequence]))


def test_an_engineer_that_reports_nothing_left_ends_the_loop():
    """The fix. `{"module": ""}` is an answer, and the answer is "there is nothing left"."""
    assert _frontier_over([
        ("pm_plan", {"modules": ["markup", "styles"]}),
        ("engineer_build", {"module": "markup"}),
        ("engineer_build", {"module": "", "note": "every module already matches the brief"}),
    ]) == "none"


def test_an_engineer_that_did_not_answer_does_not_end_the_loop():
    """The guard on the fix, and the reason it is not "any falsy module means finished".

    An agent that crashed, timed out, or replied with prose has **no** `module` key. Reading that as
    completion would turn every broken backend into a finished project — and it would still pass the
    two-run test above, which is exactly how a shortcut gets shipped.
    """
    for did_not_answer in ({}, {"summary": "I had a look"}, {"wrote": "site/index.html"}):
        assert _frontier_over([
            ("pm_plan", {"modules": ["markup", "styles"]}),
            ("engineer_build", {"module": "markup"}),
            ("engineer_build", did_not_answer),
        ]) == "module", f"{did_not_answer!r} was read as 'nothing left to build'"


def test_a_later_plan_reopens_the_loop_after_an_empty_answer():
    """"Nothing left" is about now, not for ever. A second instruction that plans more modules must
    put the loop back to work — the empty answer is the engineer's last word, not a latch."""
    assert _frontier_over([
        ("pm_plan", {"modules": ["markup"]}),
        ("engineer_build", {"module": "markup"}),
        ("engineer_build", {"module": ""}),
        ("pm_plan", {"modules": ["markup", "charts"]}),
        ("engineer_build", {"module": "charts"}),
    ]) == "none"


def test_everything_planned_is_built_still_ends_the_loop():
    """The path that always worked, kept honest — the fix must not be the only route to `none`."""
    assert _frontier_over([
        ("pm_plan", {"modules": ["markup"]}),
        ("engineer_build", {"module": "markup"}),
    ]) == "none"


def test_a_cycle_says_what_cycled(tmp_path):
    """The message was `the flow is cycling without progress` — true, and it names the symptom.

    An operator who hit it learned that something looped. It did not say which node, how often, or
    what it kept answering, all of which the report already held. The loop it was written for was
    `engineer_build` answering the same thing two hundred times.
    """
    from ai_sdlc_runner import engine

    agent = tmp_path / "mute.py"
    agent.write_text(
        "import json, sys\n"
        "order = json.load(sys.stdin)\n"
        "node = order.get('node_id') or order.get('order', {}).get('node_id')\n"
        "branch = {'pm_confirm': 'yes', 'pm_signoff': 'yes', 'lead_task_review': 'pass',\n"
        "          're_review': 'pass', 'qa_accept': 'pass'}.get(node)\n"
        "if node == 'pm_plan':\n"
        "    print(json.dumps({'modules': ['never-built']}))\n"
        "elif node == 'engineer_build':\n"
        "    print(json.dumps({'summary': 'looked, said nothing'}))   # no `module` key, ever\n"
        "elif branch:\n"
        "    print(json.dumps({'verdict': branch}))\n"
        "else:\n"
        "    print(json.dumps({'summary': f'{node} done'}))\n",
        encoding="utf-8")

    shutil.copy(EXAMPLES / "minimal" / "plan.json", tmp_path / "plan.json")
    (tmp_path / "runner.yaml").write_text(
        json.dumps({"agent_command": [sys.executable, "mute.py"], "agent_timeout": 60})
        .replace("{", "").replace("}", "").replace('"agent_command": ', "agent_command: ")
        .replace(', "agent_timeout": ', "\nagent_timeout: "), encoding="utf-8")

    proc = _cli(tmp_path, "--config", str(tmp_path / "runner.yaml"),
                "run", "--plan", str(tmp_path / "plan.json"),
                "--risk", "low", "--confirm", "merge",
                "--ask-journal", str(tmp_path / "asks"))
    out = (proc.stdout or "") + (proc.stderr or "")

    assert "exceeded" in out, f"expected the step guard to trip:\n{out[-800:]}"
    assert "Most-visited" in out and "engineer_build" in out, (
        f"the cycle message does not name what cycled:\n{out[-800:]}")
    assert "last answered" in out, (
        f"the cycle message does not say what the repeating node kept answering:\n{out[-800:]}")
