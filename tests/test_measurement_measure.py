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
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
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
    assert m["wall_seconds"] == pytest.approx(
        m["inside_asks_seconds"] + m["waiting_for_person_seconds"] + m["runner_overhead_seconds"])
    assert m["waiting_for_person_seconds"] == 0 and m["person_stops"] == [], "nobody was asked"
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
    for text in ("brief -> last turn", "inside asks", "module loop", "runner overhead",
                 "engineer_build", "ceiling(n) = 1 / ((1 - s) + s / n)", "time share", "ask share"):
        assert text in done.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["modules_built"] == len(MODULES)
    assert set(data["ceiling"]) == {"time", "asks"}
    assert {"window_start", "window_end", "opened_to_brief_seconds"} <= set(data)


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
    try:
        (tmp_path / "conv").symlink_to(run_dir / "conv", target_is_directory=True)
    except OSError:
        pytest.skip("this platform cannot make a symlink here")
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


# ── waiting for a person ─────────────────────────────────────────────────────────────────────────

def _turn(seq, kind, at, **rest):
    return {"seq": seq, "kind": kind, "at": f"2026-10-19T10:00:{at:06.3f}+00:00", **rest}


def _ask(seq, at, end, node="pm_plan"):
    return [_turn(seq, "ask", at, node_id=node, ask_id=f"a{seq}"),
            _turn(seq + 1, "answer", end, ask_id=f"a{seq}", result={})]


def test_a_stop_answered_by_the_operators_gate_is_not_a_person_wait():
    turns = (_ask(1, 0, 1) + [_turn(3, "closed", 1, state="suspended", at_node="merge"),
                              _turn(4, "decision", 1.1, decision="approval", at_node="merge")]
             + _ask(5, 1.2, 2))
    assert measure.person_waits(turns) == []


def test_a_stop_a_person_answered_is_a_wait_from_the_closed_turn_to_the_next_turn():
    turns = (_ask(1, 0, 1, "intake_review")
             + [_turn(3, "closed", 1, state="suspended", at_node="intake_review")]
             + _ask(4, 11, 12))
    [w] = measure.person_waits(turns)
    assert (w["node"], w["seconds"], w["source"]) == ("intake_review", 10, "record")
    m = measure.measure(turns, [])
    assert m["waiting_for_person_seconds"] == pytest.approx(10)
    assert m["runner_overhead_seconds"] == pytest.approx(0)
    assert m["wall_seconds"] == pytest.approx(12)


def test_a_person_wait_does_not_lower_the_time_share():
    quick = _ask(1, 0, 1, "loop") + _ask(3, 1, 2, "other")
    waited = (_ask(1, 0, 1, "loop") + [_turn(3, "closed", 1, state="suspended", at_node="loop")]
              + _ask(4, 11, 12, "other"))
    base = measure.measure(quick, ["loop"])
    m = measure.measure(waited, ["loop"])
    assert m["waiting_for_person_seconds"] == pytest.approx(10)
    assert m["working_seconds"] == pytest.approx(2)
    assert m["share_time"] == pytest.approx(0.5) == pytest.approx(base["share_time"])
    assert m["ceiling"]["time"] == pytest.approx(base["ceiling"]["time"])
    assert "of working time = wall - waiting for a person" in measure.render(m)


def test_a_tie_ruling_and_an_instruction_end_a_person_wait_and_an_unanswered_stop_does_not():
    turns = (_ask(1, 0, 1) + [_turn(3, "closed", 1, state="suspended", at_node="a"),
                              _turn(4, "decision", 4, decision="ruling", at_node="a"),
                              _turn(5, "closed", 5, state="suspended", at_node="b"),
                              _turn(6, "instruction", 9, nth=2),
                              _turn(7, "closed", 10, state="suspended", at_node="c")])
    assert [(w["node"], w["seconds"]) for w in measure.person_waits(turns)] == [("a", 3), ("b", 4)]


def test_the_drive_log_ends_the_wait_at_the_answer_not_at_the_next_turn():
    turns = (_ask(1, 0, 1) + [_turn(3, "closed", 1, state="suspended", at_node="n")] + _ask(4, 11, 12))
    log = ("AWAITING-PERSON /x/001-n.md\nPERSON-ANSWERED proceed 2026-10-19T10:00:07.500Z\n"
           "PERSON-ANSWERED proceed 2026-10-19T09:00:00.000Z\n")
    answered = measure.answered_in(log)
    [w] = measure.person_waits(turns, answered)
    assert (w["seconds"], w["source"]) == (6.5, "drive log")
    m = measure.measure(turns, [], answered)
    assert m["waiting_for_person_seconds"] == pytest.approx(6.5)
    assert m["runner_overhead_seconds"] == pytest.approx(3.5)


@pytest.fixture(scope="module")
def person_run(tmp_path_factory):
    """A real run whose risk seat says unsafe once, answered by a file after a pause."""
    import time
    tmp = tmp_path_factory.mktemp("person")
    backend = tmp / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    config = tmp / "runner.yaml"
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
    work, log = tmp / "work", tmp / "drive.log"
    with log.open("w", encoding="utf-8") as out:
        proc = subprocess.Popen([sys.executable, str(DRIVE), "--runner-yaml", str(config),
                                 "--workdir", str(work), "--person-dir", str(tmp / "person")],
                                cwd=str(tmp), stdout=out,
                                stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1",
                                                               "STAND_IN_UNSAFE": "1"})
        asked = tmp / "person" / "001-intake_review.md"
        for _ in range(240):
            if asked.exists():
                break
            time.sleep(0.25)
        time.sleep(3)
        asked.with_suffix(".proceed").write_text("", encoding="utf-8")
        assert proc.wait(timeout=300) == 0
    return work, log


def test_a_real_unsafe_stop_is_reported_as_waiting_for_a_person_not_as_overhead(person_run):
    work, log = person_run
    turns = measure.turns_of(measure.open_store(work))
    [w] = measure.person_waits(turns)
    assert w["node"] == "intake_review" and 3 <= w["seconds"] < 30
    [wl] = measure.person_waits(turns, measure.answered_in(log.read_text(encoding="utf-8")))
    assert wl["source"] == "drive log" and 3 <= wl["seconds"] <= w["seconds"]
    m = measure.measure(turns, measure.graph.module_cycle())
    assert m["waiting_for_person_seconds"] == pytest.approx(w["seconds"])
    assert m["runner_overhead_seconds"] < 3, "the pause was a person's, not the runner's"
    assert m["wall_seconds"] == pytest.approx(
        m["inside_asks_seconds"] + m["waiting_for_person_seconds"] + m["runner_overhead_seconds"])


def test_cli_prints_the_waiting_line_and_takes_a_drive_log(person_run, tmp_path):
    work, log = person_run
    out = tmp_path / "m.json"
    done = subprocess.run([sys.executable, str(TOOL), str(work), "--drive-log", str(log),
                           "--json", str(out)], capture_output=True, text=True, encoding="utf-8",
                          timeout=120, env={**os.environ, "PYTHONUTF8": "1"})
    assert done.returncode == 0, done.stderr
    assert "waiting for a person" in done.stdout and "1 stop(s)" in done.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["person_stops"][0]["source"] == "drive log"


# ── the window starts at the brief, not at the conversation opening ──────────────────────────────

def test_the_window_starts_at_the_brief_and_the_idle_time_is_reported_apart():
    turns = ([_turn(1, "opened", 0)] + [_turn(2, "instruction", 30)]
             + _ask(3, 30.5, 31.5) + _ask(5, 32, 33))
    m = measure.measure(turns, [])
    assert m["wall_seconds"] == pytest.approx(3)
    assert m["opened_to_brief_seconds"] == pytest.approx(30)
    assert m["runner_overhead_seconds"] == pytest.approx(1)
    assert m["window_start"] == "2026-10-19T10:00:30.000Z" and m["window_end"] == "2026-10-19T10:00:33.000Z"
    assert "brief -> last turn" in measure.render(m)


def test_with_no_instruction_the_window_starts_at_the_first_ask():
    turns = [_turn(1, "opened", 0)] + _ask(2, 5, 6)
    m = measure.measure(turns, [])
    assert (m["wall_seconds"], m["opened_to_brief_seconds"]) == (pytest.approx(1), pytest.approx(5))


def test_start_when_idle_time_does_not_enter_wall_or_overhead(tmp_path):
    """A real run held at --start-when for a while: the hold is in neither number."""
    import time
    backend = tmp_path / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    config = tmp_path / "runner.yaml"
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
    work, go = tmp_path / "work", tmp_path / "go"
    proc = subprocess.Popen(
        [sys.executable, str(DRIVE), "--runner-yaml", str(config), "--workdir", str(work),
         "--start-when", str(go)], cwd=str(tmp_path), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONUTF8": "1"})
    try:
        for line in proc.stdout:
            if "waiting for" in line:
                break
        time.sleep(6)
        go.write_text("", encoding="utf-8")
        proc.communicate(timeout=300)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0
    turns = measure.turns_of(measure.open_store(work))
    m = measure.measure(turns, measure.graph.module_cycle())
    brief = next(t for t in turns if t["kind"] == "instruction")
    assert m["opened_to_brief_seconds"] >= 5
    assert m["wall_seconds"] == pytest.approx(measure._when(turns[-1]["at"]) - measure._when(brief["at"]))
    assert m["wall_seconds"] == pytest.approx(
        measure._when(turns[-1]["at"]) - measure._when(turns[0]["at"]) - m["opened_to_brief_seconds"])
    assert m["runner_overhead_seconds"] < m["wall_seconds"]
    assert m["wall_seconds"] == pytest.approx(
        m["inside_asks_seconds"] + m["waiting_for_person_seconds"] + m["runner_overhead_seconds"])
