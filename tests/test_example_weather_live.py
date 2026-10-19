"""`examples/weather-live`: what the repository holds, checked without a network or a model.

The example is built by the runner with a real backend, so there is nothing of the page to test here
and nothing that may be: no agent, no page code, no key. What can be checked is the part a person
gives the runner -- that the plan and `runner.yaml` load in the runner, that the brief says what the
CHG says it does, that the recorded response is what the README describes -- and that `drive.py`
walks the plan to its end, against a stand-in backend that knows nothing about weather.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "weather-live"
DRIVE = EXAMPLE / "drive.py"

MODULES = ["index.html", "styles.css", "sources.js", "openmeteo.js", "cwa.js",
           "normalize.js", "now.js", "week.js", "chart.js", "app.js"]


def _files():
    return [p for p in EXAMPLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def _run(*args, cwd=ROOT, timeout=600):
    import os
    return subprocess.run([sys.executable, str(DRIVE), *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, "PYTHONUTF8": "1"})


def test_the_runner_builds_it_so_the_directory_holds_no_agent_and_no_page_code():
    assert not (EXAMPLE / "agent.py").exists(), "an example agent would be building the page"
    assert not (EXAMPLE / "site").exists(), "the page is the run's output, not the repository's"
    page_code = [p.relative_to(EXAMPLE).as_posix() for p in _files()
                 if p.suffix in (".js", ".html", ".css")]
    assert page_code == [], f"page code written in advance: {page_code}"


def test_the_plan_loads_the_way_serve_loads_it():
    from ai_sdlc_runner import plan

    loaded = plan.load(str(EXAMPLE / "plan.json"))
    assert loaded["risk"] == "low"
    assert loaded["decisions"]["next_module"] == "frontier", (
        "the module loop reads its modules from what pm_plan declares")
    for spec in loaded["node_specs"].values():
        assert all(name in spec["expected_outputs"] for name in MODULES)


def test_the_plan_has_the_node_specs_and_operations_of_weather_spas():
    """Derived, not new: the nodes, their operations and the decisions are the same ones."""
    spa = json.loads((ROOT / "examples" / "weather-spa" / "plan.json").read_text(encoding="utf-8"))
    live = json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))
    assert sorted(live["node_specs"]) == sorted(spa["node_specs"])
    assert live["operations"] == spa["operations"]
    assert live["decisions"] == spa["decisions"]


def test_runner_yaml_names_the_model_and_effort_and_grants_no_network_tool():
    from ai_sdlc_runner import cli

    config = cli.load_config(str(EXAMPLE / "runner.yaml"))
    command = config["agent_command"]
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--model") + 1] == "claude-sonnet-5-5"
    assert command[command.index("--effort") + 1] == "medium"
    assert config["agent_retries"] == 0
    assert int(config["agent_timeout"]) >= 1800
    granted = command[command.index("--allowedTools") + 1].split()
    for tool in ("Bash", "WebFetch", "WebSearch"):
        assert tool not in granted, f"{tool} is granted, and a build does not need it"
    assert {"Write", "Read"} <= set(granted)


def test_the_brief_names_the_modules_the_sources_the_error_state_and_the_key_rule():
    brief = (EXAMPLE / "brief.md").read_text(encoding="utf-8")
    for name in MODULES:
        assert f"`{name}`" in brief, f"the brief does not name {name}"
    assert "https://api.open-meteo.com/v1/forecast" in brief
    assert "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-063" in brief
    assert "O-A0003-001" in brief and "466920" in brief
    assert "錯誤狀態" in brief, "a failed request must show a visible error state"
    assert "編造" in brief, "and must never show made-up numbers"
    assert "localStorage" in brief
    assert "任何檔案裡都不可以出現金鑰" in brief, "no key goes into a file"


def test_nothing_in_the_example_looks_like_a_cwa_key():
    key = re.compile(r"CWA-[0-9A-Fa-f-]{20,}")
    leaked = [p.relative_to(EXAMPLE).as_posix() for p in _files()
              if key.search(p.read_text(encoding="utf-8", errors="replace"))]
    assert leaked == [], f"a CWA-looking key is in: {leaked}"


def test_the_key_pattern_would_catch_a_key():
    """A rule that cannot fail is decoration."""
    assert re.search(r"CWA-[0-9A-Fa-f-]{20,}", "Authorization=CWA-0123456789ABCDEF-0123456789AB")


def test_the_recorded_response_is_what_the_readme_says_it_is():
    recording = json.loads(
        (EXAMPLE / "fixtures" / "open-meteo-taipei-2026-10-19.json").read_text(encoding="utf-8"))
    assert recording["current"]["temperature_2m"] == 27.9
    assert recording["current"]["relative_humidity_2m"] == 75
    assert len(recording["daily"]["time"]) == 7
    assert recording["timezone"] == "Asia/Taipei"
    readme = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "fixtures/open-meteo-taipei-2026-10-19.json" in readme
    assert "27.9" in readme and "75 %" in readme


def test_the_readme_says_the_cwa_response_is_confirmed_at_the_measurement():
    readme = " ".join((EXAMPLE / "README.md").read_text(encoding="utf-8").split())
    assert "not confirmed here" in readme and "task 1a" in readme


def test_the_dry_run_exits_zero_from_the_repo_root_and_from_elsewhere(tmp_path):
    for where in (ROOT, tmp_path):
        done = _run("--dry-run", cwd=where)
        assert done.returncode == 0, (where, done.stdout, done.stderr)
        assert "nothing was started" in done.stdout


def test_the_dry_run_refuses_a_runner_yaml_with_no_agent(tmp_path):
    empty = tmp_path / "runner.yaml"
    empty.write_text("agent_timeout: 60\n", encoding="utf-8")
    done = _run("--dry-run", "--runner-yaml", str(empty))
    assert done.returncode != 0
    assert "agent_command" in (done.stdout + done.stderr)


# ── the walk, against a backend that knows nothing about weather ──────────────────────────────

#: Answers each ask the way the order's contract asks and builds nothing. It declares the brief's
#: ten files as the plan and reports one per build, then `""`. Nothing here is about a page.
STAND_IN = '''
import json, sys
from pathlib import Path
order = json.loads(sys.stdin.read())
node, seat = order["node_id"], order.get("seat")
MODULES = %r
def say(payload):
    print(json.dumps(payload)); sys.exit(0)
if node == "intake_review":
    say({"missing": [], "problems": [], "unsafe": []})
if seat:
    say({"verdict": "pass", "why": "stand-in"})
if node == "pm_plan":
    say({"modules": MODULES})
if node == "engineer_build":
    counter = Path(".built")
    done = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(done + 1))
    say({"module": MODULES[done] if done < len(MODULES) else ""})
say({"verdict": {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                 "re_review": "pass", "qa_accept": "pass"}.get(node, "pass")})
''' % (MODULES,)


def test_drive_walks_the_plan_to_its_end_and_stops_only_at_merge(tmp_path):
    backend = tmp_path / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    config = tmp_path / "runner.yaml"
    config.write_text(f'agent_command: ["{sys.executable}", "{backend.as_posix()}"]\n'
                      f"agent_timeout: 60\n", encoding="utf-8")
    work = tmp_path / "work"
    hook = tmp_path / "hook.py"
    hook.write_text("import sys\nopen(sys.argv[1], 'a').write(' '.join(sys.argv[2:]) + '\\n')\n",
                    encoding="utf-8")
    seen = tmp_path / "nodes.txt"

    done = _run("--runner-yaml", str(config), "--workdir", str(work),
                "--on-node", f"{sys.executable} {hook} {seen}", cwd=tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "final node:  done  (state finished" in done.stdout
    assert done.stdout.count("stopped at gate") == 1 and "gate merge" in done.stdout
    token = (work / ".runner" / "operator.token").read_text(encoding="utf-8").strip()
    assert token and token not in done.stdout, "the token must not be printed"
    assert (work / "brief.md").is_file() and (work / "plan.json").is_file()
    nodes = [line.split()[0] for line in seen.read_text(encoding="utf-8").splitlines()]
    assert nodes.count("engineer_build") == len(MODULES), (
        "one build per module the plan declared; the frontier is empty after the tenth")
    assert "merge" in nodes
    # Each hook call carried a UTC time after the node id.
    assert all(re.fullmatch(r"\d\d:\d\d:\d\dZ", line.split()[1])
               for line in seen.read_text(encoding="utf-8").splitlines())
