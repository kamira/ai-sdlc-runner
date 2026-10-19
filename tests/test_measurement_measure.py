"""The measurement script, on a run the stand-in backend made through drive.py. (CHG-20261019-01)

No network and no model: the stand-in knows nothing about weather. Durations are tiny and not the
point; the counts, the loop's membership and that the shares add up are.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "docs" / "measurements" / "CHG-20261019-01" / "measure.py"
spec = importlib.util.spec_from_file_location("measurement_measure", TOOL)
measure = importlib.util.module_from_spec(spec)
sys.modules["measurement_measure"] = measure
spec.loader.exec_module(measure)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_example_weather_live import DRIVE, MODULES, STAND_IN  # noqa: E402


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("measured")
    backend = tmp / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    config = tmp / "runner.yaml"
    config.write_text(f'agent_command: ["{sys.executable}", "{backend.as_posix()}"]\n'
                      f"agent_timeout: 60\n", encoding="utf-8")
    work = tmp / "work"
    done = subprocess.run([sys.executable, str(DRIVE), "--runner-yaml", str(config),
                           "--workdir", str(work)], cwd=str(tmp), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600,
                          env={**os.environ, "PYTHONUTF8": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    return work


@pytest.fixture(scope="module")
def numbers(run_dir):
    return measure.measure(measure.turns_of(measure.open_store(run_dir)), measure.graph.module_cycle())


def test_the_loop_is_derived_from_the_graph_and_contains_the_known_nodes(numbers):
    assert numbers["loop_nodes"] == sorted(measure.graph.module_cycle())
    assert {"engineer_build", "engineer_selfverify", "lead_task_review"} <= set(numbers["loop_nodes"])
    assert "pm_plan" not in numbers["loop_nodes"]


def test_counts_match_the_record(numbers):
    assert numbers["modules_built"] == len(MODULES)
    per = numbers["per_node"]
    assert per["engineer_build"]["asks"] >= len(MODULES)
    assert sum(n["asks"] for n in per.values()) == numbers["asks_total"]
    assert sum(n["asks"] for n in per.values() if n["loop"]) == numbers["asks_in_loop"]
    assert 0 < numbers["asks_in_loop"] < numbers["asks_total"]
    assert list(per) == sorted(per, key=lambda k: -per[k]["total"])


def test_shares_add_up(numbers):
    m = numbers
    assert m["inside_asks_seconds"] == pytest.approx(m["module_loop_seconds"] + m["everything_else_seconds"])
    assert m["wall_seconds"] == pytest.approx(m["inside_asks_seconds"] + m["runner_overhead_seconds"])
    assert min(m["module_loop_seconds"], m["everything_else_seconds"], m["runner_overhead_seconds"]) >= 0
    for n in m["per_node"].values():
        assert n["mean"] == pytest.approx(n["total"] / n["asks"])


def test_amdahl_matches_the_formula_and_task_6s_table():
    assert measure.amdahl(0.68, 4) == pytest.approx(2.05, abs=0.01)
    assert measure.amdahl(0.68, None) == pytest.approx(3.12, abs=0.03)
    assert measure.amdahl(0.0, 4) == 1.0
    assert measure.union_seconds([(0, 2), (1, 3), (5, 6)]) == 4


def test_cli_prints_the_block_and_writes_json(run_dir, tmp_path):
    out = tmp_path / "m.json"
    done = subprocess.run([sys.executable, str(TOOL), str(run_dir), "--json", str(out)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120,
                          env={**os.environ, "PYTHONUTF8": "1"})
    assert done.returncode == 0, done.stderr
    for text in ("first -> last turn", "inside asks", "module loop", "runner overhead",
                 "engineer_build", "ceiling(n) = 1 / ((1 - s) + s / n)", "time share", "ask share"):
        assert text in done.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["modules_built"] == len(MODULES)
    assert set(data["ceiling"]) == {"time", "asks"}
