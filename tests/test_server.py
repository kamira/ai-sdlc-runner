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
import json
import threading
import urllib.error
import urllib.request

import pytest

from ai_sdlc_runner import engine, graph, policy, server
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

    def call(method, path, body=None, token=None, host=None, origin=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None)
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
