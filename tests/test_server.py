"""Tasks 10, 14, 15 and 16 — the back end, local only.

Four tasks in one module because they are one server, and splitting them would have produced three
that cannot be demonstrated: task 10's own done-when is "a reload mid-run rebuilds the view", which
needs task 14's snapshot; and a snapshot two browsers can race is task 16's problem, not a separate
one.

## What "local only" is being tested as

Not a bind address. Binding to loopback stops the *network*; it does not stop a **browser**, because
any page the operator visits can issue requests to `http://127.0.0.1:<port>`. So the tests below
check three separate refusals, and each stops a different attack:

* a non-loopback `Host` — DNS rebinding, where the socket is local and the origin is not
* a cross-origin `Origin` — the ordinary case of a page that is not ours
* a missing or wrong token — the one that actually holds, because a cross-origin page can *send* a
  request but cannot *read a file on disk*

The third is also task 15's answer. The identity is what the caller **proved it could read**, never
a name it typed into a body — which was the "button captioned Accept (as verifier), moved one layer
down and called enforcement" that an independent seat refused.
"""
import ast
import inspect
import json
import pathlib
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

from ai_sdlc_runner import attachments as attach_mod, cli, engine, graph, policy, server, store
from test_flow import DECISIONS, SPEC


# --- a runner whose walk is the real engine ------------------------------------------------

def _make_config(instructions, approvals, rulings, artifacts=(), rejections=(),
                 intake_history=(), *, seat_verdicts=None, risk="high"):
    del instructions, artifacts
    return engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": ["module", "none", "none"], "feedback": "done"},
        risk=risk, undeclared="allow", confirmed=approvals, rulings=rulings,
        review_seats=len(seat_verdicts) if seat_verdicts else None,
        high_risk_mode=bool(seat_verdicts))


def _dispatch(seat_verdicts=None):
    def dispatch(order):
        if order.get("seat"):
            return {"verdict": (seat_verdicts or {}).get(order["seat"], "pass")}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}
    return dispatch


def _runner(seat_verdicts=None, risk="high"):
    dispatch = _dispatch(seat_verdicts)
    return server.Runner(
        walk=lambda cfg: engine.walk(cfg, dispatch, enabled=True),
        make_config=lambda i, a, r, art=(), rej=(), hist=(): _make_config(
            i, a, r, art, rej, hist, seat_verdicts=seat_verdicts, risk=risk))


@pytest.fixture
def live(tmp_path):
    """A real server on a real loopback socket — the refusals are HTTP behaviour, not method calls."""
    operator = server.Operator.mint(tmp_path)
    runner = _runner()
    httpd = server.serve(runner, operator, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]

    def call(method, path, body=None, token=None, host=None, origin=None, raw=None,
             omit_token=False):
        # `raw` sends bytes exactly as given, for the cases about what the server does with a body
        # it cannot parse. `omit_token` sends NO header at all, which is different from sending an
        # empty one: `_guard` reads `presented is None` to decide whether the query-string fallback
        # applies, so a test that sends `token=""` cannot reach that branch. Both optional, so
        # every existing caller behaves as it did.
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", method=method,
            data=raw if raw is not None
            else (json.dumps(body).encode("utf-8") if body is not None else None))
        if not omit_token:
            req.add_header("X-Operator-Token", operator.token if token is None else token)
        req.add_header("Host", host or f"127.0.0.1:{port}")
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    yield call, runner, operator
    httpd.shutdown()


# --- local only ------------------------------------------------------------------------------

def test_it_refuses_to_bind_anything_but_loopback():
    """The refusal lives in the server so it cannot be 'temporarily' widened by a caller."""
    with pytest.raises(server.ServerError, match="refusing to bind"):
        server.serve(_runner(), server.Operator("t", "me", __import__("pathlib").Path(".")),
                     host="0.0.0.0")


def test_binding_loopback_is_allowed(tmp_path):
    httpd = server.serve(_runner(), server.Operator.mint(tmp_path), port=0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8765", "10.0.0.5"])
def test_a_non_loopback_host_header_is_refused(live, host):
    """DNS rebinding: the socket is local, the origin is not, and the Host header is the tell."""
    call, _, _ = live
    status, body = call("GET", "/run", host=host)
    assert status == 403
    assert "loopback" in body["error"]


def test_a_cross_origin_request_is_refused(live):
    call, _, _ = live
    status, body = call("GET", "/run", origin="https://evil.example.com")
    assert status == 403
    assert "cross-origin" in body["error"]


def test_our_own_origin_is_accepted(live):
    call, _, _ = live
    status, _ = call("GET", "/run", origin="http://127.0.0.1:8765")
    assert status == 200


# --- task 15: the identity is proved, not asserted ---------------------------------------------

def test_no_token_is_refused(live):
    call, _, _ = live
    status, body = call("GET", "/run", token="")
    assert status == 401
    assert "operator token" in body["error"]


def test_a_wrong_token_is_refused(live):
    call, _, _ = live
    status, _ = call("GET", "/run", token="not-the-token")
    assert status == 401


def test_the_token_is_on_disk_and_that_is_what_makes_local_only_hold(live):
    """A cross-origin page can send a request. It cannot read a file."""
    call, _, operator = live
    assert operator.token_path.exists()
    assert operator.token_path.read_text(encoding="utf-8").strip() == operator.token
    status, body = call("GET", "/whoami")
    assert status == 200 and body["operator"]


def test_the_identity_cannot_be_chosen_by_the_caller(live):
    """Task 15's actual requirement: no name in a body becomes the recorded operator."""
    call, _, operator = live
    status, body = call("GET", "/whoami")
    assert body["operator"] == operator.name
    # There is no route that accepts an identity; the only way to be somebody is to hold the token.
    status, _ = call("POST", "/whoami", {"operator": "somebody else", "version": 0})
    assert status == 404


# --- task 14: the snapshot ----------------------------------------------------------------------

def test_the_snapshot_is_readable_before_anything_runs(live):
    call, _, _ = live
    status, body = call("GET", "/run")
    assert status == 200
    assert body["state"] == server.IDLE
    assert body["version"] == 0


def test_a_reload_mid_run_rebuilds_the_view(live):
    """Task 10's done-when, which had no endpoint behind it until task 14."""
    call, _, _ = live
    status, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    assert status == 200
    assert started["state"] == engine.SUSPENDED

    status, reloaded = call("GET", "/run")
    assert status == 200
    assert reloaded["state"] == engine.SUSPENDED
    assert reloaded["at"] == started["at"]
    assert reloaded["suspended"] == started["suspended"]
    assert reloaded["version"] == started["version"]


def test_the_flow_endpoint_carries_every_node_including_the_failure_paths(live):
    """The mock-up shipped 18 of 23, all omissions on failure paths. The API does not repeat that."""
    call, _, _ = live
    status, body = call("GET", "/flow")
    assert status == 200
    ids = {n["id"] for n in body["nodes"]}
    assert len(ids) == len(graph.NODES)
    for failure_path in ("fix_pass", "re_review", "halt_second_fail",
                         "review_failed", "acceptance_failed"):
        assert failure_path in ids
    assert body["gates"].keys() == policy.GATES.keys()


def test_the_flow_endpoint_carries_the_execution_mode(live):
    call, _, _ = live
    _, body = call("GET", "/flow")
    by_id = {n["id"]: n for n in body["nodes"]}
    assert by_id["engineer_build"]["mode"] == graph.POOL
    assert by_id["engineer_build"]["main"] == "lead"
    assert by_id["engineer_selfverify"]["follows"] == "engineer_build"
    assert by_id["lead_review"]["mode"] == graph.SEAT_PANEL


# --- task 16: one run, one version --------------------------------------------------------------

def test_an_answer_must_name_the_version_it_answers(live):
    call, _, _ = live
    status, body = call("POST", "/run", {"instruction": "do it"})
    assert status == 409
    assert "version" in body["error"]


def test_a_stale_version_is_refused(live):
    """The stale tab: it is answering a state this run has moved past."""
    call, _, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    stop = started["suspended"]

    status, body = call("POST", "/run/gate",
                        {"version": 0, "gate": stop["gate"], "node_id": stop["node_id"]})
    assert status == 409
    assert "moved" in body["error"]


def test_a_double_click_does_not_spend_two_approvals(live):
    """The exact 'advance twice' an independent seat named."""
    call, _, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    stop = started["suspended"]
    answer = {"version": started["version"], "gate": stop["gate"], "node_id": stop["node_id"]}

    first_status, first = call("POST", "/run/gate", answer)
    second_status, second = call("POST", "/run/gate", dict(answer))

    assert first_status == 200
    assert second_status == 409, "the second click was accepted — that is two approvals from one"
    assert "moved" in second["error"]


def test_the_version_advances_on_every_change(live):
    call, _, _ = live
    _, before = call("GET", "/run")
    _, started = call("POST", "/run", {"instruction": "do it", "version": before["version"]})
    assert started["version"] > before["version"]


# --- answering the right question ---------------------------------------------------------------

def test_a_gate_answer_is_refused_where_a_tie_is_waiting(tmp_path):
    """A gate asks whether the run may proceed; a tie asks which way. Neither answers the other."""
    names = policy.seat_names(2)
    runner = _runner(seat_verdicts={names[0]: "pass", names[1]: "fail"}, risk="low")
    runner.start("do it", 0)
    assert runner.state.state == engine.SUSPENDED
    assert runner.state.report.suspended["undecided"] is True

    with pytest.raises(server.ServerError, match="a tie to break"):
        runner.approve(runner.state.version, "lead_review", "lead_review")


def test_a_ruling_is_refused_where_a_gate_is_waiting():
    runner = _runner()
    runner.start("do it", 0)
    assert runner.state.report.suspended["undecided"] is not True
    with pytest.raises(server.ServerError, match="a gate to approve"):
        runner.rule(runner.state.version, "lead_review", "pass")


def test_answering_when_nothing_is_waiting_is_refused():
    runner = _runner(risk="low")
    with pytest.raises(server.ServerError, match="nothing waiting"):
        runner.approve(0, "merge", "merge")


def test_a_second_run_cannot_start_over_a_suspended_one():
    """One project, one runner — and a suspended run is not a free slot."""
    runner = _runner()
    runner.start("do it", 0)
    with pytest.raises(server.ServerError, match="already"):
        runner.start("something else", runner.state.version)


# --- the walk still never blocks ----------------------------------------------------------------

def test_the_server_waits_and_the_walk_does_not():
    """Task 1's guarantee, checked from the side that does the waiting.

    The server holds a suspended run for as long as nobody answers. The engine does not: the walk
    that produced the suspension already returned, so there is no live frame to lose.
    """
    import inspect

    runner = _runner()
    runner.start("do it", 0)
    assert runner.state.state == engine.SUSPENDED

    source = inspect.getsource(server.Runner._advance)
    for blocking in ("time.sleep", "input(", ".join()"):
        assert blocking not in source

    # And answering it continues the same run rather than starting a new one.
    stop = runner.state.report.suspended
    out = runner.approve(runner.state.version, stop["gate"], stop["node_id"])
    assert out["at"] != stop["node_id"]


def test_a_failing_walk_reports_stopped_rather_than_looking_idle():
    """A crash must not leave the console showing a runner that is quietly doing nothing."""
    def boom(cfg):
        raise RuntimeError("the dispatcher fell over")

    runner = server.Runner(walk=boom, make_config=lambda i, a, r, art=(), rej=(), hist=(): None)
    out = runner.start("do it", 0)
    assert out["state"] == engine.STOPPED
    assert "fell over" in out["error"]


def test_a_second_runner_cannot_bind_the_same_port(tmp_path):
    """One project, one runner — enforced, not asserted.

    `ThreadingHTTPServer` sets `allow_reuse_address`, which on Windows lets a second process bind a
    port the first already holds. Both then answer and which one gets a connection is undefined.
    Found live: a second `serve` during a test left the console reading answers from the process
    that had been replaced — a stale build serving requests, with nothing saying so.
    """
    first = server.serve(_runner(), server.Operator.mint(tmp_path / "a"), port=0)
    try:
        port = first.server_address[1]
        with pytest.raises(server.ServerError, match="already there"):
            server.serve(_runner(), server.Operator.mint(tmp_path / "b"), port=port)
    finally:
        first.server_close()


def test_the_console_shell_loads_without_a_token(tmp_path):
    """A browser cannot attach a header to a navigation, so the shell must load without one.

    It carries no data, no state and no governance — it is markup that asks the server what is true,
    and every one of those questions needs the token. This is the one route that does not.
    """
    operator = server.Operator.mint(tmp_path)
    httpd = server.serve(_runner(), operator, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert resp.headers["Content-Type"].startswith("text/html")
            assert "Content-Security-Policy" in resp.headers
        assert "<title>runner</title>" in body
        assert operator.token not in body, (
            "the page must not carry the token — it arrives in the URL fragment, which browsers "
            "never send anywhere, so a served page is not a place a credential can leak from")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_shell_is_still_refused_to_a_rebinding_host(tmp_path):
    """Exempt from the token, not from the Host check. Skipping both would be a hole, not a shell."""
    operator = server.Operator.mint(tmp_path)
    httpd = server.serve(_runner(), operator, port=0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/")
        req.add_header("Host", "evil.example.com")
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False, "a rebinding host was served the console"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_only_the_stream_may_take_the_token_from_the_query_string(live):
    """EventSource has no way to set a header — that is why the exception exists, and why it is one.

    A query string reaches access logs, so it is the weaker place to carry a credential. Allowing it
    generally would move every request to the weaker place for the convenience of one.
    """
    call, _, operator = live
    status, _ = call("GET", f"/flow?token={operator.token}", token="")
    assert status == 401


def test_the_snapshot_carries_where_the_work_was_dispatched(tmp_path):
    """"At random" is a claim, and a console that cannot show it cannot let anyone check it."""
    dispatched = {}

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                dispatched[order["node_id"]] = model
                if seat:
                    return {"verdict": "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    runner = server.Runner(
        walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
        make_config=lambda i, a, r, art=(), rej=(), hist=(): engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={"next_module": ["module", "none", "none"], "feedback": "done"},
            risk="low", undeclared="allow", confirmed=a, rulings=r,
            node_models={"engineer_build": ["opus", "codex", "gemini"]}))

    out = runner.start("do it", 0)
    assert out["dispatches"], "the snapshot must say where the pool sent the work"
    assert any("dispatched to" in d for d in out["dispatches"])
    assert dispatched["engineer_selfverify"] == dispatched["engineer_build"]


def test_a_resumed_run_does_not_re_ask_what_it_already_answered(tmp_path):
    """The defect a three-module project found, and a one-module project could not.

    Every gate approval re-enters `walk` from `intake`. With a journal, the asks already answered
    come back from it and no session opens; **without** one, `resume` is False and every ask is put
    again — so a run with four gates asks everything five times and re-runs every side effect with
    it. The demo agent happened to be idempotent, so the only visible trace was a reviewer seeing
    modules that had not been built when it was asked.

    `serve` is the caller that could walk around the engine's own refusal, because it never asked
    for a journal at all.
    """
    asked = []

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                asked.append(order["node_id"])
                if seat:
                    return {"verdict": "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    journal = engine.AskJournal(tmp_path / "asks")
    runner = server.Runner(
        walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
        make_config=lambda i, a, r, art=(), rej=(), hist=(): engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={"next_module": ["module", "none", "none"], "feedback": "done"},
            risk="high", undeclared="allow", confirmed=a, rulings=r,
            resume=True, journal=journal))

    runner.start("do it", 0)
    after_first = len(asked)
    assert after_first, "the first walk should have asked something"

    stop = runner.state.report.suspended
    runner.approve(runner.state.version, stop["gate"], stop["node_id"])

    replayed = asked[after_first:]
    already = set(asked[:after_first])
    assert not [n for n in replayed if n in already and n != stop["node_id"]], (
        f"the resumed walk re-asked {sorted(set(replayed) & already)} — with a journal those "
        f"answers are on disk, and asking again re-runs whatever the agent did the first time")


def test_an_unexpected_failure_still_gets_an_answer(live, monkeypatch):
    """A handler that dies takes the socket with it, and the client sees `RemoteDisconnected`.

    That is a failure with no message — it sends whoever is debugging to the network rather than to
    the traceback. Found live: a missing attachment directory took down the request instead of
    reporting itself.
    """
    call, runner, _ = live

    def boom(*a, **kw):
        raise ValueError("something nobody planned for")

    monkeypatch.setattr(runner, "instruct", boom)
    status, body = call("POST", "/run/instruct", {"version": 0, "instruction": "x"})
    assert status == 500
    assert "nobody planned for" in body["error"]


def test_the_attachment_store_recreates_a_directory_taken_from_under_it(tmp_path):
    from ai_sdlc_runner import attachments

    store = attachments.Store(tmp_path / "att")
    import shutil
    shutil.rmtree(store.dir)
    a = store.add("spec.md", b"the spec")
    assert store.path_for(a.id).exists()


def test_the_console_offers_a_send_back_only_where_the_graph_has_one(live):
    """A control the server must then decline is worse than no control.

    `/flow` carries `rejects_to`, and the page reads it. `merge` has none — rejecting it means *do
    not merge*, and there is no node for that.
    """
    call, _, _ = live
    _, body = call("GET", "/flow")
    by_id = {n["id"]: n for n in body["nodes"]}
    assert by_id["pm_confirm"]["rejects_to"] == "pm_plan"
    assert by_id["merge"]["rejects_to"] is None

    page = (__import__("pathlib").Path(server.__file__).parent
            / "console" / "index.html").read_text(encoding="utf-8")
    assert "here.rejects_to" in page, "the page should read the flow rather than guess"


def test_refusing_a_gate_that_has_nowhere_to_go_is_refused_by_the_server(live):
    call, _, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    # Drive to `merge`, the one gate with no rejection target.
    for _ in range(10):
        if started["state"] != "suspended":
            break
        stop = started["suspended"]
        if stop["node_id"] == "merge":
            status, body = call("POST", "/run/reject",
                                {"version": started["version"], "gate": "merge",
                                 "node_id": "merge", "reason": "no"})
            assert status == 409
            assert "nowhere to send a refusal" in body["error"]
            return
        _, started = call("POST", "/run/gate",
                          {"version": started["version"], "gate": stop["gate"],
                           "node_id": stop["node_id"]})
    raise AssertionError("the run never reached merge")


def test_the_console_has_a_handler_for_every_button_it_draws():
    """A button with no handler is a control that does nothing — which shipped once already.

    `add to the brief` was in the markup for a whole change with no `onclick` behind it, because an
    edit that should have added one failed silently. This reads the page and checks.
    """
    page = (__import__("pathlib").Path(server.__file__).parent
            / "console" / "index.html").read_text(encoding="utf-8")
    import re
    ids = set(re.findall(r'id="([a-z]+)"[^>]*>(?:[^<]*)</button>', page))
    ids |= set(re.findall(r'<button[^>]*id="([a-z]+)"', page))
    for control in ids:
        assert f'$("#{control}").onclick' in page, \
            f"the page draws #{control} and nothing listens to it"


def test_adding_to_the_brief_re_walks_the_run(tmp_path):
    """Found live: the instruction landed, the version moved, and nothing was re-asked.

    The seats went on reporting what the *first* instruction had not said, however much was added
    afterwards — so "add to the brief" looked like it worked and changed nothing anybody could see.
    """
    asked = []

    def factory(seat=None, model=None):
        class S(engine.Session):
            def ask(self, order):
                asked.append(order["node_id"])
                if seat:
                    return {"verdict": "pass"}
                branch = {"pm_confirm": "yes", "pm_signoff": "yes",
                          "lead_task_review": "pass", "re_review": "pass",
                          "qa_accept": "pass"}.get(order["node_id"])
                return {"verdict": branch} if branch else {"ok": True}

            def close(self):
                pass
        return S()

    journal = engine.AskJournal(tmp_path / "asks")
    runner = server.Runner(
        walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
        make_config=lambda i, a, r, art=(), rej=(), hist=(): engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={"next_module": ["module", "none", "none"], "feedback": "done"},
            risk="high", undeclared="allow", confirmed=a, rulings=r,
            instructions=i, resume=True, journal=journal))

    runner.start("build it", 0)
    before = len(asked)
    runner.instruct(runner.state.version, "and make it dark")
    assert len(asked) > before, (
        "adding to the brief asked nobody anything — the instruction landed and the run did not "
        "move, so nothing downstream ever saw it")


@pytest.mark.parametrize("origin", [
    "http://localhost.evil.example",
    "http://127.0.0.1.evil.example",
    "https://localhost.attacker.test",
    "http://[::1].evil.example",
])
def test_a_lookalike_origin_is_refused(live, origin):
    """A prefix is not a host.

    The check used to ask whether the origin *started with* `http://localhost`. An attacker can
    register `localhost.evil.example`, and it does. Found by an independent seat reading the check;
    all three lookalikes it named were accepted when run.
    """
    call, _, _ = live
    status, body = call("GET", "/run", origin=origin)
    assert status == 403, f"{origin} was accepted"
    assert "cross-origin" in body["error"]


@pytest.mark.parametrize("origin", [
    "http://localhost:8765", "http://127.0.0.1:9999", "https://127.0.0.1", "http://[::1]:8080",
])
def test_our_own_origins_are_still_accepted(live, origin):
    """The fix must not refuse the page it serves."""
    call, _, _ = live
    status, _ = call("GET", "/run", origin=origin)
    assert status == 200, f"{origin} was refused"


# ── one walk at a time (CHG-20260823-43) ──────────────────────────────────────────────────────
#
# **Which entry point actually had the hole**, checked rather than assumed. Both seats said a second
# walk could start; the first version of these tests drove it through `instruct()` and found that
# `instruct` already refuses while a run is `running`:
#
#     this run is running. An instruction can be added when it is waiting or finished
#
# So does `start` (refuses unless idle/finished/stopped), and so do `approve`, `reject` and `rule`
# (`_require_suspension`). **`attach()` is the one that gates only on version** — which is exactly
# what fable-seat wrote, and what these tests therefore use.

def _gated_runner(tmp_path, walks, gate):
    """A runner whose walk blocks on `gate`, so a second caller is guaranteed to arrive mid-walk."""
    from ai_sdlc_runner import attachments

    def walk(cfg):
        walks.append(tuple(cfg.instructions))
        gate.wait(timeout=10)
        report = engine.RunReport()
        report.state = engine.FINISHED
        return report

    return server.Runner(
        walk=walk,
        make_config=lambda i, a, r, art=(), rej=(), hist=(): _make_config(i, a, r, art, rej, hist),
        store=attachments.Store(tmp_path / "att"))


def _start_a_blocked_walk(runner, walks):
    thread = threading.Thread(target=lambda: runner.start("build it", 0), daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not walks and time.time() < deadline:
        time.sleep(0.01)
    assert walks, "the walk never started"
    return thread


def test_an_attachment_during_a_walk_does_not_start_a_second_walk(tmp_path):
    """`attach()` mutates the state under `_lock`, releases it, and calls `_advance()`. With no
    gate, both threads entered the walk — two walks over one run and one `Conversation`."""
    walks, gate = [], threading.Event()
    runner = _gated_runner(tmp_path, walks, gate)
    thread = _start_a_blocked_walk(runner, walks)

    runner.attach(runner.state.version, "spec.md", b"the spec")
    assert len(walks) == 1, f"a second walk started: {walks}"

    gate.set()
    thread.join(timeout=10)
    assert len(walks) == 2, "the attachment was never walked"


def test_the_attachment_that_arrives_during_a_walk_is_not_dropped(tmp_path):
    """Refusing the second caller would have been simpler and would have discarded the effect of
    what the operator did: an attachment reaches **every** work order, and the walk in flight built
    its config before that attachment existed. Recorded-and-never-acted-on is this project's own
    worst failure shape, so the running walk goes round again instead."""
    walks, gate = [], threading.Event()
    runner = _gated_runner(tmp_path, walks, gate)
    thread = _start_a_blocked_walk(runner, walks)

    runner.attach(runner.state.version, "spec.md", b"the spec")
    gate.set()
    thread.join(timeout=10)

    assert len(walks) == 2, f"expected exactly one further walk, got {len(walks)}"
    assert runner.state.attachments, "the attachment is not in the state at all"


def test_several_attachments_during_one_walk_coalesce_into_one_further_walk(tmp_path):
    """Not one further walk each — that would be the same storm, serialised."""
    walks, gate = [], threading.Event()
    runner = _gated_runner(tmp_path, walks, gate)
    thread = _start_a_blocked_walk(runner, walks)

    for n in range(4):
        runner.attach(runner.state.version, f"a{n}.md", f"body {n}".encode())
    assert len(walks) == 1, f"{len(walks)} walks ran while one was in flight"

    gate.set()
    thread.join(timeout=10)
    assert len(walks) == 2, f"four attachments produced {len(walks) - 1} further walks"


def test_the_gate_reopens_when_a_walk_raises(tmp_path):
    """A walk that throws must not leave the runner permanently refusing to walk again."""
    def exploding(cfg):
        raise RuntimeError("the backend died")

    runner = server.Runner(
        walk=exploding,
        make_config=lambda i, a, r, art=(), rej=(), hist=(): _make_config(i, a, r, art, rej, hist))
    runner.start("x", 0)
    assert runner._walking is False, "a failed walk left the gate shut"
    assert runner.state.state == engine.STOPPED


def test_only_attach_reaches_advance_without_a_state_gate():
    """The finding, pinned where it actually is.

    If a future change adds another caller of `_advance` that does not gate on run state, this says
    so — rather than the next reviewer having to rediscover which of six entry points was the one.
    """
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(server.Runner)))
    ungated = []
    for func in tree.body[0].body:
        if not isinstance(func, ast.FunctionDef):
            continue
        body = ast.unparse(func)
        if "self._advance()" not in body or func.name.startswith("_"):
            continue
        gated = "_require_suspension" in body or "self.state.state not in" in body
        if not gated:
            ungated.append(func.name)
    assert ungated == ["attach"], (
        f"the set of entry points reaching _advance without a state gate has changed: {ungated}")


# ── the lost wakeup in the gate itself (CHG-20260823-44) ──────────────────────────────────────

def test_an_action_arriving_as_the_walk_decides_to_stop_is_not_stranded(tmp_path):
    """The window CHG-43's own gate left open.

    **This test does not catch that window.** Reintroducing it — clearing `_walking` in a separate
    lock acquisition — leaves this test passing; only
    `test_the_release_and_the_decision_are_one_critical_section` fails. Verified by an
    acceptance-round verifier who put the window back and ran it (CHG-20260827-15), and reported at
    the time by CHG-20260823-45.

    Keep it: it covers coalescing under a forced arrival, which is worth having. Do not cite it as
    the guard on the lost wakeup, and do not "upgrade" the structural test away on the strength of
    it — for a window this narrow, the structural test is the load-bearing one.

    The walk took the lock, saw nothing waiting, and **returned while `_walking` was still true** —
    `_walking` was cleared afterwards, in a `finally`, under a second acquisition of the lock.
    Between those two, a caller could take the lock, see `_walking` true, set `_walk_again`, and
    have it cleared out from under them by a walk that had already decided to stop.

    Forced deterministically: the attachment is posted from inside the gap, by a walk that blocks
    on its *second* call while another thread attaches.
    """
    from ai_sdlc_runner import attachments

    walks, entered_second = [], threading.Event()
    release_second = threading.Event()

    def walk(cfg):
        walks.append(tuple(cfg.instructions))
        if len(walks) == 2:
            entered_second.set()
            release_second.wait(timeout=10)
        report = engine.RunReport()
        report.state = engine.FINISHED
        return report

    runner = server.Runner(
        walk=walk,
        make_config=lambda i, a, r, art=(), rej=(), hist=(): _make_config(i, a, r, art, rej, hist),
        store=attachments.Store(tmp_path / "att"))

    # First walk runs to completion; during it, one attachment arrives, so the gate loops. The
    # second walk blocks, and a further attachment arrives while it is inside.
    first = threading.Thread(target=lambda: runner.start("go", 0), daemon=True)
    first.start()
    while not walks:
        time.sleep(0.01)
    runner.attach(runner.state.version, "one.md", b"1")

    assert entered_second.wait(timeout=10), "the gate never looped for the first attachment"
    runner.attach(runner.state.version, "two.md", b"2")
    release_second.set()
    first.join(timeout=10)

    assert len(walks) == 3, (
        f"the second attachment was stranded: {len(walks)} walks for two mid-walk attachments")
    assert runner._walk_again is False
    assert runner._walking is False


def test_the_gate_never_rests_with_something_still_flagged(tmp_path):
    """The invariant, hammered.

    `_walk_again` true while `_walking` false means an operator's action is sitting there with
    nobody to act on it. Many callers, short walks, then assert the resting state is coherent.

    Same limit as the test above, and worth stating twice because both were cited for it: with the
    lost-wakeup window reintroduced, this passes. It hammers the invariant in the states the
    scheduler happens to produce; it cannot make the interleaving happen. The guard on that window
    is `test_the_release_and_the_decision_are_one_critical_section` (CHG-20260827-15).
    """
    from ai_sdlc_runner import attachments

    walks = []

    def walk(cfg):
        walks.append(1)
        report = engine.RunReport()
        report.state = engine.FINISHED
        return report

    runner = server.Runner(
        walk=walk,
        make_config=lambda i, a, r, art=(), rej=(), hist=(): _make_config(i, a, r, art, rej, hist),
        store=attachments.Store(tmp_path / "att"))
    runner.start("go", 0)

    def poke(n):
        for i in range(12):
            try:
                runner.attach(runner.state.version, f"a{n}-{i}.md", f"{n}{i}".encode())
            except server.ServerError:
                pass                      # a stale version, which is the API doing its job
    threads = [threading.Thread(target=poke, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert runner._walking is False, "a walk is still marked in flight after everything joined"
    assert runner._walk_again is False, (
        "an action is flagged for a walk that will never come; it will be picked up by an "
        "unrelated future caller, which will then walk twice")


def test_the_release_and_the_decision_are_one_critical_section():
    """Structural, and stated as such.

    The two behavioural tests above can only catch this window when the interleaving happens to
    occur — and it does not occur: put the window back and both of them pass while this one fails.
    That was measured, twice (CHG-20260823-45, then again by the acceptance round of 2026-08-27),
    so it is a fact about this file rather than a caution.

    **This is the test that holds the property.** What makes the window *impossible* is that
    `_walking = False` and the check that found nothing waiting sit inside the same
    `with self._lock`. That is what this asserts, and asserting the shape of the code is the right
    instrument here: a race that needs a scheduler coincidence is not reliably reachable from a
    behavioural test, and pretending otherwise is how the wrong test gets trusted (CHG-20260827-15).
    """
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(server.Runner._advance))
    tree = ast.parse(source)
    together = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        # **Which** context manager, checked. The first version of this test asserted only that two
        # substrings appeared inside some `with` — fable-seat mutated the gate to keep both strings
        # in one block while clearing `_walking` on the wrong branch, and this passed. A test
        # reading vocabulary, written to replace a test reading vocabulary.
        holds_the_lock = any(ast.unparse(item.context_expr) == "self._lock"
                             for item in node.items)
        if not holds_the_lock:
            continue
        body = ast.unparse(node)
        if "self._walking = False" not in body or "self._walk_again" not in body:
            continue
        # ...and on the branch that decided to stop, not the other one.
        for inner in ast.walk(node):
            if isinstance(inner, ast.If) and "self._walk_again" in ast.unparse(inner.test):
                stopping = inner.body if isinstance(inner.test, ast.UnaryOp) else inner.orelse
                if any("self._walking = False" in ast.unparse(s) for s in stopping):
                    together = True
    assert together, (
        "`_walking = False` is not cleared under `self._lock` on the branch that found nothing "
        "waiting — the lost wakeup CHG-20260823-44 closed")


# --------------------------------------------------------------------------------------
# the console's panels (CHG-20260827-02)
#
# Structural, and stated as such in every test below. There is no JavaScript engine in this
# environment, so none of these proves the panels *render*; what they prove is that the chain which
# has to exist for rendering to happen has not been cut. That matters because it had been cut-able:
# deleting `drawFlow` and `drawModels` entirely left the whole suite green, which an acceptance
# round established on 2026-08-27 and both verifying engines reported independently.
# --------------------------------------------------------------------------------------

def _console_page() -> str:
    import pathlib

    return (pathlib.Path(server.__file__).parent
            / "console" / "index.html").read_text(encoding="utf-8")


def test_every_endpoint_the_console_calls_is_one_the_server_answers():
    """Structural. A page calling a route that does not exist fails only in a browser.

    The reverse direction is deliberately **not** asserted: the server answers routes the console
    does not use, and that is fine — `runner serve` is an HTTP surface, not only this page's
    backend.
    """
    import re

    page = _console_page()
    called = set(re.findall(r'api\("(?:GET|POST)",\s*"([^"]+)"', page))
    assert called, "the console calls no endpoints at all; has `api(` been renamed?"

    source = __import__("inspect").getsource(server)
    missing = [route for route in sorted(called) if f'"{route}"' not in source]
    assert not missing, (
        f"the console calls {missing}, which `server.py` has no handler for")


def test_the_flow_panel_is_drawn_and_something_calls_it():
    """Structural. `drawFlow` existing is not the property — being reached is.

    Deleting the function, or the call, left the suite green before CHG-20260827-02.
    """
    page = _console_page()
    assert "function drawFlow()" in page, "the flow panel's renderer is gone"
    calls = page.count("drawFlow()")
    assert calls >= 2, (
        f"`drawFlow` is defined and called {calls - 1} time(s) — a renderer nothing reaches draws "
        f"nothing")
    assert 'api("GET", "/flow")' in page, "the flow panel no longer asks the server for the flow"


def test_the_models_panel_is_drawn_and_can_say_a_model_is_dispatched_nowhere():
    """Structural, and the sentence is the point.

    CHG-20260823-12 exists to answer "where is this model actually used", and the answer that
    carries the most information is **nowhere**. A panel that silently omits unused models answers
    the opposite question.
    """
    page = _console_page()
    assert "function drawModels()" in page, "the models panel's renderer is gone"
    assert page.count("drawModels()") >= 2, "`drawModels` is defined and never called"
    assert 'api("GET", "/config/nodes")' in page, (
        "the models panel no longer asks the server which node uses which model")
    assert "nothing dispatches to it" in page, (
        "the models panel lost the sentence it exists to be able to say")


# --- the three the mutation group found unpinned (CHG-20260830-01) ----------------------------


def test_the_token_is_compared_in_constant_time(tmp_path, monkeypatch):
    """`==` on a secret leaks its prefix by timing, and no behavioural test can see that.

    So the mechanism is named rather than the symptom: `accepts` must go through
    `secrets.compare_digest`. Replacing it with `==` left all 56 server tests green, while the
    comment beside it says *"a comparison that leaks its prefix is free to avoid and awkward to
    explain afterwards"* — a reason with nothing holding it.
    """
    operator = server.Operator.mint(tmp_path)
    seen = []
    real = server.secrets.compare_digest

    def spy(presented, known):
        seen.append((presented, known))
        return real(presented, known)

    monkeypatch.setattr(server.secrets, "compare_digest", spy)
    assert operator.accepts(operator.token) is True
    assert operator.accepts("not-the-token") is False

    assert seen, "the token was compared without secrets.compare_digest"
    assert all(known == operator.token for _, known in seen)


def test_an_absent_token_is_refused_before_anything_is_compared(tmp_path):
    """`bool(presented) and …` short-circuits, so `None` never reaches the comparison at all."""
    operator = server.Operator.mint(tmp_path)
    assert operator.accepts(None) is False
    assert operator.accepts("") is False


def test_only_the_event_stream_takes_the_token_from_the_query_string(live):
    """EventSource cannot set headers, so the stream accepts `?token=`. Nothing else may.

    A query parameter reaches access logs, which is why the fallback is one read-only route rather
    than a general one. Widening it to every route left all 56 tests green.
    """
    call, _, operator = live
    # No header at all, not an empty one: `_guard` only consults the query string when the header is
    # absent, so `token=""` never reaches the branch this test is about. The first version sent an
    # empty header, passed, and left the mutation NOT CAUGHT. Restored — CHG-20260830-05 cut this as
    # padding while adding an explanation of exactly this shape nine lines below, and ACC-20260830-01
    # row 4 still turns on the distinction (CHG-20260830-06, idiom seat).
    status, body = call("GET", f"/run?token={operator.token}", omit_token=True)
    assert status == 401, "an ordinary route accepted the token from the query string"
    assert "operator token" in body["error"]


def test_a_body_that_is_not_json_is_refused_in_words(live):
    """Not a traceback. `_body` catches `ValueError`; narrowing it to `TypeError` left every test
    green while a malformed body became a 500 — the shape `cmd_serve` catching only `StoreError`
    had, one layer out."""
    call, _, _ = live
    # `/run/instruct`, not `/run/instruction`. The first version posted to a route that does not
    # exist and passed anyway, because `do_POST` parses the body before dispatching — so it
    # exercised generic parsing rather than the route its name claims (CHG-20260830-05).
    status, payload = call("POST", "/run/instruct", raw=b"{not json at all")

    assert status != 500, "a malformed body reached the operator as a server error"
    assert "not JSON" in payload["error"]


# ── three stop shapes, three answers (CHG-20260903-23) ────────────────────────────────────────

def test_an_incomplete_stop_is_not_a_gate_to_approve():
    """`_require_suspension`'s own comment: *"A gate asks whether the run may proceed; a tie asks
    which way. Accepting one for the other would record an answer to a question nobody was asked."*

    The engine emits **three** shapes — a gate, an incomplete requirement, and a tie — and the check
    read `undecided` alone. So an incomplete stop was accepted on the approve path, and
    `intake_review` has no gate, so `approve()` stored `Approval(gate=None, …)` — which `walk`'s
    up-front check then refuses on **every** subsequent walk. `RunState.approvals` is only appended
    to and read; there is no removal route, so the run was unrecoverable short of `POST /run`
    (CHG-20260903-23, defect seat L-25).
    """
    runner = server.Runner.__new__(server.Runner)
    runner.state = server.RunState(state=engine.SUSPENDED)
    runner.state.report = engine.RunReport(state=engine.SUSPENDED)

    shapes = {
        "gate":       {"incomplete": False, "undecided": False, "gate": "merge"},
        "incomplete": {"incomplete": True, "undecided": False, "gate": None, "missing": ["flow"]},
        "tie":        {"incomplete": False, "undecided": True, "gate": None},
    }

    def try_it(shape, undecided):
        runner.state.report.suspended = dict(shapes[shape])
        try:
            server.Runner._require_suspension(runner, undecided)
            return "accepted"
        except server.ServerError as exc:
            return str(exc)

    assert try_it("gate", False) == "accepted"
    assert try_it("tie", True) == "accepted"
    assert "not complete" in try_it("incomplete", False), "an incomplete stop is not a gate"
    assert "not complete" in try_it("incomplete", True), "and it is not a tie either"
    assert "POST /run/instruct" in try_it("incomplete", False), (
        "the refusal must name the route that does answer it")
    assert "flow" in try_it("incomplete", False), "and say what is missing"


def test_the_refusal_names_what_the_run_is_actually_waiting_for():
    """The text was wrong as well as the check: at an incomplete stop it said *"waiting for a gate
    to approve"*. It is waiting for a requirement somebody has to finish."""
    runner = server.Runner.__new__(server.Runner)
    runner.state = server.RunState(state=engine.SUSPENDED)
    runner.state.report = engine.RunReport(state=engine.SUSPENDED)
    runner.state.report.suspended = {"incomplete": True, "undecided": False, "gate": None}
    try:
        server.Runner._require_suspension(runner, False)
        raise AssertionError("an incomplete stop must not be approvable")
    except server.ServerError as exc:
        assert "a gate to approve" not in str(exc), str(exc)


# ── the console showed less than the server sent, and one card lied about being an ask ──────────
#
# Rules, not instances. The six keys that reached no front end and the one class token with a dot
# in it were both found by reading; a test naming the six and the one would go green the moment a
# seventh key or a second typo arrived. These read the shapes instead (CHG-20260903-29).


def _console():
    return (pathlib.Path(server.__file__).parent / "console" / "index.html").read_text(
        encoding="utf-8")


def test_every_key_the_server_sends_reaches_the_console():
    """`confirmations`, `rulings`, `rejections`, `survey`, `send_backs` and `adjudications` were
    computed on every poll, shipped to the browser, and rendered by nothing — which between them
    are the whole record of what the run decided and why.

    This was CHG-20260901-15 task 24. `ACC-20260903-23` — an **accepted** record — deferred it to
    that task, and that record was later withdrawn, so an accepted reservation pointed at nothing
    until CHG-20260903-29 gave it an owner.
    """
    page = _console()
    snapshot = server.RunState().snapshot()

    unreached = [key for key in snapshot
                 if not re.search(r"\b%s\b" % re.escape(key), page)]

    assert unreached == [], f"the server sends these and the console renders nothing for them: {unreached}"


def test_no_class_attribute_carries_a_token_that_starts_with_a_dot():
    """`class="ask .row"` is two tokens, the second named `.row`.

    Selecting it needs `.\\.row`, which the file did not contain, so `.ask .row{display:flex}` —
    a *descendant* selector — never matched. What did match was `.ask`, the amber card the
    stylesheet reserves for *"the run is waiting for you"*: the start controls were permanently
    dressed as a pending question, and at a real gate the page showed two amber cards, one of which
    was not an ask.

    A CSS selector written into a class attribute is silent in every direction — no parse error, no
    console warning, and a plausible-looking page.
    """
    page = _console()

    dotted = re.findall(r"class=\"[^\"]*(?<![\w-])\.[\w-]+", page)

    assert dotted == [], f"class attributes carrying a selector rather than a name: {dotted}"


# ── an approval names the stop it answers, and a finished run is not still failing ──────────────


def test_approving_a_gate_the_run_is_not_waiting_at_is_refused():
    """`_require_suspension` checks *that* the run is waiting, never *which* gate it waits at.

    So a client could approve `acceptance` while the run was suspended at `plan_confirmed`, and
    `state.approvals` is append-only with no removal route — the pre-authorisation then waited
    indefinitely for a rung the person would never be shown. Driven end to end before the fix, it
    opened `halt_independent` at `qa_accept` on a high-risk run whose operator answered only the
    seven stops the console put in front of them (CHG-20260903-34, risk seat L-47).
    """
    runner = _runner()
    state = runner.start("do it", 0)
    waiting = state["suspended"]["gate"]
    assert waiting != "acceptance", "this test needs a run waiting somewhere else"

    with pytest.raises(server.ServerError, match="waiting at"):
        runner.approve(state["version"], "acceptance", None)


def test_an_approval_through_the_door_names_the_node_and_the_run():
    """`Approval`'s docstring: `node_id` and `run_id` are *"what make refusing a stale or
    misdirected answer possible"*, and `None` is *"the wrong one for an answer typed into a console
    after a stop."* This is that console, and it was passing the wrong one.
    """
    runner = _runner()
    state = runner.start("do it", 0)
    stop = state["suspended"]

    runner.approve(state["version"], stop["gate"], None)

    minted = runner.state.approvals[-1]
    assert minted.node_id == stop["node_id"], minted
    assert minted.run_id == stop["run_id"], minted


def test_a_finished_run_does_not_still_carry_the_failure_before_it():
    """`state.error` was assigned at one site and cleared at none.

    `instruct` and `attach` reach `_advance` without guarding on suspension, so an operator who
    added a line to the brief after a failure got a **finished** run still showing the error — and
    CHG-20260903-29, which reported this as not reproducing, is what made the field reach the page.
    The measurement behind that report tested two of six `_advance` call sites
    (CHG-20260903-34, conformance seat L-48).
    """
    calls = {"n": 0}

    def walk(cfg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the disk went away")
        report = engine.RunReport()
        report.state = engine.FINISHED
        report.halted_at = "done"
        return report

    runner = server.Runner(walk=walk, make_config=lambda *a, **k: object())

    failed = runner.start("do it", 0)
    assert failed["state"] == engine.STOPPED
    assert failed["error"], "the failure must still be reported when it is true"

    after = runner.instruct(failed["version"], "try again")

    assert after["state"] == engine.FINISHED
    assert after["error"] == "", after["error"]


# ── the provenance the server computed and dropped (CHG-20260903-39) ─────────────────────────────


def test_a_freshly_started_server_already_knows_where_each_assignment_came_from():
    """`cmd_serve` computes this map with `store.resolve` and dropped it, so `held["source"]`
    stayed `{}` until the first config **write**.

    `GET /config/nodes` on a freshly started console therefore answered `"source": {}` against
    `docs/API.md`'s own *"an override nobody can see is worse than no override"* (defect seat
    L-51).
    """
    import inspect

    assert "assignment_source" in inspect.signature(server.serve).parameters
    assert "assignment_source" in inspect.signature(server.make_handler).parameters

    source = {"node_models.engineer_build": "plan"}
    handler = server.make_handler(
        server.Runner(walk=lambda cfg: engine.RunReport(), make_config=lambda *a, **k: object()),
        server.Operator.mint(pathlib.Path(tempfile.mkdtemp())),
        assignment_source=source)

    assert handler is not None


#: **Removed, not renamed** (CHG-20260903-39). This slot held
#: `test_the_cli_hands_the_provenance_it_computed_to_the_server`, which asserted the literal
#: string `"assignment_source=assignment_source"` appeared in `cmd_serve`'s source. Renaming the
#: local turned it red with no defect present, and handing over the same map under any other
#: expression left it green — a check on the wording rather than the property, which is the
#: class this change already had to fix once in `models.save`'s guard. The replacement is
#: `test_cmd_serve_hands_over_the_provenance_it_computed` at the end of this file: it reads the
#: AST and asserts that what reaches `serve` is a name `store.resolve` bound.


def test_a_freshly_started_server_answers_the_assignment_provenance():
    """**The provenance is answered before any write** (CHG-20260903-39, defect seat L-51).

    `cmd_serve` computes this map with `store.resolve` and dropped it, so `held["source"]` stayed
    empty until the first config *write*, and `GET /config/nodes` on a freshly started console
    answered `"source": {}` — against `docs/API.md`'s own *"an override nobody can see is worse
    than no override"*. No request is made here except the read: the point is what a server that has
    served nothing yet already knows.
    """
    tmp = pathlib.Path(tempfile.mkdtemp())
    operator = server.Operator.mint(tmp)
    source = {"node_models.draft": store.FROM_STORE, "seat_models.risk": store.FROM_PLAN}
    httpd = server.serve(_runner(), operator, port=0,
                         assignments={"node_models": {"draft": "m"},
                                      "seat_models": {"risk": "m"}},
                         assignment_source=source)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        req = urllib.request.Request(f"http://127.0.0.1:{port}/config/nodes", method="GET")
        req.add_header("X-Operator-Token", operator.token)
        req.add_header("Host", f"127.0.0.1:{port}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            answered = json.loads(resp.read().decode("utf-8"))["source"]
    finally:
        httpd.shutdown()

    assert answered == source, (
        "a server that has served nothing yet answers the provenance it was started with; "
        f"got {answered}")


def test_cmd_serve_hands_over_the_provenance_it_computed():
    """**Computed and dropped is the defect this pins** (CHG-20260903-39).

    The route test above passes whatever `serve` is given, so it cannot see the original mistake:
    `cmd_serve` bound `assignment_source` from `store.resolve` twelve lines above the `serve` call
    and then did not pass it. Read from the source tree rather than by running the command, because
    reaching that call needs a plan, a store, a registry and a bound socket — and the claim is about
    one argument, not about any of those.
    """
    tree = ast.parse(pathlib.Path(cli.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_serve")

    bound = [t.elts[1].id for node in ast.walk(fn) if isinstance(node, ast.Assign)
             for t in node.targets
             if isinstance(t, ast.Tuple) and len(t.elts) == 2
             and all(isinstance(e, ast.Name) for e in t.elts)
             and isinstance(node.value, ast.Call)
             and getattr(node.value.func, "attr", None) == "resolve"]
    assert bound, "`cmd_serve` no longer binds a provenance map from `store.resolve`"

    handed = [kw.value.id for call in ast.walk(fn) if isinstance(call, ast.Call)
              and getattr(call.func, "attr", None) == "serve"
              for kw in call.keywords
              if kw.arg == "assignment_source" and isinstance(kw.value, ast.Name)]
    assert handed, "`cmd_serve` computes the provenance and does not hand it to `serve`"
    assert set(handed) <= set(bound), (
        f"`serve` is given {handed}, which is not what `store.resolve` returned ({bound})")


# --- an operator decision names the stop it answers (CHG-20260903-44) -------------------------

def test_a_refusal_that_names_a_different_gate_is_refused(live):
    """**The reproduction.** A refusal aimed at a stop nobody has been shown routed the run past
    `acceptance@high` — the only `halt_independent` cell in `GATES` — recorded as the operator's
    act. `approve` was hardened against this by CHG-20260903-34; `reject`, three methods below in
    the same class, was not."""
    call, _, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    stop = started["suspended"]
    assert stop["gate"] != "acceptance", "this test needs a stop that is not the one it names"

    code, body = call("POST", "/run/reject",
                      {"version": started["version"], "gate": "acceptance",
                       "node_id": "qa_accept", "reason": "planted"})

    assert code >= 400, (
        f"a refusal naming 'acceptance' was accepted while the run waited at {stop['gate']!r} — "
        f"it routes the run past the only halt_independent cell in GATES, as the operator's act")
    assert "waiting at" in json.dumps(body), body


def test_every_operator_decision_carries_the_run_it_answers(live):
    """`run_id=None` left the engine's staleness guards — `if rejection.run_id is not None and
    rejection.run_id != cfg.run_id` and the same for rulings — unreachable through the only human
    interface. `Approval`'s own docstring calls `None` *"the wrong one for an answer typed into a
    console after a stop"*."""
    call, runner, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    stop = started["suspended"]

    call("POST", "/run/gate", {"version": started["version"], "gate": stop["gate"],
                               "node_id": stop["node_id"]})
    assert runner.state.approvals, "no approval was recorded"
    assert runner.state.approvals[-1].run_id == stop.get("run_id"), (
        "an approval typed into the console does not say which run it answers, so the engine's "
        "staleness guard cannot refuse it")


def test_no_operator_decision_reaches_state_without_naming_its_stop():
    """**The rule** (CHG-20260903-44): over the class, not over three method names.

    The check lived in `approve` alone and its two siblings never got it. A fourth decision method
    would have been written the same way, so this asks the question of every method that appends an
    operator decision — including ones nobody has written yet.
    """
    import ast

    tree = ast.parse(pathlib.Path(server.__file__).read_text(encoding="utf-8"))
    runner = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.ClassDef) and n.name == "Runner")

    DECISIONS = {"approvals", "rejections", "rulings"}
    missing = []
    for fn in runner.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        appends = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and getattr(n.func, "attr", None) == "append"
                   and getattr(getattr(n.func, "value", None), "attr", None) in DECISIONS]
        if not appends:
            continue
        # **What it was given, not that it was named** (CHG-20260904-01, defect seat L-20). This
        # asked only whether the token `_answering` appeared and whether the token `run_id=` did,
        # so a fourth method calling `self._answering()` with no arguments and passing
        # `run_id=None` satisfied it while checking nothing — measured, and it passed.
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", None) == "_answering"]
        given = {kw.arg for call in calls for kw in call.keywords}
        params = {a.arg for a in fn.args.args} - {"self", "version"}
        asked = bool(calls) and given >= (params & {"gate", "node_id"})

        # And `run_id` must come from what the helper returned, not from any expression: the
        # literal `None` is what `Approval`'s docstring calls "the wrong one for an answer typed
        # into a console after a stop", and it is what `reject` and `rule` used to pass.
        stamped = []
        for call in appends:
            for inner in ast.walk(call):
                if not isinstance(inner, ast.Call):
                    continue
                for kw in inner.keywords:
                    if kw.arg != "run_id":
                        continue
                    stamped.append(any(isinstance(sub, ast.Call)
                                       and getattr(sub.func, "attr", None) == "get"
                                       for sub in ast.walk(kw.value)))
        carried = bool(stamped) and all(stamped)

        if not asked or not carried:
            missing.append(
                f"{fn.name}: "
                f"{'_answering is not given the values this method takes' if not asked else ''}"
                f"{' and ' if not asked and not carried else ''}"
                f"{'run_id is not read from the suspension' if not carried else ''}")

    assert missing == [], (
        f"these append an operator decision without naming the stop it answers or the run it "
        f"belongs to: {missing}")


def test_the_rule_looks_at_the_three_methods_that_exist():
    """**The floor.** Without it the rule passes by finding no decision methods at all, which is
    exactly how the defect it guards would come back."""
    import ast

    tree = ast.parse(pathlib.Path(server.__file__).read_text(encoding="utf-8"))
    runner = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.ClassDef) and n.name == "Runner")

    DECISIONS = {"approvals", "rejections", "rulings"}
    found = {fn.name for fn in runner.body if isinstance(fn, ast.FunctionDef)
             and any(isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "append"
                     and getattr(getattr(n.func, "value", None), "attr", None) in DECISIONS
                     for n in ast.walk(fn))}
    assert found == {"approve", "reject", "rule"}, (
        f"the rule above scans {sorted(found)}; if a decision method was added or renamed, this "
        f"floor is the place to say so rather than letting the rule quietly cover less")


# ── what the console shows of what governs the run (CHG-20260903-49) ───────────────────

#: A report field the console does not render, and **why**. Not an exemption list — an inventory.
#:
#: `test_every_key_the_server_sends_reaches_the_console` (CHG-20260903-29) watches the 19 keys
#: `RunState.snapshot()` builds. `RunReport().as_dict()` has 30 fields, and CHG-20260903-24 retired
#: `CHG-20260901-15` task 24 on the ground that the `-29` rule would catch the next one to go
#: unrendered. It cannot: a field that never enters the snapshot cannot fail a rule that iterates
#: the snapshot. The rule is honestly named — *the server sends* — and the citation was not.
#:
#: So the fifteen are written down instead. Every one of them is the record of **what governed the
#: run** rather than what it did, which is the shape worth seeing in one place.
NOT_ON_THE_CONSOLE = {
    # the grade a panel settled on
    "risk_proposed": "the per-model grades behind `risk_agreed`; the console shows neither yet",
    "risk_settled": "the grade the run was governed by — reaches `--json` and the terminal only",
    "risk_agreed": "whether a panel agreed it, as against a grade carried from the plan",
    # the class, and what it dissolved
    "change_class": "which class governed the run, as a sentence for a person",
    "class_authorised_by": "who declared it, as a name",
    "relaxations": "the runner's own relaxations — `--store-remote allow` and the like",
    "relaxations_by_class": "the gates a class dissolved, each named",
    "relaxation_authorisers": "who authorised each of those, per note",
    # what the run did
    "effects": "which effects applied and which were already met",
    "halts": "the permanent halts this run tripped",
    "panel_rounds": "how many laps a panel took before it settled",
    "resumed": "asks answered from the journal rather than re-asked",
    "single_model_panels": "panels that ran on one voice because that is all there was",
    # trust and the store
    "on_trust": "targets accepted because the operator vouched for the command",
    "store_errors": "writes to the conversation store that failed",
}


def _reaches_console(field, page):
    """True if the field's **content** reaches the console, under whatever key.

    **Content, not name.** `snapshot()` sends `report.halted_at` as `"at"` and `report.halt_reason`
    as `"reason"`, so a name-based check flags two fields that the console does render — which is
    how the seat's count of seventeen became fifteen when it was measured (CHG-20260903-49).
    """
    import ast

    if re.search(r"\b%s\b" % re.escape(field), page):
        return True
    source = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "snapshot")
    for mapping in ast.walk(fn):
        if not isinstance(mapping, ast.Dict):
            continue
        for key, value in zip(mapping.keys, mapping.values):
            reads = {a.attr for a in ast.walk(value) if isinstance(a, ast.Attribute)
                     and isinstance(a.value, ast.Name) and a.value.id == "report"}
            if field in reads and re.search(r"\b%s\b" % re.escape(key.value), page):
                return True
    return False


def test_every_report_field_is_rendered_or_written_down():
    """**The scope the `-29` rule does not cover, made visible rather than assumed.**

    A report field that reaches no console and nobody wrote down is the defect
    `CHG-20260901-16` was filed for — *"declared, written during the walk, and emitted by nothing"*
    — one surface further out. This does not build the fifteen views; it refuses a sixteenth field
    joining them in silence.
    """
    page = _console()
    fields = set(engine.RunReport().as_dict())

    unlisted = sorted(f for f in fields
                      if not _reaches_console(f, page) and f not in NOT_ON_THE_CONSOLE)
    assert unlisted == [], (
        f"these reach no console and no reason is written down for them: {unlisted}. Render them, "
        f"or add each to NOT_ON_THE_CONSOLE with what it is — an inventory a reader can argue "
        f"with, not a silence")

    stale = sorted(f for f in NOT_ON_THE_CONSOLE if f not in fields)
    assert stale == [], f"NOT_ON_THE_CONSOLE names fields the report no longer has: {stale}"

    rendered_but_listed = sorted(f for f in NOT_ON_THE_CONSOLE if _reaches_console(f, page))
    assert rendered_but_listed == [], (
        f"these are listed as absent and the console renders them: {rendered_but_listed}")


def test_the_inventory_is_fifteen_and_the_two_renamed_ones_are_not_in_it():
    """**The floor**, and the correction that produced this record's number.

    The conformance seat counted seventeen by field name. `halted_at` reaches the console as `at`
    and `halt_reason` as `reason`, so two of the seventeen are rendered — a name-based count of a
    thing that is renamed, which is the class of error this whole review round has been finding,
    inside one of the round's own findings.
    """
    page = _console()
    assert len(NOT_ON_THE_CONSOLE) == 15, (
        f"the inventory is {len(NOT_ON_THE_CONSOLE)} entries; if the console grew a view, delete "
        f"the entry rather than leaving it — the test above already refuses a listed-and-rendered "
        f"field, and this number is what a reader checks the record against")

    for renamed in ("halted_at", "halt_reason"):
        assert not re.search(r"\b%s\b" % re.escape(renamed), page), (
            f"{renamed} is now named directly in the page; the renaming this test exists to "
            f"describe is gone")
        assert _reaches_console(renamed, page), (
            f"{renamed} no longer reaches the console under its snapshot key — if that is "
            f"deliberate it belongs in NOT_ON_THE_CONSOLE")


def test_a_decision_that_names_nothing_is_refused_before_it_reaches_the_ledger(live):
    """**The empty-string road into an append-only ledger** (CHG-20260904-01, defect seat L-15).

    `do_POST` turns an absent field into `""` (`str(body.get("gate") or "")`), and `_answering`'s
    guards were written `if gate and …` — so an empty one short-circuited both and no check ran.
    The entry then reached a ledger with no removal route, and `walk`'s up-front check refused it
    on **every subsequent walk**:

        Approval(gate="")    approval for gate '' does not exist
        Rejection(gate="")   rejection names gate '', which does not exist
        Ruling(node_id="")   ruling names a node that is not in the flow

    Unrecoverable short of `POST /run` — CHG-20260903-23's L-25 arriving by a different road, into
    the helper CHG-20260903-44 extracted to stop it. The helper asked the question; the question
    answered nothing.
    """
    call, runner, _ = live
    _, started = call("POST", "/run", {"instruction": "do it", "version": 0})
    stop = started["suspended"]
    assert stop, "the run is not waiting, so there is no decision to leave empty"

    empty = [
        ("/run/gate", {"version": started["version"], "gate": "", "node_id": stop["node_id"]}),
        ("/run/reject", {"version": started["version"], "gate": "",
                         "node_id": stop["node_id"], "reason": "x"}),
        ("/run/decide", {"version": started["version"], "node_id": "", "branch": "yes"}),
    ]
    for route, payload in empty:
        code, said = call("POST", route, payload)
        assert code >= 400, f"{route} accepted a decision naming nothing: {said}"

    assert not runner.state.approvals, runner.state.approvals
    assert not runner.state.rejections, runner.state.rejections
    assert not runner.state.rulings, runner.state.rulings

    # And the run is still answerable, which is the property the ledger's append-only shape puts
    # at risk: one accepted empty entry would have made this 409 for the life of the run.
    code, _ = call("POST", "/run/gate", {"version": started["version"], "gate": stop["gate"],
                                         "node_id": stop["node_id"]})
    assert code == 200, "the run could not be answered after the empty decisions were refused"


# ── one question, one answer, in one rendered box (CHG-20260904-03) ───────────────────────────

def _intake_runner(sequence):
    """A runner whose intake seat reports `sequence[i]` missing on the i-th walk."""
    from test_flow import DECISIONS, SPEC

    aspect = {"now": sequence[0]}

    def factory(seat=None, model=None, **_):
        class Session(engine.Session):
            def ask(self, order):
                if order["node_id"] == "intake_review":
                    return {"missing": [aspect["now"]], "problems": []}
                return {"verdict": "pass"} if seat else {"ok": True}

            def close(self):
                pass
        return Session()

    def make_config(instructions, approvals, rulings, artifacts=(), rejections=(),
                    intake_history=()):
        return engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                                decisions=dict(DECISIONS), risk="low", undeclared="allow",
                                instructions=tuple(instructions), confirmed=tuple(approvals),
                                rulings=tuple(rulings), rejections=tuple(rejections),
                                intake_history=tuple(intake_history))

    runner = server.Runner(walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
                           make_config=make_config)
    for lap, missing in enumerate(sequence):
        aspect["now"] = missing
        version = runner.state.version
        if lap == 0:
            runner.start("do it", version)
        else:
            runner.instruct(version, "more")
        yield missing, runner.state.snapshot()


def test_the_console_shows_one_answer_to_how_many_times_it_has_been_asked():
    """**Two numbers in one box** (CHG-20260904-03, defect seat L-16).

    The panel's `<p>` renders `reason`, which `intake.stop_reason` writes **per aspect**. The row
    below it rendered `intake_asks`, which was `len(intake_history)` — every intake stop, whatever
    was missing. Measured, from the second aspect onward:

        missing        the <p> said     the counter said
        flow           asked once       1
        architecture   asked once       2      <-
        architecture   asked twice      3      <-

    CHG-20260903-42 gave the two engine-side readers one name; the console is the third reader and
    it was not swept. The claim asserted here is that the two agree, not that either is spelled a
    particular way.
    """
    words = {1: "asked once", 2: "asked twice"}
    for missing, snap in _intake_runner(["flow", "architecture", "architecture", "architecture"]):
        counted = (snap.get("intake_asks_by_aspect") or {}).get(missing)
        assert counted is not None, (
            f"the console has no per-aspect count for {missing!r}: "
            f"{snap.get('intake_asks_by_aspect')}")
        said = words.get(counted, f"asked {counted} times")
        assert said in str(snap.get("reason")), (
            f"the sentence and the counter disagree in one box: the counter says {counted} "
            f"({said!r}) and the sentence reads {snap.get('reason')!r}")


def test_the_count_is_the_tally_because_the_stop_is_already_recorded():
    """**The same question has two correct answers at two moments**, which is why one shared
    function would give the wrong one here.

    `intake.asks_including_this_one` is right during the walk — the engine checks before the stop
    is written. The snapshot is read *after* `_walk_once` appends it, so the ask in flight is
    already in the history and the correct count is the raw tally. Pinned so a later "tidy-up" that
    routes this through the shared name is caught.
    """
    from ai_sdlc_runner import intake as intake_mod

    history = [{"missing": ["flow"]}, {"missing": ["architecture"]},
               {"missing": ["architecture"]}]
    assert intake_mod.times_asked(history, "architecture") == 2
    assert intake_mod.asks_including_this_one(history, "architecture") == 3, (
        "the two differ by exactly the ask in flight, which is the whole point")

    # **The call, not the prose.** The first version asserted the name did not appear in
    # `inspect.getsource`, and failed on the comment that explains *why* it does not apply —
    # a rule flagging its own explanation, for the fourth time in two days (CHG-20260904-03).
    import ast

    tree = ast.parse(inspect.getsource(server).lstrip())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "snapshot")
    called = {getattr(n.func, "attr", None) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "times_asked" in called, "the snapshot no longer counts the recorded stops"
    assert "asks_including_this_one" not in called, (
        "the snapshot counts the ask in flight twice — it is already in the history by the time "
        "this is read")


def _intake_only_runner(tmp_path=None):
    """A runner whose intake seat always reports the same aspect missing."""
    from test_flow import DECISIONS, SPEC

    def factory(seat=None, model=None, **_):
        class Session(engine.Session):
            def ask(self, order):
                if order["node_id"] == "intake_review":
                    return {"missing": ["architecture"], "problems": []}
                return {"verdict": "pass"} if seat else {"ok": True}

            def close(self):
                pass
        return Session()

    def make_config(instructions, approvals, rulings, artifacts=(), rejections=(),
                    intake_history=()):
        return engine.RunConfig(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                                decisions=dict(DECISIONS), risk="low", undeclared="allow",
                                instructions=tuple(instructions), confirmed=tuple(approvals),
                                rulings=tuple(rulings), rejections=tuple(rejections),
                                intake_history=tuple(intake_history))

    store = attach_mod.Store(tmp_path) if tmp_path is not None else None
    return server.Runner(walk=lambda cfg: engine.walk(cfg, factory, enabled=True),
                         make_config=make_config, store=store)


# ── a walk is not an ask (CHG-20260904-05) ────────────────────────────────────────────────────

def test_a_walk_that_nobody_asked_for_is_not_counted_as_an_ask(tmp_path):
    """**`attach` is the one path that walks without anybody being asked** (defect seat L-25).

    Measured: `start`, `instruct` and `attach` can walk from an incomplete stop; `approve`,
    `reject` and `rule` are refused there by `_require_suspension` (CHG-20260903-23). So the count
    moved on attachments, and a third one crossed `intake.ASK_LIMIT` — at which point
    `needs_options` leaves the ask-again path and the runner offers options to somebody nobody
    asked again. A **behaviour** change, not a label.
    """
    runner = _intake_only_runner(tmp_path)
    runner.start("do it", runner.state.version)
    assert len(runner.state.intake_history) == 1, "the first stop is an ask"

    before = len(runner.state.intake_history)
    runner.attach(runner.state.version, "notes.md", b"an unrelated file")
    assert len(runner.state.intake_history) == before, (
        f"attaching a file was counted as asking the operator for the requirement again: "
        f"{runner.state.intake_history}")

    runner.instruct(runner.state.version, "and the architecture is three services")
    assert len(runner.state.intake_history) == before + 1, (
        "a new instruction that still leaves the aspect missing is an ask, and was not counted")


def test_the_runner_does_not_give_up_on_somebody_it_never_asked_again(tmp_path):
    """The consequence, at the limit: `ASK_LIMIT` attachments used to reach the options path."""
    from ai_sdlc_runner import intake as intake_mod

    runner = _intake_only_runner(tmp_path)
    runner.start("do it", runner.state.version)
    for n in range(intake_mod.ASK_LIMIT + 1):
        runner.attach(runner.state.version, "f%d.md" % n, b"unrelated")

    assert not intake_mod.needs_options(runner.state.intake_history, "architecture"), (
        f"the runner stopped asking after {len(runner.state.intake_history)} recorded asks, "
        f"having asked once and been answered by nobody")


def test_a_gate_decision_cannot_walk_from_an_incomplete_stop():
    """The floor for the finding above: the other three methods are already refused there, so the
    fix does not need to cover them and the comment must not claim it does."""
    runner = _intake_only_runner()
    runner.start("do it", runner.state.version)
    for call in (lambda: runner.rule(runner.state.version, "intake_review", "yes"),
                 lambda: runner.approve(runner.state.version, "plan_confirmed", "pm_confirm"),
                 lambda: runner.reject(runner.state.version, "plan_confirmed", "pm_confirm", "no")):
        with pytest.raises(server.ServerError, match="not complete"):
            call()
