"""`examples/weather-live`: what the repository holds, checked without a network or a model.

The example is built by the runner with a real backend, so there is nothing of the page to test here
and nothing that may be: no agent, no page code, no key. What can be checked is the part a person
gives the runner -- that the plan and `runner.yaml` load in the runner, that the brief says what the
CHG says it does, that the recorded response is what the README describes -- and that `drive.py`
walks the plan to its end, against a stand-in backend that knows nothing about weather.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "weather-live"
DRIVE = EXAMPLE / "drive.py"

MODULES = ["index.html", "styles.css", "sources.js", "openmeteo.js", "cwa.js",
           "normalize.js", "now.js", "week.js", "chart.js", "app.js"]


#: The nodes the flow reaches before the module loop (`graph.py`: intake .. pm_signoff), and the ones
#: that judge the finished change. Spelled out so a node added to either stage has to be placed.
PRE_BUILD = ["intake", "intake_review", "pm_plan", "pm_confirm", "lead_assess", "pm_signoff"]
CHANGE_STAGE = ["lead_review", "review_failed", "qa_verify", "qa_accept", "acceptance_failed",
                "pr", "merge", "close_out", "feedback", "done"]


def _files():
    return [p for p in EXAMPLE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]


def _drive_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("weather_live_drive", DRIVE)
    drive = importlib.util.module_from_spec(spec)
    sys.modules["weather_live_drive"] = drive
    spec.loader.exec_module(drive)
    return drive


def _run(*args, cwd=ROOT, timeout=600, env=None):
    import os
    return subprocess.run([sys.executable, str(DRIVE), *args], cwd=str(cwd), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env={**os.environ, "PYTHONUTF8": "1", **(env or {})})


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
    for node in CHANGE_STAGE:
        assert all(name in loaded["node_specs"][node]["expected_outputs"] for name in MODULES)


def test_the_plan_has_the_node_specs_and_operations_of_weather_spas():
    """Derived, not new: the nodes, their operations and the decisions are the same ones."""
    spa = json.loads((ROOT / "examples" / "weather-spa" / "plan.json").read_text(encoding="utf-8"))
    live = json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))
    assert sorted(live["node_specs"]) == sorted(spa["node_specs"])
    assert live["operations"] == spa["operations"]
    assert live["decisions"] == spa["decisions"]


def test_runner_yaml_names_the_model_and_effort_and_grants_no_write_and_no_network_tool():
    from ai_sdlc_runner import cli

    config = cli.load_config(str(EXAMPLE / "runner.yaml"))
    command = config["agent_command"]
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--model") + 1] == "claude-sonnet-5-5"
    assert command[command.index("--effort") + 1] == "medium"
    assert config["agent_retries"] == 0
    assert int(config["agent_timeout"]) >= 1800
    granted = command[command.index("--allowedTools") + 1].split()
    refused = command[command.index("--disallowedTools") + 1].split()
    assert set(granted) == {"Read", "Glob", "Grep"}
    for tool in ("Write", "Edit", "Bash", "WebFetch", "WebSearch"):
        assert tool not in granted, f"{tool} is granted by the default command"
        assert tool in refused, f"{tool} is not refused by name"


def _writer():
    from ai_sdlc_runner import models as models_mod

    registry = models_mod.load(EXAMPLE / "models.json")
    return registry, registry.get("sonnet-writer")


def test_the_write_capable_command_is_the_default_plus_write_and_edit_and_nothing_else():
    from ai_sdlc_runner import cli

    default = cli.load_config(str(EXAMPLE / "runner.yaml"))["agent_command"]
    _, writer = _writer()
    command = list(writer.command)
    assert command[command.index("--model") + 1] == "claude-sonnet-5-5"
    assert command[command.index("--effort") + 1] == "medium"
    granted = command[command.index("--allowedTools") + 1].split()
    refused = command[command.index("--disallowedTools") + 1].split()
    assert set(granted) == {"Read", "Glob", "Grep", "Write", "Edit"}
    assert set(refused) == {"Bash", "WebFetch", "WebSearch"}
    stripped = [w for w in command if w not in ("--allowedTools", "--disallowedTools")]
    assert [w for w in default if w not in ("--allowedTools", "--disallowedTools")][:6] == stripped[:6]


def test_through_the_runners_resolution_only_the_build_and_the_nodes_that_follow_it_can_write():
    """The plan's node_models, the engine's pool and follows rules, and the factory's argv."""
    from ai_sdlc_runner import cli, engine, graph, plan, settings

    loaded = plan.load(str(EXAMPLE / "plan.json"))
    registry, writer = _writer()
    config = cli.load_config(str(EXAMPLE / "runner.yaml"))
    node_models, _, _ = cli.coder_defaults(loaded["node_models"], registry, settings.Settings(),
                                           agent_command=True)
    factory = cli.session_factory(config, registry=registry)
    cfg = engine.RunConfig(node_specs=loaded["node_specs"], decisions=loaded["decisions"],
                           node_models=node_models)
    report = engine.RunReport()
    can_write = set()
    for node in graph.NODES:
        if not node.role:
            continue
        configured = list(node_models.get(node.id) or ())
        model = None
        if node.mode == graph.POOL and configured:
            model = engine._dispatch_from(configured, cfg, node, 0)
        elif node.mode == graph.FOLLOWS:
            model = engine._followed_model(node, report)
        elif configured:
            model = configured[0]
        if node.id == "engineer_build":
            report.asks.append(engine.Ask(node.id, node.role, None, {}, model=model))
        argv = factory(model=model, role=node.role).argv
        tools = argv[argv.index("--allowedTools") + 1].split()
        if "Write" in tools or "Edit" in tools:
            can_write.add(node.id)
    assert can_write == {"engineer_build", "fix_pass", "engineer_selfverify"}
    assert [n.id for n in graph.NODES if n.follows == "engineer_build"] == [
        "engineer_selfverify", "fix_pass"], "the follows nodes changed: update runner.yaml and the README"
    assert loaded["node_models"] == {"engineer_build": ["sonnet-writer"]}


def test_the_specs_tell_every_node_what_it_may_write():
    specs = json.loads((EXAMPLE / "plan.json").read_text(encoding="utf-8"))["node_specs"]
    assert "Build only that first missing file and touch no other file" in specs["engineer_build"]["instructions"]
    assert ("You may only correct the module just built; you must not create any other file"
            in specs["engineer_selfverify"]["instructions"])
    for node, spec in specs.items():
        if node not in ("engineer_build", "engineer_selfverify", "fix_pass"):
            assert spec["instructions"].endswith("Do not create or change any file."), node


def _specs():
    from ai_sdlc_runner import plan

    return plan.load(str(EXAMPLE / "plan.json"))["node_specs"]


def _requires_a_site_file(spec):
    text = " ".join([json.dumps(spec["expected_outputs"]), spec["acceptance_predicate"]])
    return "site/" in text or any(name in text for name in MODULES) or "files exist" in text


def test_no_node_before_the_module_loop_requires_a_built_file():
    """A real model reads its spec: a sign-off whose predicate is the build's says no to an empty site/."""
    from ai_sdlc_runner import graph

    specs = _specs()
    before_loop = [n.id for n in graph.NODES[:graph.NODES.index(graph.BY_ID["next_module"])]
                   if n.id in specs and n.role is not None or n.id == "intake"]
    assert before_loop == PRE_BUILD, "a node was added before the module loop: place it"
    for node in PRE_BUILD:
        assert not _requires_a_site_file(specs[node]), node
        assert specs[node]["expected_outputs"] == [], node


def test_the_plan_stage_specs_judge_the_plan_and_pm_signoff_does_not_ask_for_the_assessment():
    specs = _specs()
    for node in PRE_BUILD:
        assert "plan" in specs[node]["acceptance_predicate"], node
        assert specs[node]["instructions"].endswith("Do not create or change any file."), node
    signoff = specs["pm_signoff"]["instructions"]
    assert "no lead assessment is attached" in signoff and "empty site/ is expected" in signoff


def test_engineer_build_names_exactly_one_module_to_build():
    spec = _specs()["engineer_build"]
    assert "the first file in the brief's numbered list that does not yet exist" in spec["instructions"]
    for field in ("scope", "instructions", "done_criteria", "acceptance_predicate", "expected_outputs"):
        named = [m for m in MODULES if m in json.dumps(spec[field])]
        assert named == [], (field, "the spec lists modules instead of naming one", named)
    assert "all ten files exist" not in spec["acceptance_predicate"]
    assert "exists under site/" in spec["acceptance_predicate"]


def test_the_module_stage_judges_one_module_and_never_all_ten():
    specs = _specs()
    for node in ("next_module", "engineer_build", "engineer_selfverify", "lead_task_review",
                 "record_module", "fix_pass", "re_review", "halt_second_fail"):
        assert "all ten" not in specs[node]["acceptance_predicate"], node
        assert not [m for m in MODULES if m in specs[node]["expected_outputs"]], node
        assert "the module" in specs[node]["acceptance_predicate"], node


def test_the_whole_change_stage_judges_the_page_against_the_full_predicate():
    specs = _specs()
    for node in CHANGE_STAGE:
        predicate = specs[node]["acceptance_predicate"]
        assert [m for m in MODULES if m not in predicate + specs[node]["scope"]] == [], node
        assert "all ten files exist" in predicate, node
        assert "no file holds an API key" in predicate, node
        assert "nothing but the two named API hosts" in predicate, node
        assert "error state" in predicate, node


def test_every_node_keeps_the_briefs_rules():
    for node, spec in _specs().items():
        assert "no API key in any file" in spec["instructions"], node
        assert "no made-up or fallback numbers" in spec["instructions"], node


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


def test_the_readme_says_the_measurement_neither_confirmed_nor_left_out_the_cwa():
    readme = " ".join((EXAMPLE / "README.md").read_text(encoding="utf-8").split())
    assert "not confirmed here" in readme and "task 1a" in readme
    assert "no key reached that session" in readme
    assert "neither confirmed nor left out" in readme
    assert "left out if" not in readme and "checked against the API" not in readme


def test_runner_yaml_and_readme_say_the_boundary_is_the_tool_list_not_paths():
    for name in ("runner.yaml", "README.md"):
        text = " ".join((EXAMPLE / name).read_text(encoding="utf-8").split())
        assert "tool list, not paths" in text.lower(), name
        assert "bwrap" in text and "permission behaviour" in text, name


def test_the_dry_run_refuses_a_models_file_without_the_model_the_plan_names(tmp_path):
    empty = tmp_path / "models.json"
    empty.write_text('{"models": []}', encoding="utf-8")
    done = _run("--dry-run", "--models", str(empty))
    assert done.returncode != 0 and "sonnet-writer" in (done.stdout + done.stderr)


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
import json, os, sys
from pathlib import Path
order = json.loads(sys.stdin.read())
node, seat = order["node_id"], order.get("seat")
MODULES = %r
def say(payload):
    print(json.dumps(payload)); sys.exit(0)
if node == "intake_review":
    # The way a survey seat calls a requirement unsafe: an `unsafe` list of strings in its answer.
    # Once, and only when the test asks for it.
    if seat == "risk" and os.environ.get("STAND_IN_UNSAFE") and not Path(".unsafe-said").exists():
        Path(".unsafe-said").write_text("1")
        say({"missing": [], "problems": [], "unsafe": ["the key goes in the URL query string"]})
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
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
    work = tmp_path / "work"
    hook = tmp_path / "hook.py"
    hook.write_text("import sys\nopen(sys.argv[1], 'a').write(' '.join(sys.argv[2:]) + '\\n')\n",
                    encoding="utf-8")
    seen = tmp_path / "nodes.txt"

    done = _run("--runner-yaml", str(config), "--workdir", str(work),
                "--on-node", shlex.join([sys.executable, str(hook), str(seen)])
                if os.name != "nt" else subprocess.list2cmdline([sys.executable, str(hook), str(seen)]), cwd=tmp_path)

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


def test_start_when_asks_nothing_until_the_file_appears(tmp_path):
    import os
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
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            if "waiting for" in line:
                break
        assert any("serving" in l for l in lines) and "waiting for" in lines[-1]
        time.sleep(2)                       # long enough for a run that ignored the flag to ask
        asks = work / ".runner" / "asks"
        assert not (asks.is_dir() and list(asks.glob("*.json")))
        assert not (work / ".built").exists()
        assert proc.poll() is None
        go.write_text("", encoding="utf-8")
        rest, _ = proc.communicate(timeout=300)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, "".join(lines) + rest
    assert "final node:  done  (state finished" in rest
    assert list((work / ".runner" / "asks").glob("*.json"))


def test_drive_copies_the_models_file_and_the_build_is_asked_through_it(tmp_path):
    """A stand-in registry under the same id: the build's asks go to it, every other ask does not."""
    backend = tmp_path / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    marker = tmp_path / "writer_asks.txt"
    wrapper = tmp_path / "writer.py"
    wrapper.write_text("import sys, json\nraw = sys.stdin.read()\n"
                       f"open({str(marker)!r}, 'a').write(json.loads(raw)['node_id'] + '\\n')\n"
                       f"import subprocess\nr = subprocess.run([{sys.executable!r}, {str(backend)!r}], "
                       "input=raw, text=True, capture_output=True)\nsys.stdout.write(r.stdout)\n",
                       encoding="utf-8")
    config = tmp_path / "runner.yaml"
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
    (tmp_path / "models.json").write_text(json.dumps({"models": [{
        "id": "sonnet-writer", "vendor": "test", "name": "stand-in", "transport": "cli",
        "command": [sys.executable, str(wrapper)]}]}), encoding="utf-8")
    work = tmp_path / "work"
    done = _run("--runner-yaml", str(config), "--workdir", str(work), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "final node:  done  (state finished" in done.stdout
    assert (work / ".runner" / "models.json").is_file()
    asked = marker.read_text(encoding="utf-8").split()
    assert set(asked) == {"engineer_build", "engineer_selfverify"}, "only the build and what follows it"
    assert asked.count("engineer_build") == len(MODULES)


# ── a stop that needs a person is never answered by drive.py ──────────────────────────────────────

def _stand_in_config(tmp_path):
    backend = tmp_path / "stand_in.py"
    backend.write_text(STAND_IN, encoding="utf-8")
    config = tmp_path / "runner.yaml"
    config.write_text("agent_command: " + json.dumps([sys.executable, backend.as_posix()])
                      + "\nagent_timeout: 60\n", encoding="utf-8")
    return config


def _start_unsafe(tmp_path, *extra):
    import os
    work = tmp_path / "work"
    proc = subprocess.Popen(
        [sys.executable, str(DRIVE), "--runner-yaml", str(_stand_in_config(tmp_path)),
         "--workdir", str(work), *extra], cwd=str(tmp_path), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONUTF8": "1", "STAND_IN_UNSAFE": "1"})
    lines = []
    for line in proc.stdout:
        lines.append(line)
        if line.startswith("AWAITING-PERSON "):
            break
    return proc, work, lines


def test_an_unsafe_stop_waits_for_the_person_and_proceeds_only_on_their_file(tmp_path):
    import time
    proc, work, lines = _start_unsafe(tmp_path)
    try:
        assert lines[-1].startswith("AWAITING-PERSON "), "".join(lines)
        text = Path(lines[-1].split(" ", 1)[1].strip())
        assert text.name == "001-intake_review.md"
        assert work.resolve() not in text.resolve().parents, "the build model must not reach it"
        said = text.read_text(encoding="utf-8")
        assert "risk" in said and "the key goes in the URL query string" in said
        assert "intake_review" in said and "POST /run/proceed" in said
        time.sleep(3)                       # a driver that approved on its own would be past it
        assert proc.poll() is None
        assert not (work / "site").exists() and not (work / ".built").exists()
        text.with_suffix(".proceed").write_text("", encoding="utf-8")
        rest, _ = proc.communicate(timeout=300)
    finally:
        if proc.poll() is None:
            proc.kill()
    out = "".join(lines) + rest
    assert proc.returncode == 0, out
    assert re.search(r"^PERSON-ANSWERED proceed \d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", rest, re.M), out
    assert out.count("AWAITING-PERSON") == 1
    assert "final node:  done  (state finished" in out and "gate merge" in out
    token = (work / ".runner" / "operator.token").read_text(encoding="utf-8").strip()
    assert token not in out


def test_a_stop_file_ends_the_run_with_a_nonzero_exit(tmp_path):
    proc, work, lines = _start_unsafe(tmp_path)
    try:
        Path(lines[-1].split(" ", 1)[1].strip()).with_suffix(".stop").write_text("", encoding="utf-8")
        rest, _ = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode != 0
    assert "STOPPED-BY-PERSON" in rest and "PERSON-ANSWERED" not in rest
    assert not (work / "site").exists()


def test_a_person_dir_inside_the_workdir_is_refused(tmp_path):
    work = tmp_path / "work"
    done = _run("--runner-yaml", str(_stand_in_config(tmp_path)), "--workdir", str(work),
                "--person-dir", str(work / "sub" / ".." / "person"), cwd=tmp_path)
    assert done.returncode != 0 and "inside the workdir" in done.stdout + done.stderr
    assert not (work / ".runner").exists(), "nothing was started"


def test_a_proceed_that_exists_before_the_stop_does_not_answer_it(tmp_path):
    where = tmp_path / "elsewhere"
    where.mkdir()
    (where / "001-intake_review.proceed").write_text("", encoding="utf-8")
    proc, work, lines = _start_unsafe(tmp_path, "--person-dir", str(where))
    try:
        rest, _ = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    out = "".join(lines) + rest
    assert proc.returncode != 0 and "already existed" in out, out
    assert "PERSON-ANSWERED" not in out and not (work / "site").exists()


def test_person_dir_moves_the_files(tmp_path):
    where = tmp_path / "elsewhere"
    proc, work, lines = _start_unsafe(tmp_path, "--person-dir", str(where))
    try:
        assert Path(lines[-1].split(" ", 1)[1].strip()).parent == where.resolve()
        (where / "001-intake_review.stop").write_text("", encoding="utf-8")
        proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode != 0


def test_an_unexpected_refusal_prints_the_servers_message_and_exits_cleanly(tmp_path):
    """A route that 409s must not leave the server running or die without saying why."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("weather_live_drive", DRIVE)
    drive = importlib.util.module_from_spec(spec)
    sys.modules["weather_live_drive"] = drive
    spec.loader.exec_module(drive)
    console = drive.Console(1, "t")
    console.call = lambda path, body=None: (
        (200, {"version": 3}) if body is None else (409, {"error": "not what it waits for"}))
    with pytest.raises(drive.Refused, match=r"/run/gate was refused \(409\): not what it waits for"):
        console.act("/run/gate", {})
    stop = {"unsafe": True, "node_id": "intake_review", "safety": {"risk": ["x"]}}
    assert drive.stop_kind(stop) == "unsafe" and drive.stop_kind({"gate": "merge"}) == "gate"
    assert drive.stop_kind({"incomplete": True}) == "incomplete"
    assert drive.stop_kind({"undecided": True}) == "undecided"


def test_a_workdir_that_is_not_empty_is_refused_and_nothing_is_copied(tmp_path):
    work = tmp_path / "project"
    work.mkdir()
    (work / "keep.txt").write_text("mine", encoding="utf-8")
    done = _run("--runner-yaml", str(_stand_in_config(tmp_path)), "--workdir", str(work), cwd=tmp_path)
    assert done.returncode != 0 and "not empty" in done.stdout + done.stderr
    assert sorted(p.name for p in work.iterdir()) == ["keep.txt"]


def test_an_existing_empty_workdir_is_used(tmp_path):
    work = tmp_path / "empty"
    work.mkdir()
    done = _run("--runner-yaml", str(_stand_in_config(tmp_path)), "--workdir", str(work), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


def test_drive_prints_the_servers_models_line_where_the_commands_go_and_the_relaxations(tmp_path):
    work = tmp_path / "work"
    done = _run("--runner-yaml", str(_stand_in_config(tmp_path)), "--workdir", str(work), cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert re.search(r"^server: models +\d+ registered, \d+ of which leave this machine", out, re.M)
    assert "agent_command: python" in out
    token = (work / ".runner" / "operator.token").read_text(encoding="utf-8").strip()
    assert token not in out and "#token=" not in out
    assert re.search(r"^relaxation:  ", out, re.M)


def test_the_reach_line_names_the_program():
    drive = _drive_module()
    assert drive.reach_line("agent_command", "claude") == (
        "agent_command: claude — leaves this machine (the work order goes to the vendor)")
    assert "local script" in drive.reach_line("agent_command", "python3")


def test_the_relaxations_are_read_from_the_conversation(tmp_path):
    drive = _drive_module()
    assert drive.relaxations(tmp_path) == []
