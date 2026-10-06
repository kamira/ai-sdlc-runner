"""CHG-20261006-01 — what each ask used, and the quota a backend says remains.

KN-8: the wire tests here fail when the wire is cut. Cutting the `usage.append` in `engine._ask`
turns `test_a_run_over_a_claude_shaped_backend_reports_its_cost` red; cutting `self.usage = …` out of
`cli._Process.ask` does the same; cutting the `/usage` branch in `server.do_GET` turns the server
tests red. The shape tests alone would stay green through all three, which is why they are not the
only ones.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ai_sdlc_runner import cli, engine, graph, server, usage

NOW = 1791290000.0          # 2026-10-06T12:33:20Z: before the fixture windows reset, after nothing

CLAUDE = json.dumps({
    "type": "result", "result": "done", "total_cost_usd": 0.123,
    "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 300,
              "cache_creation_input_tokens": 40}})
THREAD = "0199a0b1-aaaa-bbbb-cccc-000000000001"
OTHER = "0199a0b1-aaaa-bbbb-cccc-000000000002"


def _codex_stdout(thread=THREAD):
    return "\n".join(json.dumps(e) for e in (
        {"type": "thread.started", "thread_id": thread},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": "hi"}},
        {"type": "turn.completed",
         "usage": {"input_tokens": 1200, "cached_input_tokens": 800, "output_tokens": 90}})) + "\n"


def _limits(primary=42.0, secondary=95.0, resets=1791300000, resets2=1791800000):
    return {"primary": {"used_percent": primary, "window_minutes": 300, "resets_at": resets},
            "secondary": {"used_percent": secondary, "window_minutes": 10080, "resets_at": resets2}}


def _rollout(home, thread, *events, day="2026/10/06"):
    folder = home / "sessions" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-06T13-50-00-{thread}.jsonl"
    path.write_text("\n".join(e if isinstance(e, str) else json.dumps(e) for e in events) + "\n",
                    encoding="utf-8")
    return path


def _count(stamp, limits):
    return {"timestamp": stamp, "type": "event_msg",
            "payload": {"type": "token_count", "info": {}, "rate_limits": limits}}


# ── claude ────────────────────────────────────────────────────────────────────────────────────

def test_claude_json_gives_cost_and_tokens_and_no_remaining():
    got = usage.from_reply(CLAUDE)
    assert got["kind"] == "claude"
    assert got["cost_usd"] == 0.123
    assert got["tokens"] == {"input": 10, "output": 20, "cache_read": 300, "cache_write": 40}
    assert got["remaining"] == [], "claude states no remaining quota and none is invented"
    assert "API-equivalent" in got["note"]


def test_claude_json_with_only_a_cost_has_unknown_tokens_not_zero():
    got = usage.from_reply(json.dumps({"type": "result", "total_cost_usd": 0.5}))
    assert got["kind"] == "claude" and got["cost_usd"] == 0.5
    assert got["tokens"] is None


# ── codex ─────────────────────────────────────────────────────────────────────────────────────

def test_codex_tokens_come_from_stdout_and_remaining_from_its_own_thread_log(tmp_path):
    _rollout(tmp_path, THREAD,
             _count("2026-10-06T13:49:00.000Z", _limits(10.0, 20.0)),
             _count("2026-10-06T13:50:01.123Z", _limits(42.0, 95.0)))
    # Another thread's log, with different numbers: reading it would be reading another session.
    _rollout(tmp_path, OTHER, _count("2026-10-06T13:55:00.000Z", _limits(1.0, 2.0)))
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert got["kind"] == "codex" and got["cost_usd"] is None
    assert got["tokens"] == {"input": 1200, "output": 90, "cache_read": 800, "cache_write": 0}
    primary, secondary = got["remaining"]
    assert (primary["window"], primary["window_minutes"], primary["used_percent"]) == ("primary", 300, 42.0)
    assert primary["remaining_percent"] == 58.0
    assert primary["as_of"] == "2026-10-06T13:50:01.123000+00:00"
    assert primary["resets_at"] == "2026-10-06T15:20:00+00:00"
    assert (secondary["window"], secondary["window_minutes"], secondary["remaining_percent"]) == ("secondary", 10080, 5.0)
    assert primary["stale"] is False and secondary["stale"] is False


def test_the_last_rate_limits_line_wins_and_a_later_null_does_not_erase_it(tmp_path):
    _rollout(tmp_path, THREAD,
             _count("2026-10-06T13:49:00.000Z", _limits(10.0, 20.0)),
             _count("2026-10-06T13:50:00.000Z", None))
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert [w["used_percent"] for w in got["remaining"]] == [10.0, 20.0]


def test_a_missing_log_says_why_and_reports_no_remaining(tmp_path):
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert got["kind"] == "codex" and got["remaining"] == []
    assert "no session log" in got["note"]
    assert got["tokens"]["input"] == 1200, "the stdout half still stands without the log"


def test_null_rate_limits_say_so(tmp_path):
    _rollout(tmp_path, THREAD, _count("2026-10-06T13:50:00.000Z", None))
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert got["remaining"] == [] and "no rate limits" in got["note"]


def test_malformed_log_lines_are_skipped_not_fatal(tmp_path):
    _rollout(tmp_path, THREAD, "{not json rate_limits", "[1, 2, 3]", '{"payload": "rate_limits"}',
             _count("2026-10-06T13:50:00.000Z", _limits(30.0, 40.0)), "{\"truncated\": rate_limits")
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert [w["used_percent"] for w in got["remaining"]] == [30.0, 40.0]


def test_malformed_stdout_lines_are_skipped_not_fatal():
    out = "garbage\n{broken\n" + _codex_stdout()
    got = usage.from_reply(out, Path("/nonexistent-codex-home"), now=NOW)
    assert got["kind"] == "codex" and got["tokens"]["output"] == 90


def test_a_window_past_its_reset_is_stale_and_one_without_a_reset_is_not(tmp_path):
    limits = {"primary": {"used_percent": 90.0, "window_minutes": 300, "resets_at": int(NOW) - 60},
              "secondary": {"used_percent": 10.0, "window_minutes": 10080, "resets_at": None}}
    _rollout(tmp_path, THREAD, _count("2026-10-06T13:50:00.000Z", limits))
    primary, secondary = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)["remaining"]
    assert primary["stale"] is True
    assert secondary["stale"] is False and secondary["resets_at"] is None


def test_remaining_percent_never_goes_below_zero(tmp_path):
    _rollout(tmp_path, THREAD, _count("2026-10-06T13:50:00.000Z", _limits(130.0, 100.0)))
    got = usage.from_reply(_codex_stdout(), tmp_path, now=NOW)
    assert [w["remaining_percent"] for w in got["remaining"]] == [0.0, 0.0]


@pytest.mark.parametrize("thread", ["*", "../*", "a/b", "0199*", "..", "a b"])
def test_a_thread_id_that_is_not_a_plain_id_is_never_globbed(tmp_path, thread):
    """A `*` would match every session on the machine, and `/` would leave the sessions folder."""
    _rollout(tmp_path, THREAD, _count("2026-10-06T13:50:00.000Z", _limits(1.0, 2.0)))
    got = usage.from_reply(_codex_stdout(thread), tmp_path, now=NOW)
    assert got["remaining"] == [], thread
    assert got["kind"] == "codex"


def test_a_log_for_a_longer_id_ending_the_same_way_is_not_this_thread(tmp_path):
    _rollout(tmp_path, "x" + THREAD, _count("2026-10-06T13:50:00.000Z", _limits(1.0, 2.0)))
    assert usage.from_reply(_codex_stdout(), tmp_path, now=NOW)["remaining"] == []


# ── anything else ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stdout", ["just some text", "[1, 2]", "", "   \n", "{}", '{"verdict": "pass"}',
                                    "{broken", None, 7])
def test_anything_else_is_unreported_and_never_zero(stdout):
    got = usage.from_reply(stdout)
    assert got == {"kind": "unreported", "cost_usd": None, "tokens": None, "remaining": [],
                   "note": "the backend did not report usage"}


# ── summarize ─────────────────────────────────────────────────────────────────────────────────

def _rec(model, **over):
    base = {"ask_id": "a", "node_id": "n", "seat": None, "model": model, "kind": "claude",
            "cost_usd": None, "tokens": None, "remaining": [], "note": ""}
    return {**base, **over}


def _win(name, used, as_of, stale=False):
    return {"window": name, "window_minutes": 300, "used_percent": used,
            "remaining_percent": 100 - used, "resets_at": None, "as_of": as_of, "stale": stale}


def test_summarize_sums_per_model_and_keeps_unknown_as_none():
    tok = {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4}
    got = usage.summarize([
        _rec("a", cost_usd=0.25, tokens=tok), _rec("a", cost_usd=0.5, tokens=tok),
        _rec("a", kind="unreported"),
        _rec("b", kind="unreported"), _rec("b", kind="unreported"),
        _rec("c", kind="codex", tokens=tok)])
    a, b, c = (got["models"][m] for m in "abc")
    assert (a["asks"], a["cost_usd"], a["asks_unreported"]) == (3, 0.75, 1)
    assert a["tokens"] == {"input": 2, "output": 4, "cache_read": 6, "cache_write": 8}
    assert (b["asks"], b["cost_usd"], b["tokens"], b["asks_unreported"]) == (2, None, None, 2)
    assert c["cost_usd"] is None and c["tokens"]["output"] == 2
    assert usage.summarize([]) == {"models": {}, "remaining": []}


def test_summarize_keeps_the_latest_reading_of_each_window_with_its_model():
    got = usage.summarize([
        _rec("a", kind="codex", remaining=[_win("primary", 10, "2026-10-06T10:00:00+00:00"),
                                           _win("secondary", 50, "2026-10-06T12:00:00+00:00")]),
        _rec("b", kind="codex", remaining=[_win("primary", 70, "2026-10-06T11:00:00+00:00")]),
        _rec("a", kind="codex", remaining=[_win("primary", 5, "2026-10-06T09:00:00+00:00")])])
    primary, secondary = got["remaining"]
    assert (primary["window"], primary["model"], primary["used_percent"]) == ("primary", "b", 70)
    assert (secondary["model"], secondary["used_percent"]) == ("a", 50)


# ── the wire: a backend's stdout → the session → the report ───────────────────────────────────

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}

#: Answers as the routing needs and prints what `claude -p --output-format json` would: the agent's
#: own keys and the CLI's cost beside them, in one JSON object.
CLAUDE_BACKEND = """
import json, sys
order = json.load(sys.stdin)
answers = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}
if order.get("seat"):
    out = ({"problems": [], "missing": [], "unsafe": []} if order["node_id"] == "intake_review"
           else {"verdict": "pass"})
else:
    out = {"verdict": answers[order["node_id"]]} if order["node_id"] in answers else {"ok": True}
out.update({"type": "result", "total_cost_usd": 0.125,
            "usage": {"input_tokens": 10, "output_tokens": 20,
                      "cache_read_input_tokens": 300, "cache_creation_input_tokens": 40}})
print(json.dumps(out))
"""
#: The same backend with the CLI's usage object removed: it prints the agent's own keys and nothing
#: a usage reader recognises, which is every stub and every `ollama run` wrapper.
SILENT_BACKEND = CLAUDE_BACKEND.replace("out.update(", "ignored = (")


def _walk(tmp_path, script_text):
    script = tmp_path / "backend.py"
    script.write_text(script_text, encoding="utf-8")

    def factory(seat=None, model=None):
        return cli._Process([sys.executable, str(script)], timeout=60, cwd=str(tmp_path))

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none"], "feedback": "done"},
        risk="low", undeclared="allow", confirmed=("merge",))
    return engine.walk(cfg, factory, enabled=True)


def test_a_run_over_a_claude_shaped_backend_reports_its_cost(tmp_path):
    """*cut*: drop the `usage.append` in `engine._ask`, or `self.usage = …` in `_Process.ask`."""
    report = _walk(tmp_path, CLAUDE_BACKEND)
    assert report.state == engine.FINISHED, (report.state, report.halt_reason)
    assert report.usage, "an ask ran, and the report says nothing about what it used"
    assert len(report.usage) == len(report.asks)
    assert {u["cost_usd"] for u in report.usage} == {0.125}
    first = report.usage[0]
    assert {"ask_id", "node_id", "seat", "model", "kind", "tokens", "remaining", "note"} <= set(first)
    assert first["kind"] == "claude" and first["tokens"]["cache_write"] == 40
    shown = report.as_dict()
    assert shown["usage"] == report.usage
    summary = shown["usage_summary"]["models"]["(default backend)"]
    assert summary["asks"] == len(report.asks)
    assert summary["cost_usd"] == round(0.125 * len(report.asks), 6)


def test_usage_does_not_change_the_answer_or_the_route(tmp_path):
    """The reporting field is beside the answer: the same backend with and without a cost walks the
    same nodes to the same end."""
    with_usage = _walk(tmp_path, CLAUDE_BACKEND)
    without = _walk(tmp_path, SILENT_BACKEND)
    assert with_usage.visited == without.visited and with_usage.state == without.state


def test_a_backend_that_prints_nothing_recognisable_is_recorded_as_unreported(tmp_path):
    report = _walk(tmp_path, SILENT_BACKEND)
    assert report.usage and {u["kind"] for u in report.usage} == {"unreported"}
    assert {u["cost_usd"] for u in report.usage} == {None}
    row = report.as_dict()["usage_summary"]["models"]["(default backend)"]
    assert row["asks_unreported"] == row["asks"] and row["cost_usd"] is None


def test_a_session_without_usage_adds_nothing(tmp_path):
    class Quiet(engine.Session):
        def ask(self, order):
            if order.get("seat"):
                return ({"problems": [], "missing": [], "unsafe": []}
                        if order["node_id"] == "intake_review" else {"verdict": "pass"})
            branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                      "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
            return {"verdict": branch} if branch else {"ok": True}

        def close(self):
            pass

    cfg = engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none"], "feedback": "done"},
        risk="low", undeclared="allow", confirmed=("merge",))
    report = engine.walk(cfg, lambda: Quiet(), enabled=True)
    assert report.state == engine.FINISHED and report.asks
    assert report.usage == []


def test_the_process_reads_codex_home_from_the_environment(tmp_path, monkeypatch):
    """*cut*: pass no `CODEX_HOME` in `_Process.ask` and the fake home is never read."""
    home = tmp_path / "home"
    _rollout(home, THREAD, _count("2026-10-06T13:50:00.000Z", _limits(42.0, 95.0)))
    script = tmp_path / "codex_like.py"
    script.write_text("import sys\nsys.stdin.read()\nsys.stdout.write(%r)\n" % _codex_stdout(),
                      encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    session = cli._Process([sys.executable, str(script)], timeout=60, cwd=str(tmp_path))
    session.ask({"node_id": "qa_accept"})
    assert session.usage["kind"] == "codex"
    assert [w["used_percent"] for w in session.usage["remaining"]] == [42.0, 95.0]


# ── GET /usage ────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def served(tmp_path):
    operator = server.Operator.mint(tmp_path)
    runner = server.Runner(walk=lambda cfg: engine.RunReport(), make_config=lambda *a, **k: None)
    httpd = server.serve(runner, operator, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]

    def get(path, token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
        req.add_header("X-Operator-Token", operator.token if token is None else token)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    yield get, runner
    httpd.shutdown()
    httpd.server_close()


def test_usage_before_any_run_is_null_and_empty(served):
    get, _ = served
    assert get("/usage") == (200, {"run": None, "asks": []})


def test_usage_serves_the_reports_asks_and_their_summary(served):
    """*cut*: remove the `/usage` branch from `server.do_GET` and this is a 404."""
    get, runner = served
    tok = {"input": 1, "output": 2, "cache_read": 3, "cache_write": 4}
    asks = [_rec("opus", ask_id="000-x", node_id="x", cost_usd=0.5, tokens=tok),
            _rec("opus", ask_id="001-x", node_id="x", cost_usd=0.25, tokens=tok),
            _rec("local", kind="unreported")]
    runner.state.report = engine.RunReport()
    runner.state.usage.extend(asks)
    status, body = get("/usage")
    assert status == 200 and body["asks"] == asks
    assert body["run"]["models"]["opus"]["cost_usd"] == 0.75
    assert body["run"]["models"]["local"]["asks_unreported"] == 1
    assert body["run"] == usage.summarize(asks)


def test_usage_needs_the_operator_token(served):
    get, _ = served
    assert get("/usage", token="not-the-token")[0] == 401
    assert get("/usage", token="")[0] == 401


# ── the backend's own envelopes (the json output flags `runner setup` proposes) ───────────────

#: Prints what `claude -p --output-format json` prints: the agent's answer is the *string* `result`.
CLAUDE_ENVELOPE_BACKEND = CLAUDE_BACKEND.replace(
    "print(json.dumps(out))",
    "agent = {k: v for k, v in out.items() if k not in ('type', 'total_cost_usd', 'usage')}\n"
    "print(json.dumps({'type': 'result', 'is_error': False, 'result': json.dumps(agent),\n"
    "                  'total_cost_usd': 0.125,\n"
    "                  'usage': {'input_tokens': 10, 'output_tokens': 20}}))")


def test_a_claude_envelope_is_unwrapped_to_route_and_still_reports_cost(tmp_path):
    """*cut*: drop the `usage_mod.unwrap` branch in `_Process.ask` and the run no longer routes."""
    report = _walk(tmp_path, CLAUDE_ENVELOPE_BACKEND)
    assert report.state == engine.FINISHED, (report.state, report.halt_reason)
    assert {u["cost_usd"] for u in report.usage} == {0.125}
    assert report.as_dict()["usage_summary"]["models"]["(default backend)"]["cost_usd"] == round(
        0.125 * len(report.asks), 6)


def test_a_codex_envelope_is_unwrapped_to_route_with_tokens_and_remaining(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _rollout(home, THREAD, _count("2026-10-06T13:50:00.000Z", _limits(42.0, 95.0)))
    monkeypatch.setenv("CODEX_HOME", str(home))
    backend = (
        "import json, sys\n"
        "order = json.loads(sys.stdin.read())\n"
        "if order.get('seat'):\n"
        "    out = ({'problems': [], 'missing': [], 'unsafe': []}\n"
        "           if order['node_id'] == 'intake_review' else {'verdict': 'pass'})\n"
        "else:\n"
        "    branch = {'pm_confirm': 'yes', 'pm_signoff': 'yes', 'lead_task_review': 'pass',\n"
        "              're_review': 'pass', 'qa_accept': 'pass'}.get(order['node_id'])\n"
        "    out = {'verdict': branch} if branch else {'ok': True}\n"
        "for e in ({'type': 'thread.started', 'thread_id': %r},\n"
        "          {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'draft'}},\n"
        "          {'type': 'item.completed', 'item': {'type': 'agent_message',\n"
        "                                              'text': json.dumps(out)}},\n"
        "          {'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 6}}):\n"
        "    print(json.dumps(e))\n" % THREAD)
    report = _walk(tmp_path, backend)
    assert report.state == engine.FINISHED, (report.state, report.halt_reason)
    first = report.usage[0]
    assert first["kind"] == "codex" and first["tokens"]["input"] == 5
    assert [w["used_percent"] for w in first["remaining"]] == [42.0, 95.0]


def test_unwrap_recognises_only_the_two_envelopes():
    assert usage.unwrap(json.dumps({"type": "result", "result": '{"a": 1}'})) == ('{"a": 1}', False)
    assert usage.unwrap(json.dumps({"type": "result", "result": "x", "is_error": True})) == ("x", True)
    # not a string result, or no `type: result`: the agent's own answer
    assert usage.unwrap(json.dumps({"type": "result", "result": {"verdict": "fail"}})) is None
    assert usage.unwrap(json.dumps({"verdict": "pass", "result": "x"})) is None
    # codex events with no thread.started are not an envelope
    assert usage.unwrap(_codex_stdout().replace("thread.started", "other")) is None
    assert usage.unwrap(_codex_stdout()) == ("hi", False)
    assert usage.unwrap("") is None and usage.unwrap(None) is None


def _ask(tmp_path, stdout):
    script = tmp_path / "echo.py"
    script.write_text("import sys\nsys.stdin.read()\nsys.stdout.write(%r)\n" % stdout,
                      encoding="utf-8")
    return cli._Process([sys.executable, str(script)], timeout=60, cwd=str(tmp_path)).ask(
        {"node_id": "qa_accept"})


def test_an_agents_own_json_that_is_not_an_envelope_is_unaffected(tmp_path):
    assert _ask(tmp_path, json.dumps({"verdict": "fail"}))["verdict"] == "fail"
    answer = _ask(tmp_path, json.dumps({"type": "result", "result": {"verdict": "fail"}}))
    assert answer["result"] == {"verdict": "fail"} and "verdict" not in answer


def test_a_claude_envelope_answer_is_the_json_inside_and_an_error_is_not_an_answer(tmp_path):
    inner = json.dumps({"verdict": "pass"})
    assert _ask(tmp_path, json.dumps({"type": "result", "result": inner}))["verdict"] == "pass"
    answer = _ask(tmp_path, json.dumps({"type": "result", "result": inner, "is_error": True}))
    assert "verdict" not in answer and answer["stdout"] == inner
    prose = _ask(tmp_path, json.dumps({"type": "result", "result": "just words"}))
    assert prose["stdout"] == "just words" and "verdict" not in prose


# ── a run that stops on an error keeps the usage of the asks it made ─────────────────────────

def test_usage_lists_asks_already_made_when_the_run_stops_on_an_error(tmp_path):
    """*cut*: drop `usage=self.state.usage` from the config `_walk_once` builds, or the
    `RunConfig.usage` hand-off in `engine.walk`, and this lists nothing: no report came back."""
    refusing = CLAUDE_BACKEND.replace(
        '{"problems": [], "missing": [], "unsafe": []}', '{"verdict": "pass"}')
    assert refusing != CLAUDE_BACKEND
    script = tmp_path / "refuses.py"
    script.write_text(refusing, encoding="utf-8")
    operator = server.Operator.mint(tmp_path)

    def factory(seat=None, model=None):
        return cli._Process([sys.executable, str(script)], timeout=60, cwd=str(tmp_path))

    runner = server.Runner(
        walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
        make_config=lambda *a, **k: engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={}, risk="low", undeclared="allow"))
    runner.start("build a thing", runner.state.version)
    assert runner.state.state == engine.STOPPED and runner.state.report is None
    assert "IntakeError" in runner.state.error
    httpd = server.serve(runner, operator, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/usage")
        req.add_header("X-Operator-Token", operator.token)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert body["asks"] and body["run"] is not None
    assert body["asks"][0]["cost_usd"] == 0.125
