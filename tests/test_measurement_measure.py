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


# ── the writes check: mtimes placed inside and outside the asks ──────────────────────────────────

def _site(tmp_path, run_dir, placements):
    """Files under tmp_path/site whose mtime is the midpoint of the n-th ask (None: after the run)."""
    rows = measure.asks_of(measure.turns_of(measure.open_store(run_dir)))
    (tmp_path / "site").mkdir()
    for name, ask in placements.items():
        path = tmp_path / "site" / name
        path.write_text("x", encoding="utf-8")
        when = rows[-1]["end"] + 60 if ask is None else (rows[ask]["start"] + rows[ask]["end"]) / 2
        os.utime(path, (when, when))
    return rows


def _first(rows, node, after=-1):
    return next(i for i, r in enumerate(rows) if r["node"] == node and i > after)


def test_writes_attributes_each_file_to_its_ask_and_flags_only_what_is_not_allowed(tmp_path, run_dir):
    rows = measure.asks_of(measure.turns_of(measure.open_store(run_dir)))
    build = _first(rows, "engineer_build")
    built = rows[build]["result"]["module"]
    verify = _first(rows, "engineer_selfverify", build)
    review = _first(rows, "lead_task_review", build)
    _site(tmp_path, run_dir, {built: build, "other.js": verify, "stray.js": review, "late.js": None})
    found = {w["file"]: w for w in measure.writes(rows, tmp_path)}
    assert found[f"site/{built}"]["node"] == "engineer_build" and not found[f"site/{built}"]["flag"]
    assert found[f"site/{built}"]["ask"] == build + 1
    assert "selfverify" in found["site/other.js"]["flag"]
    assert "lead_task_review" in found["site/stray.js"]["flag"]
    assert "outside" in found["site/late.js"]["flag"]


def test_selfverify_may_write_the_module_its_build_just_built(tmp_path, run_dir):
    rows = measure.asks_of(measure.turns_of(measure.open_store(run_dir)))
    build = _first(rows, "engineer_build")
    verify = _first(rows, "engineer_selfverify", build)
    built = rows[build]["result"]["module"]
    _site(tmp_path, run_dir, {built: verify})
    [w] = measure.writes(rows, tmp_path)
    assert w["node"] == "engineer_selfverify" and w["flag"] == ""


def test_writes_is_in_the_output_and_the_json(tmp_path, run_dir):
    rows = measure.asks_of(measure.turns_of(measure.open_store(run_dir)))
    build = _first(rows, "engineer_build")
    _site(tmp_path, run_dir, {"index.html": build, "bad.js": _first(rows, "pm_plan")})
    (tmp_path / "conv").symlink_to(run_dir / "conv", target_is_directory=True)
    out = tmp_path / "m.json"
    done = subprocess.run([sys.executable, str(TOOL), str(tmp_path), "--json", str(out)],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "site/index.html" in done.stdout and "!! written by pm_plan" in done.stdout
    assert "2 files, 1 flagged" in done.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert {w["file"]: bool(w["flag"]) for w in data["writes"]} == {
        "site/bad.js": True, "site/index.html": False}


def test_no_site_directory_is_no_writes(tmp_path, run_dir):
    rows = measure.asks_of(measure.turns_of(measure.open_store(run_dir)))
    assert measure.writes(rows, tmp_path) == []
