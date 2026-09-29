"""The review matrix with a mechanism behind it (CHG-20260929-01).

`tools/panel.py` is what turns "every model on every dimension, one session each" from a rule into
something that runs (KN-8). No real model is ever called: each seat is a small Python script that
reads its brief on stdin and prints what a `claude` or a `codex` would, with a verdict chosen by the
test. Each test names the wire it watches, and fails when that wire is cut.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import panel  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

FAKE = textwrap.dedent('''
    import json, os, re, sys, time
    state, mid, kind = sys.argv[1], sys.argv[2], sys.argv[3]
    brief = sys.stdin.read()
    phase = "cross" if "CROSS-READ" in brief else "review"
    dim = re.search(r"^Dimension: (\\S+)", brief, re.M).group(1)
    os.makedirs(os.path.join(state, "briefs"), exist_ok=True)
    with open(os.path.join(state, "invoked"), "a") as f:
        f.write(mid + " " + phase + " " + dim + " cwd=" + os.getcwd() + "\\n")
    with open(os.path.join(state, "briefs", phase + "__" + dim + "__" + mid + ".txt"), "w", encoding="utf-8") as f:
        f.write(brief)
    script = {}
    p = os.path.join(state, mid + ".json")
    if os.path.exists(p):
        script = json.load(open(p))
    how = script.get(phase, "pass")
    if isinstance(how, dict):
        how = how.get(dim, how.get("*", "pass"))

    if how == "count":                      # how many seats are alive at once
        run = os.path.join(state, "running"); os.makedirs(run, exist_ok=True)
        mark = os.path.join(run, str(os.getpid())); open(mark, "w").close()
        seen = len(os.listdir(run)); time.sleep(0.4); os.remove(mark)
        os.makedirs(os.path.join(state, "seen"), exist_ok=True)
        open(os.path.join(state, "seen", str(os.getpid())), "w").write(str(seen))
        how = "pass"
    if how == "sleep":
        time.sleep(60)
    if how == "exit1":
        print("boom", file=sys.stderr); sys.exit(1)
    if how == "mutate":
        open("scratch.txt", "w").write("a seat touched the tree\\n"); how = "pass"

    body = "ANSWER-%s-%s-%s" % (mid, dim, phase)
    if phase == "cross" and script.get("disagree"):
        body += "\\nF1: DISAGREE - the other seat is wrong about the retry"
    elif phase == "cross":
        body += "\\nF1: AGREE"
    if how == "none":
        text = body + "\\nno verdict here"
    elif how == "ok":
        text = body + "\\nVERDICT: ok"
    elif how == "flip":
        text = body + "\\nVERDICT: fail\\nOn reflection.\\nVERDICT: pass"
    else:
        text = body + "\\nVERDICT: " + how

    if kind == "claude":
        print(json.dumps({"type": "result", "result": text, "total_cost_usd": 0.25,
                          "usage": {"input_tokens": 10, "output_tokens": 5,
                                    "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7}}))
    else:
        import uuid
        thread = str(uuid.uuid4())
        usage = {"input_tokens": 14362, "cached_input_tokens": 12288, "cache_write_input_tokens": 0,
                 "output_tokens": 10, "reasoning_output_tokens": 0}
        ev = [{"type": "thread.started", "thread_id": thread},
              {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message",
                                                  "text": "draft\\nVERDICT: fail"}},
              {"type": "item.completed", "item": {"id": "item_1", "type": "agent_message", "text": text}},
              {"type": "turn.completed", "usage": usage}]
        for e in ev:
            print(json.dumps(e))
        # rate_limits are never on stdout: codex writes them to its session log only.
        home = os.environ.get("CODEX_HOME")
        rollout = script.get("rollout", "own")
        if home and rollout != "none":
            owner = thread if rollout == "own" else "11111111-2222-3333-4444-555555555555"
            day = os.path.join(home, "sessions", "2026", "09", "29")
            os.makedirs(day, exist_ok=True)
            def line(used, secondary):
                limits = {"limit_id": "codex", "primary": {"used_percent": used, "window_minutes": 300,
                                                           "resets_at": 1790000000}}
                if secondary:
                    limits["secondary"] = {"used_percent": secondary, "window_minutes": 10080,
                                           "resets_at": 1790500000}
                return json.dumps({"timestamp": "2026-09-29T04:39:45.646Z", "type": "event_msg",
                                   "payload": {"type": "token_count", "info": {"total_token_usage": usage},
                                               "rate_limits": limits}})
            with open(os.path.join(day, "rollout-2026-09-29T04-39-45-" + owner + ".jsonl"), "w") as f:
                f.write(json.dumps({"type": "session_meta", "rate_limits": None}) + "\\n")
                f.write(line(5.0, None) + "\\n")
                f.write(line(30.0, 12.5) + "\\n")
                f.write(json.dumps({"type": "event_msg", "payload": {"type": "task_complete"}}) + "\\n")
''')

DIMS = [
    {"id": "defect", "label": "缺陷", "question": "Where is it wrong? QUESTION-DEFECT", "enabled": True},
    {"id": "risk", "label": "風險", "question": "What is hard to undo? QUESTION-RISK", "enabled": True},
    {"id": "i18n", "label": "國際化", "question": "Encoding? QUESTION-I18N", "enabled": False},
]


def _git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A committed repo, a state dir the fakes report into, and a config using three fake seats.
    CODEX_HOME points at a fake one, so no test reads the developer's real ~/.codex."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "kept.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "first")
    state = tmp_path / "state"
    state.mkdir()
    script = tmp_path / "fake_seat.py"
    script.write_text(FAKE, encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("BRIEF-BODY: review the retry change.\n", encoding="utf-8")

    def seat(mid, kind):
        return {"id": mid, "kind": kind, "argv": [sys.executable, str(script), str(state), mid, kind]}

    config = tmp_path / "panel.json"

    class World:
        pass

    w = World()
    w.repo, w.state, w.brief, w.config, w.out = repo, state, brief, config, tmp_path / "out"
    w.sha = _git(repo, "rev-parse", "HEAD").strip()
    w.seat = seat

    def write_config(dims=DIMS, models=None, **extra):
        models = models or [seat("fable", "claude"), seat("opus", "claude"), seat("astra", "codex")]
        config.write_text(json.dumps({"models": models, "dimensions": dims, **extra}, ensure_ascii=False),
                          encoding="utf-8")

    def script_for(mid, **how):
        (state / f"{mid}.json").write_text(json.dumps(how), encoding="utf-8")

    def run(*extra, timeout="30"):
        return panel.main(["run", "--brief", str(brief), "--out", str(w.out), "--config", str(config),
                           "--repo", str(repo), "--cell-timeout", timeout, *extra])

    def report():
        return json.loads((w.out / "report.json").read_text(encoding="utf-8"))

    def invoked():
        f = state / "invoked"
        return f.read_text(encoding="utf-8").splitlines() if f.exists() else []

    def brief_of(phase, dim, mid):
        return (state / "briefs" / f"{phase}__{dim}__{mid}.txt").read_text(encoding="utf-8")

    w.write_config, w.script_for, w.run, w.report, w.invoked, w.brief_of = (
        write_config, script_for, run, report, invoked, brief_of)
    write_config()
    return w


# ------------------------------------------------------------------------------------- the freeze

def test_a_dirty_tree_runs_nothing_and_names_kn14(world, capsys):
    """KN-14: the check comes before any seat is opened, so a round on a moving tree never starts."""
    (world.repo / "kept.txt").write_text("two\n", encoding="utf-8")
    assert world.run() == 1
    said = capsys.readouterr().out
    assert "KN-14" in said and "kept.txt" in said
    assert world.invoked() == [], "a seat ran on a tree that was not frozen"
    assert not (world.out / "report.json").exists()


def test_a_tree_that_moves_during_the_round_is_incomplete(world, capsys):
    """The end-of-round check: a seat that writes into the repo makes the whole round unverified,
    even though every seat said pass."""
    world.script_for("opus", review="mutate")
    assert world.run("--no-cross-read") == 3
    report = world.report()
    assert report["result"] == "incomplete"
    assert any("tree moved during the round (KN-14)" in r for r in report["reasons"])
    assert "scratch.txt" in " ".join(report["reasons"])
    assert "result: pass" not in capsys.readouterr().out


def test_out_inside_the_repo_is_refused_before_anything_runs(world, capsys):
    """Raw output written into the frozen tree would fail every round at its own end check."""
    world.out = world.repo / "panel-out"
    assert world.run() == 2
    assert "inside the repo" in capsys.readouterr().out
    assert world.invoked() == []


# ---------------------------------------------------------------------------- config and matrix

def test_matrix_is_enabled_dimensions_times_models(world):
    assert world.run("--no-cross-read") == 0
    cells = world.report()["cells"]
    assert len(cells) == 2 * 3
    assert {c["dimension"] for c in cells} == {"defect", "risk"}, "the disabled dimension ran"
    assert {c["model"] for c in cells} == {"fable", "opus", "astra"}
    assert len(world.invoked()) == 6


def test_only_dimensions_overrides_enabled_and_narrows_the_rest(world):
    assert world.run("--only-dimensions", "i18n", "--no-cross-read") == 0
    assert {c["dimension"] for c in world.report()["cells"]} == {"i18n"}
    assert len(world.invoked()) == 3


def test_an_unknown_dimension_is_an_error_and_runs_nothing(world, capsys):
    assert world.run("--only-dimensions", "defect,nonesuch") == 2
    assert "nonesuch" in capsys.readouterr().out
    assert world.invoked() == []


def test_an_unknown_config_key_is_exit_2_and_named(world, capsys):
    world.write_config(surprise=1)
    assert world.run() == 2
    assert "surprise" in capsys.readouterr().out
    assert world.invoked() == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda c: c["models"][0].update(colour="red"), "colour"),
    (lambda c: c["dimensions"][0].update(enable=True), "enable"),
    (lambda c: c["models"][0].update(kind="gemini"), "kind"),
    (lambda c: c["models"].clear(), "at least one model"),
    (lambda c: c["dimensions"].append(dict(c["dimensions"][0])), "duplicate dimension"),
    (lambda c: c.update(coder={"model": "x", "surprise": 1}), "surprise"),
])
def test_config_validation(world, capsys, mutate, needle):
    config = json.loads(world.config.read_text(encoding="utf-8"))
    mutate(config)
    world.config.write_text(json.dumps(config), encoding="utf-8")
    assert world.run() == 2
    assert needle in capsys.readouterr().out
    assert world.invoked() == []


def test_the_shipped_config_is_valid_and_has_the_specified_dimensions(capsys):
    """The wire from the tool to its data: the file a user edits is the file the tool loads."""
    config = panel.load_config(ROOT / "config" / "panel.json")
    dims = config["dimensions"]
    assert len(dims) == 15
    assert [d["enabled"] for d in dims] == [True] * 12 + [False] * 3
    assert [m["id"] for m in config["models"]] == ["fable", "opus", "gpt-6-astra"]
    assert panel.main(["list", "--config", str(ROOT / "config" / "panel.json")]) == 0
    assert "36 review + 36 cross-read = 72 sessions" in capsys.readouterr().out


def test_list_counts_the_sessions_a_round_opens(world, capsys):
    assert panel.main(["list", "--config", str(world.config)]) == 0
    said = capsys.readouterr().out
    assert "6 review + 6 cross-read = 12 sessions" in said
    assert "i18n" in said and "disabled" in said
    assert world.invoked() == []


# ------------------------------------------------------------------------------------- the brief

def test_the_brief_reaches_the_seat_on_stdin_with_question_and_sha(world):
    assert world.run("--no-cross-read") == 0
    brief = world.brief_of("review", "defect", "fable")
    assert "QUESTION-DEFECT" in brief and "QUESTION-RISK" not in brief
    assert "缺陷" in brief
    assert world.sha in brief
    assert "BRIEF-BODY: review the retry change." in brief
    assert "Seat: fable" in brief
    assert "will not see the other seats" in brief and "read only" in brief
    assert "VERDICT: pass" in brief and "VERDICT: fail" in brief
    assert all(f"cwd={world.repo.resolve()}" in line or f"cwd={world.repo}" in line
               for line in world.invoked()), "seats must run from the repo root"


def test_repo_is_substituted_into_argv(world):
    """The `{repo}` in codex's `-C {repo}` is what points it at the tree; unsubstituted it reads
    nothing."""
    script = world.state.parent / "echo_argv.py"
    script.write_text("import sys, json\nsys.stdin.read()\n"
                      "print(json.dumps({'result': 'got ' + sys.argv[1] + '\\nVERDICT: pass'}))\n",
                      encoding="utf-8")
    world.write_config(models=[{"id": "x", "kind": "claude",
                                "argv": [sys.executable, str(script), "{repo}"]}])
    assert world.run("--no-cross-read") == 0
    assert f"got {world.repo}" in world.report()["cells"][0]["answer"]


# ------------------------------------------------------------------------------------- verdicts

def test_all_pass_is_exit_0_and_the_report_says_pass(world):
    assert world.run() == 0
    report = world.report()
    assert report["result"] == "pass"
    assert report["sha"] == world.sha
    assert {c["phase"] for c in report["cells"]} == {"review", "cross"}
    assert len(report["cells"]) == 12
    md = (world.out / "report.md").read_text(encoding="utf-8")
    assert "# Panel round — pass" in md and "| defect (缺陷) |" in md
    assert len(list((world.out / "cells").glob("*.stdout.txt"))) == 12


def test_one_fail_is_exit_1(world):
    world.script_for("opus", review={"risk": "fail", "*": "pass"})
    assert world.run() == 1
    report = world.report()
    assert report["result"] == "fail"
    failed = [c for c in report["cells"] if c["verdict"] == "fail"]
    assert [(c["model"], c["dimension"]) for c in failed] == [("opus", "risk")]


@pytest.mark.parametrize("how,why", [
    ("none", "VERDICT"),
    ("ok", "VERDICT"),
    ("exit1", "exit code 1"),
])
def test_anything_but_a_verdict_is_unreached_and_never_pass(world, capsys, how, why):
    """KN-15 and DIR-2: unknown is its own state, it stops the round, and it is not the safe one."""
    world.script_for("astra", review={"defect": how, "*": "pass"})
    assert world.run() == 3
    report = world.report()
    assert report["result"] == "incomplete"
    unreached = [c for c in report["cells"] if c["verdict"] == "unreached"]
    assert [(c["model"], c["dimension"]) for c in unreached] == [("astra", "defect")]
    assert why in unreached[0]["reason"]
    assert all(c["phase"] == "review" for c in report["cells"]), "cross-read ran on an incomplete round"
    assert len(world.invoked()) == 6
    assert "UNREACHED" in capsys.readouterr().out
    assert "pass" not in (world.out / "report.md").read_text(encoding="utf-8").splitlines()[0]


def test_a_nonzero_exit_is_unreached_even_if_it_printed_a_pass(world):
    """A crashed seat's last words are not its verdict."""
    script = world.state.parent / "crash.py"
    script.write_text("import sys, json\nprint(json.dumps({'result': 'VERDICT: pass'}))\nsys.exit(2)\n",
                      encoding="utf-8")
    world.write_config(models=[{"id": "x", "kind": "claude", "argv": [sys.executable, str(script)]}])
    assert world.run() == 3
    assert {c["verdict"] for c in world.report()["cells"]} == {"unreached"}


def test_a_timeout_is_unreached(world):
    world.script_for("fable", review={"risk": "sleep", "*": "pass"})
    assert world.run(timeout="1") == 3
    cell = next(c for c in world.report()["cells"] if c["verdict"] == "unreached")
    assert (cell["model"], cell["dimension"]) == ("fable", "risk")
    assert "timed out" in cell["reason"]


def test_a_missing_binary_is_unreached_not_a_crash(world):
    world.write_config(models=[{"id": "ghost", "kind": "claude", "argv": ["no-such-binary-xyzzy"]}])
    assert world.run() == 3
    assert "could not start" in world.report()["cells"][0]["reason"]


def test_the_last_verdict_line_wins(world):
    world.script_for("fable", review="flip")
    assert world.run("--no-cross-read") == 0
    cell = next(c for c in world.report()["cells"] if c["model"] == "fable")
    assert cell["verdict"] == "pass"
    assert panel.verdict_of("VERDICT: pass\nVERDICT: fail\n") == "fail"
    assert panel.verdict_of("a VERDICT: pass in prose\n") is None


# --------------------------------------------------------------------------- usage and answers

def test_codex_verdict_is_read_from_the_last_agent_message_and_quota_is_computed(world):
    world.write_config(models=[world.seat("astra", "codex")])
    world.script_for("astra", review="pass")
    assert world.run("--no-cross-read") == 0
    report = world.report()
    cell = report["cells"][0]
    assert cell["verdict"] == "pass", "the earlier draft message said fail; the last one governs"
    assert cell["usage"]["rate_limits"]["primary"]["used_percent"] == 30.0, "the last rate_limits wins"
    assert cell["usage"]["token_usage"]["output_tokens"] == 10
    codex = report["usage_summary"]["codex"]
    assert codex["primary"]["remaining_percent"] == 70.0
    assert codex["primary"]["window_minutes"] == 300
    assert codex["secondary"]["remaining_percent"] == 87.5
    assert codex["primary"]["resets"].endswith("UTC")
    md = (world.out / "report.md").read_text(encoding="utf-8")
    assert "70.0% remaining" in md and "87.5% remaining" in md


REAL_CODEX_STDOUT = "\n".join([
    '{"type":"thread.started","thread_id":"01a0eb76-0a72-75d2-ac59-ed17e5c9469a"}',
    '{"type":"turn.started"}',
    '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello\\nVERDICT: pass"}}',
    '{"type":"turn.completed","usage":{"input_tokens":14362,"cached_input_tokens":12288,'
    '"cache_write_input_tokens":0,"output_tokens":10,"reasoning_output_tokens":0}}',
]) + "\n"
THREAD = "01a0eb76-0a72-75d2-ac59-ed17e5c9469a"


def _rollout(home, thread, used, name_day="2026/09/29"):
    day = home / "sessions" / name_day
    day.mkdir(parents=True, exist_ok=True)
    line = {"type": "event_msg", "payload": {"type": "token_count", "rate_limits": {
        "primary": {"used_percent": used, "window_minutes": 300, "resets_at": 1790674782}}}}
    (day / f"rollout-2026-09-29T04-39-45-{thread}.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")


def test_the_real_codex_stdout_gives_the_answer_and_tokens_from_turn_completed(tmp_path):
    assert panel.extract_answer("codex", REAL_CODEX_STDOUT) == "hello\nVERDICT: pass"
    usage = panel.extract_usage("codex", REAL_CODEX_STDOUT, tmp_path)
    assert usage["token_usage"]["input_tokens"] == 14362 and usage["token_usage"]["output_tokens"] == 10
    assert usage["rate_limits"] is None, "nothing on stdout carries rate limits"


def test_rate_limits_are_read_from_the_rollout_matched_by_thread_id(tmp_path):
    _rollout(tmp_path, THREAD, 6.0)
    usage = panel.extract_usage("codex", REAL_CODEX_STDOUT, tmp_path)
    assert usage["rate_limits"]["primary"]["used_percent"] == 6.0


def test_the_last_rate_limits_in_the_rollout_wins(tmp_path):
    _rollout(tmp_path, THREAD, 6.0)
    path = next(tmp_path.rglob("*.jsonl"))
    later = {"type": "event_msg", "payload": {"rate_limits": {"primary": {"used_percent": 9.0}}}}
    path.write_text(path.read_text(encoding="utf-8") + json.dumps(later) + "\n" + '{"rate_limits": null}\n',
                    encoding="utf-8")
    assert panel.extract_usage("codex", REAL_CODEX_STDOUT, tmp_path)["rate_limits"]["primary"]["used_percent"] == 9.0


def test_codex_home_comes_from_the_environment_when_not_passed(tmp_path, monkeypatch):
    _rollout(tmp_path, THREAD, 6.0)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert panel.extract_usage("codex", REAL_CODEX_STDOUT)["rate_limits"]["primary"]["used_percent"] == 6.0


def test_a_rollout_for_a_different_thread_is_not_used(tmp_path):
    _rollout(tmp_path, "99999999-0000-0000-0000-000000000000", 77.0)
    usage = panel.extract_usage("codex", REAL_CODEX_STDOUT, tmp_path)
    assert usage["rate_limits"] is None, "another thread's quota was attributed to this cell"
    assert usage["token_usage"]["output_tokens"] == 10


def test_no_rollout_is_none_and_never_an_error(tmp_path):
    assert panel.extract_usage("codex", REAL_CODEX_STDOUT, tmp_path / "does-not-exist")["rate_limits"] is None


def test_a_cell_with_no_rollout_still_counts_in_the_summary(world):
    world.write_config(dims=DIMS[:1], models=[world.seat("astra", "codex")])
    world.script_for("astra", rollout="none")
    assert world.run("--no-cross-read") == 0
    report = world.report()
    assert report["cells"][0]["usage"]["rate_limits"] is None
    codex = report["usage_summary"]["codex"]
    assert codex["cells"] == 1 and codex["primary"] is None
    assert codex["input_tokens"] == 14362 and codex["output_tokens"] == 10
    assert "codex primary: not reported" in (world.out / "report.md").read_text(encoding="utf-8")


def test_a_foreign_rollout_leaves_the_round_without_quota(world):
    world.write_config(dims=DIMS[:1], models=[world.seat("astra", "codex")])
    world.script_for("astra", rollout="foreign")
    assert world.run("--no-cross-read") == 0
    report = world.report()
    assert report["cells"][0]["usage"]["rate_limits"] is None
    assert report["usage_summary"]["codex"]["primary"] is None and report["usage_summary"]["codex"]["cells"] == 1


def test_codex_falls_back_to_raw_stdout_when_no_agent_message_is_found():
    assert panel.extract_answer("codex", "plain text\nVERDICT: pass\n") == "plain text\nVERDICT: pass\n"


def test_claude_verdict_comes_from_result_and_cost_is_captured(world):
    world.write_config(models=[world.seat("fable", "claude"), world.seat("opus", "claude")])
    assert world.run("--no-cross-read") == 0
    report = world.report()
    cell = report["cells"][0]
    assert cell["answer"].startswith("ANSWER-fable-defect-review")
    assert cell["usage"] == {"total_cost_usd": 0.25, "input_tokens": 10, "output_tokens": 5,
                             "cache_read_input_tokens": 100, "cache_creation_input_tokens": 7}
    claude = report["usage_summary"]["claude"]
    assert claude["cost_usd"] == 1.0 and claude["input_tokens"] == 40 and claude["output_tokens"] == 20
    assert claude["cache_read_input_tokens"] == 400 and claude["cache_creation_input_tokens"] == 28


def test_claude_stdout_that_is_not_the_json_result_is_unreached(world):
    """Not a fallback to raw text: a verdict scraped out of malformed output is not the seat's."""
    script = world.state.parent / "raw.py"
    script.write_text("print('VERDICT: pass')\n", encoding="utf-8")
    world.write_config(models=[{"id": "x", "kind": "claude", "argv": [sys.executable, str(script)]}])
    assert world.run() == 3


def test_jobs_bounds_the_concurrent_sessions(world):
    world.script_for("fable", review="count")
    world.script_for("opus", review="count")
    world.script_for("astra", review="count")
    assert world.run("--jobs", "2", "--no-cross-read") == 0
    seen = [int(p.read_text()) for p in (world.state / "seen").iterdir()]
    assert len(seen) == 6
    assert max(seen) == 2, f"expected exactly 2 at once with --jobs 2, saw {max(seen)}"


# ------------------------------------------------------------------------------------ cross-read

def test_cross_read_gives_each_model_only_the_others_answers_for_that_dimension(world):
    assert world.run() == 0
    for dim in ("defect", "risk"):
        other_dim = "risk" if dim == "defect" else "defect"
        for me in ("fable", "opus", "astra"):
            brief = world.brief_of("cross", dim, me)
            for other in {"fable", "opus", "astra"} - {me}:
                assert f"ANSWER-{other}-{dim}-review" in brief, (me, dim, other)
            assert f"ANSWER-{me}-{dim}-review" not in brief, "a seat was shown its own answer"
            assert f"-{other_dim}-review" not in brief, "another dimension's answers leaked in"
            assert "CROSS-READ" in brief and "BRIEF-BODY" in brief and world.sha in brief


def test_a_disagree_line_is_collected_and_escalated_not_averaged(world, capsys):
    world.script_for("opus", disagree=True)
    assert world.run() == 0, "verdicts all say pass; the disagreement is reported, not voted away"
    report = world.report()
    found = report["disagreements"]
    assert {(d["model"]) for d in found} == {"opus"} and {d["dimension"] for d in found} == {"defect", "risk"}
    assert "DISAGREE" in found[0]["line"]
    assert "DISAGREE defect / opus" in capsys.readouterr().out
    assert "the other seat is wrong about the retry" in (world.out / "report.md").read_text(encoding="utf-8")


def test_an_unreached_cross_read_seat_makes_the_round_incomplete(world):
    world.script_for("astra", cross={"risk": "none", "*": "pass"})
    assert world.run() == 3
    report = world.report()
    assert report["result"] == "incomplete"
    bad = [c for c in report["cells"] if c["verdict"] == "unreached"]
    assert [(c["phase"], c["model"], c["dimension"]) for c in bad] == [("cross", "astra", "risk")]


def test_a_failing_cross_read_fails_the_round(world):
    world.script_for("fable", cross={"defect": "fail", "*": "pass"})
    assert world.run() == 1
    assert world.report()["result"] == "fail"
