"""CHG-20261005-01 — a model's tier and effort, a default model for the coding role, `runner setup`.

KN-8: each test here is the one that fails when its wire is cut. Cutting `effort_argv` out of the
factory, `coder_defaults` out of `cmd_run` or `cmd_serve`, the `ALTER TABLE` out of the migration,
or `detect.propose` out of `cmd_setup` each turns one of these red; a test that only called the
helper in isolation would stay green through all four.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, detect, engine, graph, models, settings as settings_mod, store

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}

#: Every ask appends `node_id model argv...` to the log, then answers as the settings tests' stub does.
AGENT = """
import json, sys
order = json.load(sys.stdin)
with open(%(log)r, "a", encoding="utf-8") as fh:
    fh.write(json.dumps([order.get("node_id"), sys.argv[1:]]) + "\\n")
answers = %(answers)r
if order.get("seat"):
    if order["node_id"] == "intake_review":
        print(json.dumps({"problems": [], "missing": [], "unsafe": []}))
    else:
        print(json.dumps({"verdict": "pass"}))
else:
    branch = answers.get(order["node_id"])
    print(json.dumps({"verdict": branch} if branch else {"ok": True}))
"""


def _cli(**over):
    base = dict(id="opus", vendor="anthropic", name="claude-opus-5", transport="cli",
                command=("claude", "-p"))
    return models.Model(**{**base, **over})


def _api(**over):
    base = dict(id="gpt", vendor="openai", name="gpt-5", transport="api",
                endpoint="https://api.example.com/v1", key_env="OPENAI_API_KEY")
    return models.Model(**{**base, **over})


# ── 1 · the registry: refusals and persistence ─────────────────────────────────────────────────

def test_an_unknown_tier_is_refused():
    with pytest.raises(models.ModelError, match="tier"):
        models.validate(_cli(tier="medium"))
    for ok in ("", "high", "mid", "low"):
        assert models.validate(_cli(tier=ok)).tier == ok


def test_an_effort_template_with_no_slot_is_refused():
    with pytest.raises(models.ModelError, match=r"\{effort\}"):
        models.validate(_cli(effort_argv=("--effort", "high")))
    assert models.validate(_cli(effort_argv=("--effort", "{effort}")))
    # The slot may sit inside one element, as `-c key={effort}` does.
    assert models.validate(_cli(effort_argv=("-c", "model_reasoning_effort={effort}")))


def test_an_api_model_cannot_carry_an_effort_template():
    with pytest.raises(models.ModelError, match="effort_argv"):
        models.validate(_api(effort_argv=("--effort", "{effort}")))


def test_with_effort_substitutes_every_element():
    model = _cli(effort_argv=("-c", "e={effort}", "--also", "{effort}"))
    assert models.with_effort(model, "high") == ["-c", "e=high", "--also", "high"]
    assert models.with_effort(_cli(), "high") is None


def test_tier_and_effort_survive_the_registry_file(tmp_path):
    registry = models.Registry(models=(
        _cli(tier="mid", effort_argv=("--effort", "{effort}")),))
    models.save(registry, tmp_path / "models.json")
    back = models.load(tmp_path / "models.json").get("opus")
    assert back.tier == "mid" and back.effort_argv == ("--effort", "{effort}")
    # And the file stays closed: a misspelt key is still refused rather than ignored.
    bad = {"models": [{**registry.get("opus").as_dict(), "tierr": "mid"}]}
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(models.ModelError):
        models.load(tmp_path / "bad.json")


# ── 1 · the store: schema 3 -> 4 on a real v3 database ─────────────────────────────────────────

def _v3_store(path: Path) -> None:
    """A database exactly as schema 3 left it: the three older statement groups, no new columns."""
    db = sqlite3.connect(str(path))
    for statement in store._SCHEMA_1 + store._SCHEMA_2 + store._SCHEMA_3:
        db.execute(statement)
    db.execute("INSERT INTO models (id, vendor, name, transport, command_json) "
               "VALUES ('old', 'v', 'n', 'cli', '[\"agent\"]')")
    db.execute("INSERT INTO node_assignments VALUES ('engineer_build', 0, 'old')")
    db.execute("PRAGMA user_version = 3")
    db.commit()
    db.close()


def test_a_schema_3_store_migrates_and_keeps_what_it_held(tmp_path):
    path = tmp_path / "v3.sqlite"
    _v3_store(path)
    before = sqlite3.connect(str(path))
    assert [r[1] for r in before.execute("PRAGMA table_info(models)")][-1] == "note"
    before.close()

    db = store.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 4 == store.SCHEMA_VERSION
    assert [r[1] for r in db.execute("PRAGMA table_info(models)")][-3:] == [
        "tier", "effort_argv", "declared_reach"]
    old = store.load_registry(db).get("old")
    assert old.tier == "" and old.effort_argv == () and old.command == ("agent",)
    assert store.node_models(db) == {"engineer_build": ["old"]}, "the assignment was lost"

    # And a write through the new columns reads back.
    store.save_registry(db, store.load_registry(db).add(
        _cli(tier="mid", effort_argv=("--effort", "{effort}"))))
    again = store.load_registry(store.connect(path)).get("opus")
    assert again.tier == "mid" and again.effort_argv == ("--effort", "{effort}")


def test_migrating_twice_is_a_no_op(tmp_path):
    path = tmp_path / "v3.sqlite"
    _v3_store(path)
    store.connect(path).close()
    db = store.connect(path)
    assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_a_schema_3_store_with_a_mangled_models_table_is_still_refused(tmp_path):
    """`_verify_or_refuse` still compares columns exactly: relaxing it for 4 must not bless a stranger."""
    path = tmp_path / "odd.sqlite"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE models (id TEXT PRIMARY KEY, vendor TEXT)")
    db.commit()
    db.close()
    with pytest.raises(store.StoreError, match="already exists"):
        store.connect(path)


# ── 2 · effort reaches the process ─────────────────────────────────────────────────────────────

def test_the_factory_appends_the_substituted_template():
    registry = models.Registry(models=(
        _cli(id="m", command=("agent", "-p"), effort_argv=("--effort", "{effort}")),))
    factory = cli.session_factory({}, registry=registry)
    session = factory(model="m", effort="high")
    assert session.argv == ["agent", "-p", "--effort", "high"]
    assert session.effort_applied is True


def test_no_effort_means_the_argv_is_untouched():
    registry = models.Registry(models=(
        _cli(id="m", command=("agent", "-p"), effort_argv=("--effort", "{effort}")),))
    session = cli.session_factory({}, registry=registry)(model="m")
    assert session.argv == ["agent", "-p"]


def test_a_model_without_a_template_says_it_did_not_apply_the_effort():
    registry = models.Registry(models=(_cli(id="m", command=("agent", "-p")),))
    session = cli.session_factory({}, registry=registry)(model="m", effort="high")
    assert session.argv == ["agent", "-p"], "no template, so nothing is invented"
    assert session.effort_applied is False


def test_the_engine_hands_the_effort_to_a_factory_that_asks_and_records_the_miss():
    """Through `engine.walk`: the engine passes `effort` by node, and a backend that did not apply it
    is named on the report (KN-11) — once per node and model, not once per ask."""
    seen = []

    class Quiet(engine.Session):
        def ask(self, order):
            if order.get("seat"):
                if order["node_id"] == "intake_review":
                    return {"problems": [], "missing": [], "unsafe": []}
                return {"verdict": "pass"}
            branch = ANSWERS.get(order["node_id"])
            return {"verdict": branch} if branch else {"ok": True}

        def close(self):
            pass

    def factory(seat=None, model=None, effort=""):
        seen.append((model, effort))
        return Quiet()

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none"], "feedback": "done"},
        risk="low", efforts={"engineer_build": "high"}, undeclared="allow", confirmed=("merge",))
    report = engine.walk(cfg, factory, enabled=True)
    assert report.state == engine.FINISHED, (report.state, report.halt_reason)
    assert (None, "high") in seen
    assert [e for _, e in seen if e] == ["high"] * len([1 for _, e in seen if e])
    assert report.effort_not_applied == ["engineer_build: (the default backend)"]
    assert report.as_dict()["effort_not_applied"] == report.effort_not_applied


# ── 3 · settings ───────────────────────────────────────────────────────────────────────────────

def test_the_coder_settings_round_trip_and_default(tmp_path):
    assert settings_mod.Settings().coder_model == ""
    assert settings_mod.Settings().coder_effort == "medium"
    path = str(tmp_path / "s.json")
    settings_mod.save(settings_mod.Settings(coder_model="sonnet", coder_effort="high"), path)
    back = settings_mod.load(path)
    assert (back.coder_model, back.coder_effort) == ("sonnet", "high")
    assert back.as_dict()["coder_model"] == "sonnet"
    assert "coder model: sonnet" in back.describe() and "coder effort: high" in back.describe()


def test_a_bad_coder_effort_or_model_is_refused_on_load_and_on_save(tmp_path):
    path = tmp_path / "s.json"
    for body in ({"coder_effort": "extreme"}, {"coder_model": 7}):
        path.write_text(json.dumps(body), encoding="utf-8")
        with pytest.raises(settings_mod.SettingsError):
            settings_mod.load(str(path))
    with pytest.raises(settings_mod.SettingsError):
        settings_mod.save(settings_mod.Settings(coder_effort="extreme"), str(path))


def _scripted(*answers):
    said = iter(answers)
    return lambda prompt="": next(said)


def _row(label):
    return [r[0] for r in settings_mod._screen(settings_mod.Settings())].index(label) + 1


def test_the_screen_edits_the_coder_effort_and_model():
    chosen = settings_mod.edit(
        settings_mod.Settings(),
        input_fn=_scripted(str(_row("Coder effort")), "3",
                           str(_row("Coder model")), "sonnet",
                           str(_row("Save and close"))))
    assert (chosen.coder_effort, chosen.coder_model) == ("high", "sonnet")


def test_a_coder_row_cancelled_changes_nothing():
    chosen = settings_mod.edit(
        settings_mod.Settings(coder_effort="low"),
        input_fn=_scripted(str(_row("Coder effort")), "q", str(_row("Save and close"))))
    assert chosen.coder_effort == "low"


# ── 3 · the resolution order, step by step ─────────────────────────────────────────────────────

def _registry(*entries):
    return models.Registry(models=tuple(entries))


def test_an_assignment_from_the_plan_or_store_is_left_alone():
    registry = _registry(_cli(id="a", tier="mid"), _cli(id="b"))
    merged, _, notices = cli.coder_defaults(
        {"engineer_build": ["b"]}, registry, settings_mod.Settings(coder_model="a"))
    assert merged["engineer_build"] == ["b"] and notices == []


def test_coder_model_comes_before_the_lone_mid_model():
    registry = _registry(_cli(id="a", tier="mid"), _cli(id="b"))
    merged, _, _ = cli.coder_defaults({}, registry, settings_mod.Settings(coder_model="b"))
    assert merged["engineer_build"] == ["b"]


def test_the_only_mid_model_is_the_default():
    registry = _registry(_cli(id="a", tier="mid"), _cli(id="b", tier="low"))
    merged, _, notices = cli.coder_defaults({}, registry, settings_mod.Settings())
    assert merged["engineer_build"] == ["a"]
    # Picked by a rule nobody was asked about, so it is said: which model, and that it stays here.
    assert len(notices) == 1 and "a is the only tier 'mid'" in notices[0]
    assert "runs on this machine" in notices[0]


def test_a_lone_mid_model_that_leaves_the_machine_says_so():
    registry = _registry(_cli(id="a", tier="mid", declared_reach="external", vendor="acme"))
    merged, _, notices = cli.coder_defaults({}, registry, settings_mod.Settings())
    assert merged["engineer_build"] == ["a"]
    assert len(notices) == 1 and "a " in notices[0] and "acme" in notices[0]
    assert "repository's content" in notices[0] and "external" in notices[0]
    assert "runs on this machine" not in notices[0]


def test_the_run_prints_the_lone_mid_notice(tmp_path, capsys):
    _project(tmp_path, [dict(id="solo", vendor="acme", name="n", transport="cli", tier="mid",
                             declared_reach="external", **TEMPLATE)])
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert "solo is the only tier 'mid'" in out and "sends the work order" in out and "acme" in out


def test_several_mid_models_are_named_and_none_is_picked():
    registry = _registry(_cli(id="a", tier="mid"), _cli(id="b", tier="mid"))
    merged, _, notices = cli.coder_defaults({}, registry, settings_mod.Settings())
    assert "engineer_build" not in merged
    assert len(notices) == 1 and "a, b" in notices[0] and "coder_model" in notices[0]


def test_no_mid_model_and_no_setting_changes_nothing():
    merged, efforts, notices = cli.coder_defaults(
        {"lead_review": ["x"]}, _registry(_cli(id="a")), settings_mod.Settings())
    assert merged == {"lead_review": ["x"]} and notices == []
    assert cli.coder_defaults({}, None, settings_mod.Settings())[0] == {}


def test_an_unknown_coder_model_is_an_error_not_a_fallback():
    with pytest.raises(cli.CliError, match="nope"):
        cli.coder_defaults({}, _registry(_cli(id="a", tier="mid")),
                           settings_mod.Settings(coder_model="nope"))
    with pytest.raises(cli.CliError, match="registry"):
        cli.coder_defaults({}, None, settings_mod.Settings(coder_model="nope"))


def test_the_effort_goes_to_the_build_node_and_what_follows_it_only():
    _, efforts, _ = cli.coder_defaults({}, None, settings_mod.Settings(coder_effort="low"))
    follows = {n.id for n in graph.NODES if n.follows == "engineer_build"}
    assert follows, "the flow has nodes that follow the build"
    assert set(efforts) == {"engineer_build"} | follows
    assert set(efforts.values()) == {"low"}


# ── 3 · through `runner run`, to the process that is spawned ───────────────────────────────────

def _project(tmp_path, entries, saved=None, plan_extra=None):
    """A store holding `entries`, an agent that logs its argv, and the three files `run` takes."""
    log = tmp_path / "log.jsonl"
    agent = tmp_path / "agent.py"
    agent.write_text(AGENT % {"log": str(log), "answers": ANSWERS}, encoding="utf-8")
    registry = models.Registry(models=tuple(
        models.Model(command=(sys.executable, str(agent), "--as", e["id"]), **e)
        for e in entries))
    db = store.connect(tmp_path / "config.sqlite")
    store.save_registry(db, registry)
    db.close()
    (tmp_path / "runner.yaml").write_text(
        f"agent_command: {json.dumps([sys.executable, str(agent), '--as', 'default'])}\n",
        encoding="utf-8")
    (tmp_path / "settings.json").write_text(json.dumps(saved or {}), encoding="utf-8")
    plan = {"node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
            "decisions": {"next_module": ["module", "none"], "feedback": "done"},
            "risk": "low", **(plan_extra or {})}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return log


def _run(tmp_path, capsys):
    code = cli.main(["--config", str(tmp_path / "runner.yaml"),
                     "--settings", str(tmp_path / "settings.json"),
                     "run", "--undeclared", "allow", "--plan", str(tmp_path / "plan.json"),
                     "--confirm", "merge", "--assignment-store", str(tmp_path / "config.sqlite")])
    return code, capsys.readouterr().out


def _asks(log):
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _argv_of(asks, node_id):
    return [argv for node, argv in asks if node == node_id]


TEMPLATE = {"effort_argv": ("--effort", "{effort}")}
FOLLOWERS = ["engineer_selfverify"]      # `fix_pass` follows it too, and a green lap never asks it
assert all(graph.BY_ID[n].follows == "engineer_build" for n in FOLLOWERS)


def test_run_builds_with_coder_model_at_coder_effort_and_nobody_else_gets_an_effort(
        tmp_path, capsys):
    log = _project(
        tmp_path,
        [dict(id="coder", vendor="v", name="n", transport="cli", **TEMPLATE),
         dict(id="other", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE)],
        saved={"coder_model": "coder", "coder_effort": "high"})
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    asks = _asks(log)
    assert _argv_of(asks, "engineer_build") == [["--as", "coder", "--effort", "high"]]
    for node in FOLLOWERS:
        assert _argv_of(asks, node) == [["--as", "coder", "--effort", "high"]], node
    for node, argv in asks:
        if node != "engineer_build" and node not in FOLLOWERS:
            assert "--effort" not in argv, f"{node} got an effort it was never given: {argv}"
    assert "effort:        not applied" not in out
    assert "engineer_build: lead dispatched to coder" in out, "the dispatch record is unchanged"


def test_run_uses_the_only_mid_model_at_the_default_effort(tmp_path, capsys):
    log = _project(
        tmp_path,
        [dict(id="mid1", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE),
         dict(id="big", vendor="v", name="n", transport="cli", tier="high", **TEMPLATE)])
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert _argv_of(_asks(log), "engineer_build") == [["--as", "mid1", "--effort", "medium"]]


def test_run_with_several_mid_models_says_so_and_picks_none(tmp_path, capsys):
    log = _project(
        tmp_path,
        [dict(id="m1", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE),
         dict(id="m2", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE)])
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert "m1, m2" in out and "coder_model" in out
    assert _argv_of(_asks(log), "engineer_build")[0][:2] == ["--as", "default"]


def test_run_lets_the_plan_beat_the_coder_default(tmp_path, capsys):
    log = _project(
        tmp_path,
        [dict(id="coder", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE),
         dict(id="planned", vendor="v", name="n", transport="cli", **TEMPLATE)],
        plan_extra={"node_models": {"engineer_build": ["planned"]}})
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert _argv_of(_asks(log), "engineer_build") == [["--as", "planned", "--effort", "medium"]]


def test_run_reports_an_effort_the_model_could_not_take(tmp_path, capsys):
    log = _project(
        tmp_path, [dict(id="plain", vendor="v", name="n", transport="cli", tier="mid")])
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert _argv_of(_asks(log), "engineer_build") == [["--as", "plain"]]
    assert "effort:        not applied for engineer_build: plain" in out
    for node in FOLLOWERS:
        assert f"not applied for {node}: plain" in out


def test_run_refuses_a_coder_model_the_registry_does_not_have(tmp_path, capsys):
    log = _project(
        tmp_path, [dict(id="a", vendor="v", name="n", transport="cli", tier="mid")],
        saved={"coder_model": "ghost"})
    code, out = _run(tmp_path, capsys)
    assert code == 2 and "ghost" in out
    assert not log.exists(), "nothing was dispatched"


# ── 3 · and through `runner serve`'s `make_config` ─────────────────────────────────────────────

def _serve(tmp_path, monkeypatch, capsys):
    """Start `cmd_serve` as far as the `Runner` it builds, and hand back its `make_config`."""
    from ai_sdlc_runner import server

    captured = {}

    class Catch:
        def __init__(self, **kw):
            captured.update(kw)

    def stop(*a, **kw):
        raise server.ServerError("stopped by the test")

    monkeypatch.setattr(server, "Runner", Catch)
    monkeypatch.setattr(server, "serve", stop)
    code = cli.main(["--config", str(tmp_path / "runner.yaml"),
                     "--settings", str(tmp_path / "settings.json"),
                     "serve", "--plan", str(tmp_path / "plan.json"),
                     "--token-dir", str(tmp_path / "tok"),
                     "--assignment-store", str(tmp_path / "config.sqlite"),
                     "--ask-journal", str(tmp_path / "asks")])
    return code, capsys.readouterr().out, captured.get("make_config")


def test_serve_builds_the_same_coder_defaults(tmp_path, monkeypatch, capsys):
    _project(tmp_path,
             [dict(id="coder", vendor="v", name="n", transport="cli", **TEMPLATE)],
             saved={"coder_model": "coder", "coder_effort": "low"})
    code, out, make_config = _serve(tmp_path, monkeypatch, capsys)
    assert code == 2 and "stopped by the test" in out, out
    cfg = make_config((), (), ())
    assert cfg.node_models["engineer_build"] == ["coder"]
    assert cfg.efforts["engineer_build"] == "low"
    assert {n.id for n in graph.NODES if n.follows == "engineer_build"} <= set(cfg.efforts)


def test_serve_refuses_an_unknown_coder_model_before_it_starts(tmp_path, monkeypatch, capsys):
    _project(tmp_path, [dict(id="a", vendor="v", name="n", transport="cli")],
             saved={"coder_model": "ghost"})
    code, out, _ = _serve(tmp_path, monkeypatch, capsys)
    assert code == 2 and "ghost" in out and "stopped by the test" not in out


# ── 4 · `runner setup` ─────────────────────────────────────────────────────────────────────────

def _fake(directory: Path, name: str, body: str) -> Path:
    """An executable called `name` that runs the Python in `body`. A `.cmd` shim on Windows."""
    directory.mkdir(parents=True, exist_ok=True)
    # Not `.py`: a Windows PATHEXT may list it, and `find_tool` would then rightly pick the script
    # over the shim, so the tests would assert a path nobody dispatches.
    script = directory / (name + ".impl")
    script.write_text(body, encoding="utf-8")
    if os.name == "nt":                                      # pragma: no cover
        shim = directory / (name + ".cmd")
        shim.write_text(f'@"{sys.executable}" "%~dp0{name}.impl" %*\r\n', encoding="utf-8")
        return shim
    shim = directory / name
    shim.write_text(f'#!{sys.executable}\nexec(open({str(script)!r}, encoding="utf-8").read())\n',
                    encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _shim(directory: Path, name: str) -> Path:
    """Where `_fake` put the runnable file for `name`."""
    return directory / (name + (".cmd" if os.name == "nt" else ""))


def _marker(directory: Path, name: str) -> str:
    """A body that records it was run, which is what must not happen to `claude` and `codex`."""
    return f'open({str(directory / (name + ".ran"))!r}, "w").write("ran")\n'


OLLAMA_LIST = """
import sys
if sys.argv[1:] == ["list"]:
    print("NAME                ID            SIZE      MODIFIED")
    print("llama3:8b           abc123        4.7 GB    2 days ago")
    print("qwen2.5-coder:7b    def456        4.4 GB    3 weeks ago")
else:
    open(sys.argv[0] + ".bad", "w").write(" ".join(sys.argv))
"""


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A PATH holding fake `claude`, `codex` and `ollama`, and a working directory that is not it."""
    bin_dir = tmp_path / "bin"
    for name in ("claude", "codex"):
        _fake(bin_dir, name, _marker(bin_dir, name))
    _fake(bin_dir, "ollama", OLLAMA_LIST)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setattr(cli, "_interactive", lambda: False)
    return bin_dir


def _setup(tmp_path, *extra):
    return cli.main(["--settings", str(tmp_path / "settings.json"), "setup",
                     "--token-dir", str(tmp_path / "tok"), *extra])


def test_detection_finds_the_three_tools_on_an_absolute_path(machine):
    for name in detect.TOOLS:
        found = detect.find_tool(name, path=str(machine))
        # The file the fake planted: `name` on POSIX, `name.cmd` on Windows, never a bare name there.
        assert found and os.path.normcase(found) == os.path.normcase(str(_shim(machine, name))), name


def test_on_windows_a_cmd_shim_beats_the_extensionless_npm_script(tmp_path, monkeypatch):
    # npm's layout: a POSIX sh script beside `.cmd` and `.ps1`. Windows cannot run the first, and the
    # path found is the path dispatched, so choosing it registers a command that never starts.
    for leaf in ("claude", "claude.cmd", "claude.ps1"):
        (tmp_path / leaf).write_text("x", encoding="utf-8")
    monkeypatch.setattr(detect, "_on_windows", lambda: True)
    environ = {"PATHEXT": ".exe;.cmd"}
    assert detect.find_tool("claude", path=str(tmp_path), environ=environ) == str(
        tmp_path / "claude.cmd")
    # With no shim at all, the bare script is not an answer on Windows.
    (tmp_path / "claude.cmd").unlink()
    assert detect.find_tool("claude", path=str(tmp_path), environ=environ) is None
    # A name that already carries a PATHEXT extension is tried as written.
    assert detect.find_tool("claude.ps1", path=str(tmp_path),
                            environ={"PATHEXT": ".ps1"}) == str(tmp_path / "claude.ps1")


def test_detection_never_looks_in_the_working_directory_or_a_relative_entry(tmp_path, monkeypatch):
    planted = tmp_path / "repo"
    _fake(planted, "claude", "")
    monkeypatch.chdir(planted)
    # Listed as the cwd by absolute path, as `.`, as empty (which means cwd to a shell), and relative.
    search = os.pathsep.join([str(planted), ".", "", "repo", str(tmp_path / "nowhere")])
    assert detect.find_tool("claude", path=search) is None
    # The same file is found once its directory is an ordinary absolute PATH entry elsewhere.
    monkeypatch.chdir(tmp_path)
    assert detect.find_tool("claude", path=str(planted)) is not None


def test_only_ollama_list_is_ever_run(machine):
    proposals, notes = detect.propose()
    assert notes == []
    assert [m.id for m in proposals] == [
        "claude-sonnet-5-5", "codex", "ollama-llama3-8b", "ollama-qwen2-5-coder-7b"]
    assert not (machine / "claude.ran").exists() and not (machine / "codex.ran").exists()
    assert not list(machine.glob("*.bad")), "ollama was run with something other than `list`"


def test_the_proposals_are_what_the_record_says(machine):
    by_id = {m.id: m for m in detect.propose()[0]}
    where = lambda tool: detect.find_tool(tool, path=str(machine))
    claude = by_id["claude-sonnet-5-5"]
    assert (claude.tier, claude.command, claude.effort_argv) == (
        "mid", (where("claude"), "-p", "--model", "claude-sonnet-5-5"), ("--effort", "{effort}"))
    codex = by_id["codex"]
    assert (codex.tier, codex.command, codex.effort_argv) == (
        "", (where("codex"), "exec", "-"), ("-c", "model_reasoning_effort={effort}"))
    llama = by_id["ollama-llama3-8b"]
    assert (llama.name, llama.tier, llama.command, llama.effort_argv) == (
        "llama3:8b", "", (where("ollama"), "run", "llama3:8b"), ())
    assert by_id["ollama-qwen2-5-coder-7b"].command == (where("ollama"), "run", "qwen2.5-coder:7b")


def test_a_hung_ollama_is_a_note_not_a_hang(tmp_path):
    slow = _fake(tmp_path / "slow", "ollama", "import time\ntime.sleep(30)\n")
    names, problem = detect.ollama_models(str(slow), timeout=1)
    assert names == [] and "did not answer" in problem


def test_a_failing_ollama_is_a_note(tmp_path):
    bad = _fake(tmp_path / "bad", "ollama", "import sys\nsys.exit(3)\n")
    names, problem = detect.ollama_models(str(bad))
    assert names == [] and "exited 3" in problem


def test_setup_off_a_terminal_prints_and_writes_nothing_without_yes(machine, tmp_path, capsys):
    assert _setup(tmp_path) == 0
    out = capsys.readouterr().out
    assert "propose:       claude-sonnet-5-5" in out and "--yes" in out
    assert not (tmp_path / "tok").exists(), "something was written without an answer"
    assert not (tmp_path / "settings.json").exists()


def test_setup_yes_writes_the_registry_the_store_and_the_coder_model(machine, tmp_path, capsys):
    assert _setup(tmp_path, "--yes") == 0
    ids = {"claude-sonnet-5-5", "codex", "ollama-llama3-8b", "ollama-qwen2-5-coder-7b"}
    from_file = models.load(tmp_path / "tok" / "models.json")
    assert {m.id for m in from_file} == ids
    db = store.connect(tmp_path / "tok" / "config.sqlite")
    from_store = store.load_registry(db)
    assert {m.id for m in from_store} == ids
    assert from_store.get("claude-sonnet-5-5").effort_argv == ("--effort", "{effort}")
    assert store.node_models(db) == {}, "setup assigns nothing to any node"
    assert settings_mod.load(str(tmp_path / "settings.json")).coder_model == "claude-sonnet-5-5"

    # Run again: nothing is added twice, and nothing fails.
    capsys.readouterr()
    assert _setup(tmp_path, "--yes") == 0
    assert "already there: codex" in capsys.readouterr().out
    assert len(models.load(tmp_path / "tok" / "models.json")) == 4


def test_setup_on_a_terminal_asks_about_each_and_writes_only_the_accepted(
        machine, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    # claude: add (1); codex: skip (3); llama: skip; qwen: add; then "use claude as the coder?" no.
    answers = iter(["1", "3", "3", "1", "2"])
    args = cli.build_parser().parse_args(
        ["--settings", str(tmp_path / "settings.json"), "setup", "--token-dir", str(tmp_path / "tok")])
    assert cli.cmd_setup(args, input_fn=lambda prompt="": next(answers)) == 0
    assert {m.id for m in models.load(tmp_path / "tok" / "models.json")} == {
        "claude-sonnet-5-5", "ollama-qwen2-5-coder-7b"}
    assert not (tmp_path / "settings.json").exists(), "coder_model was set after the user said no"


def test_setup_will_not_touch_a_coder_model_somebody_already_chose(machine, tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"coder_model": "mine"}), encoding="utf-8")
    assert _setup(tmp_path, "--yes") == 0
    assert settings_mod.load(str(tmp_path / "settings.json")).coder_model == "mine"


def test_setup_with_nothing_found_says_how_to_add_one_and_writes_nothing(
        tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.chdir(tmp_path)
    assert _setup(tmp_path, "--yes") == 0
    out = capsys.readouterr().out
    assert "nothing found" in out and "docs/MODELS.md" in out
    assert not (tmp_path / "tok").exists()


def test_setup_without_a_store_writes_the_registry_file_only(machine, tmp_path):
    assert _setup(tmp_path, "--yes", "--assignment-store", "none") == 0
    assert (tmp_path / "tok" / "models.json").exists()
    assert not (tmp_path / "tok" / "config.sqlite").exists()


# ── review round 1 ─────────────────────────────────────────────────────────────────────────────

def _interactive_setup(tmp_path, monkeypatch, answers):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    feed = iter(answers)
    args = cli.build_parser().parse_args(
        ["--settings", str(tmp_path / "settings.json"), "setup", "--token-dir", str(tmp_path / "tok")])
    return cli.cmd_setup(args, input_fn=lambda prompt="": next(feed))


def test_setup_lets_the_user_edit_a_proposal_before_it_is_written(machine, tmp_path, monkeypatch):
    # claude: Edit (2) -> id, tier, effort template; codex/llama/qwen: skip; coder_model: no.
    answers = ["2", "my-claude", "high", "--reasoning {effort}", "3", "3", "3", "2"]
    assert _interactive_setup(tmp_path, monkeypatch, answers) == 0
    saved = models.load(tmp_path / "tok" / "models.json")
    assert [m.id for m in saved] == ["my-claude"]
    edited = saved.get("my-claude")
    assert (edited.tier, edited.effort_argv) == ("high", ("--reasoning", "{effort}"))
    assert edited.command == (detect.find_tool("claude", path=str(machine)), "-p", "--model", "claude-sonnet-5-5"), \
        "the command stays as detected"


def test_an_invalid_edit_is_refused_and_asked_again_never_written(
        machine, tmp_path, monkeypatch, capsys):
    # First try: tier "ultra" -> refused, "Yes" try again (1); second try: blank = keep everything.
    answers = ["2", "", "ultra", "", "1", "", "", "", "3", "3", "3", "2"]
    assert _interactive_setup(tmp_path, monkeypatch, answers) == 0
    assert "not accepted" in capsys.readouterr().out
    assert models.load(tmp_path / "tok" / "models.json").get("claude-sonnet-5-5").tier == "mid"


def test_giving_up_on_a_bad_edit_skips_the_proposal(machine, tmp_path, monkeypatch):
    answers = ["2", "", "ultra", "", "2", "3", "3", "3"]
    assert _interactive_setup(tmp_path, monkeypatch, answers) == 0
    assert not (tmp_path / "tok").exists()


def test_an_edit_cannot_take_an_id_already_in_the_registry(machine, tmp_path, monkeypatch, capsys):
    # claude: add; codex: edit to the id "claude-sonnet-5-5" -> refused, give up; the rest skipped.
    answers = ["1", "2", "claude-sonnet-5-5", "", "", "2", "3", "3", "2"]
    assert _interactive_setup(tmp_path, monkeypatch, answers) == 0
    assert "already in the registry" in capsys.readouterr().out
    assert [m.id for m in models.load(tmp_path / "tok" / "models.json")] == ["claude-sonnet-5-5"]


def test_a_proposals_command_starts_with_the_absolute_path_that_was_found(machine):
    by_id = {m.id: m for m in detect.propose()[0]}
    for model_id, tool in (("claude-sonnet-5-5", "claude"), ("codex", "codex"),
                           ("ollama-llama3-8b", "ollama")):
        first = by_id[model_id].command[0]
        assert first == detect.find_tool(tool, path=str(machine)) and os.path.isabs(first)


def test_setup_keeps_hand_written_models_when_the_store_is_empty(machine, tmp_path):
    tok = tmp_path / "tok"
    tok.mkdir()
    models.save(models.Registry(models=(_cli(id="local-llama", name="llama"),)), tok / "models.json")
    assert _setup(tmp_path, "--yes") == 0
    db = store.connect(tok / "config.sqlite")
    ids = {m.id for m in store.load_registry(db)}
    assert "local-llama" in ids and "claude-sonnet-5-5" in ids


def test_the_lone_mid_fallback_skips_a_model_that_cannot_be_dispatched():
    registry = _registry(_api(id="remote", tier="mid"), _cli(id="b", tier="low"))
    merged, _, notices = cli.coder_defaults({}, registry, settings_mod.Settings())
    assert "engineer_build" not in merged
    assert any("remote" in n and "api" in n for n in notices)
    # With a cli mid beside it, the cli one is the lone mid.
    registry = _registry(_api(id="remote", tier="mid"), _cli(id="a", tier="mid"))
    assert cli.coder_defaults({}, registry, settings_mod.Settings())[0]["engineer_build"] == ["a"]


def test_an_api_coder_model_is_refused_with_a_clear_error():
    with pytest.raises(cli.CliError, match="api model"):
        cli.coder_defaults({}, _registry(_api(id="remote")), settings_mod.Settings(coder_model="remote"))


# ── review round 2 ─────────────────────────────────────────────────────────────────────────────

# B · where the work goes is said, on every surface

def test_a_declared_reach_overrides_the_derived_one_and_round_trips(tmp_path):
    model = _cli(declared_reach="external")
    assert model.reach == "external" and model.leaves_this_machine
    assert _cli().reach == "local", "no declaration: derived, as before"
    assert model.as_dict()["leaves_this_machine"] is True
    # models.json
    models.save(models.Registry(models=(model,)), tmp_path / "models.json")
    assert models.load(tmp_path / "models.json").get("opus").declared_reach == "external"
    # the store
    db = store.connect(tmp_path / "c.sqlite")
    store.save_registry(db, models.Registry(models=(model,)))
    assert store.load_registry(store.connect(tmp_path / "c.sqlite")).get("opus").reach == "external"


def test_a_declared_reach_is_validated_and_can_only_raise():
    with pytest.raises(models.ModelError, match="declared_reach"):
        models.validate(_cli(declared_reach="nearby"))
    # An api model on a public host cannot be labelled nearer than it is.
    with pytest.raises(models.ModelError, match="never"):
        models.validate(_api(declared_reach="local"))
    # Raising is fine: a private endpoint declared external.
    private = _api(endpoint="http://10.0.0.5/v1", key_env="K", declared_reach="external")
    assert models.validate(private).reach == "external" and not private.as_dict()["reach_guessed"]


def test_the_proposals_for_claude_and_codex_leave_the_machine_and_ollama_does_not(machine):
    by_id = {m.id: m for m in detect.propose()[0]}
    for model_id in ("claude-sonnet-5-5", "codex"):
        assert by_id[model_id].reach == "external" and by_id[model_id].leaves_this_machine
    assert by_id["ollama-llama3-8b"].reach == "local"


def test_setup_says_before_writing_that_the_work_goes_to_the_vendor(machine, tmp_path, capsys):
    assert _setup(tmp_path) == 0                                 # off a terminal: shows, writes nothing
    out = capsys.readouterr().out
    assert "reach=external" in out and "repository's content to anthropic" in out
    assert "repository's content to openai" in out
    assert out.count("reach=local") == 2, "the two ollama models stay local"


def test_the_coder_prompt_says_the_repository_goes_to_the_vendor(
        machine, tmp_path, monkeypatch, capsys):
    # claude: add; codex, llama, qwen: skip; then the coder_model prompt, which we read and refuse.
    assert _interactive_setup(tmp_path, monkeypatch, ["1", "3", "3", "3", "2"]) == 0
    out = capsys.readouterr().out
    assert "Use claude-sonnet-5-5 as the coding model" in out
    assert "repository's content will be sent to anthropic" in out
    assert not (tmp_path / "settings.json").exists()


def test_a_local_coder_prompt_does_not_claim_egress(machine, tmp_path, monkeypatch, capsys):
    # claude, codex: skip; llama: edit to tier mid and accept; qwen: skip; coder prompt: no.
    answers = ["3", "3", "2", "", "mid", "", "3", "2"]
    assert _interactive_setup(tmp_path, monkeypatch, answers) == 0
    out = capsys.readouterr().out
    assert "Use ollama-llama3-8b as the coding model" in out and "will be sent to" not in out


def test_setup_yes_prints_where_the_coder_sends_the_work(machine, tmp_path, capsys):
    assert _setup(tmp_path, "--yes") == 0
    out = capsys.readouterr().out
    assert "note:          claude-sonnet-5-5 is reach external" in out


def test_the_server_reports_the_setup_models_as_leaving_the_machine(
        machine, tmp_path, monkeypatch, capsys):
    assert _setup(tmp_path, "--yes") == 0
    capsys.readouterr()
    _project_files(tmp_path)
    body = _get_route(tmp_path, monkeypatch, "/models")
    by_id = {m["id"]: m for m in body["models"]}
    assert by_id["claude-sonnet-5-5"]["reach"] == "external"
    assert by_id["claude-sonnet-5-5"]["leaves_this_machine"] is True
    assert {"claude-sonnet-5-5", "codex"} <= set(body["leaving"])
    assert "ollama-llama3-8b" not in body["leaving"]


def test_a_store_stamped_4_before_declared_reach_gains_the_column(tmp_path):
    path = tmp_path / "v4.sqlite"
    _v3_store(path)
    raw = sqlite3.connect(str(path))
    for column, statement in store._SCHEMA_4[:2]:
        raw.execute(statement)
    raw.execute("PRAGMA user_version = 4")
    raw.commit()
    raw.close()
    db = store.connect(path)
    assert "declared_reach" in [r[1] for r in db.execute("PRAGMA table_info(models)")]
    assert store.load_registry(db).get("old").reach == "local"


# C · the console shows the model that will build

def _project_files(tmp_path):
    """The config, settings and plan `serve` takes, without touching an existing store."""
    agent = tmp_path / "agent.py"
    agent.write_text("print('{}')\n", encoding="utf-8")
    (tmp_path / "runner.yaml").write_text(
        f"agent_command: {json.dumps([sys.executable, str(agent)])}\n", encoding="utf-8")
    plan = {"node_specs": {n.id: dict(SPEC) for n in graph.NODES if n.role},
            "decisions": {"next_module": ["module", "none"], "feedback": "done"}, "risk": "low"}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    if not (tmp_path / "settings.json").exists():
        (tmp_path / "settings.json").write_text("{}", encoding="utf-8")


def _get_route(tmp_path, monkeypatch, route):
    """Start the real `cmd_serve` on an ephemeral port, GET `route` from it, and stop it."""
    import threading
    import urllib.request
    from ai_sdlc_runner import server

    real, seen = server.serve, {}

    def serve_and_ask(runner, operator, **kw):
        httpd = real(runner, operator, **kw)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            port = httpd.server_address[1]
            req = urllib.request.Request(f"http://127.0.0.1:{port}{route}", method="GET")
            req.add_header("X-Operator-Token", operator.token)
            req.add_header("Host", f"127.0.0.1:{port}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                seen["body"] = json.loads(resp.read().decode("utf-8"))
        finally:
            httpd.shutdown()
            httpd.server_close()
        raise server.ServerError("stopped by the test")

    monkeypatch.setattr(server, "serve", serve_and_ask)
    cli.main(["--config", str(tmp_path / "runner.yaml"),
              "--settings", str(tmp_path / "settings.json"),
              "serve", "--plan", str(tmp_path / "plan.json"), "--port", "0",
              "--token-dir", str(tmp_path / "tok"),
              "--assignment-store", str(tmp_path / "config.sqlite"),
              "--ask-journal", str(tmp_path / "asks")])
    return seen["body"]


CODER_NODES = {"engineer_build", "fix_pass", "engineer_selfverify"}


def _default_nodes(body, model_id):
    return {n["node_id"] for n in body["by_model"][model_id]["nodes"] if n.get("default")}


def test_the_console_shows_the_coder_default_not_unused(tmp_path, monkeypatch, capsys):
    _project(tmp_path, [dict(id="coder", vendor="v", name="n", transport="cli", **TEMPLATE)],
             saved={"coder_model": "coder"})
    body = _get_route(tmp_path, monkeypatch, "/config/nodes")
    assert _default_nodes(body, "coder") == CODER_NODES
    assert body["node_models"] == {}, "a default is not an assignment"


def test_the_console_shows_the_lone_mid_model_as_the_coder(tmp_path, monkeypatch, capsys):
    _project(tmp_path, [dict(id="a", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE),
                        dict(id="b", vendor="v", name="n", transport="cli", tier="low", **TEMPLATE)])
    body = _get_route(tmp_path, monkeypatch, "/config/nodes")
    assert _default_nodes(body, "a") == CODER_NODES
    assert body["by_model"]["b"]["nodes"] == [], "the other model is genuinely unused"


def test_an_assignment_beats_the_default_in_the_console_too(tmp_path, monkeypatch, capsys):
    _project(tmp_path, [dict(id="a", vendor="v", name="n", transport="cli", tier="mid", **TEMPLATE),
                        dict(id="b", vendor="v", name="n", transport="cli", **TEMPLATE)],
             plan_extra={"node_models": {"engineer_build": ["b"]}})
    body = _get_route(tmp_path, monkeypatch, "/config/nodes")
    assert _default_nodes(body, "a") == set() and _default_nodes(body, "b") == set()
    assert [n["node_id"] for n in body["by_model"]["b"]["nodes"]] == ["engineer_build"]


def test_the_console_page_labels_a_default_as_not_an_assignment():
    page = (Path(cli.__file__).parent / "console" / "index.html").read_text(encoding="utf-8")
    assert "n.default" in page and "not an assignment" in page
