"""The console draws the flow and a click on a node opens its settings (CHG-20261005-03).

Three kinds of test, because there is no browser here:

* **route tests** over a real socket — `/flow` carries capabilities, `GET /config/seats`,
  `POST /config/dimensions` and its refusals;
* **static tests** over `index.html` — nothing remote, no node id typed into the script, the panel
  posts only to routes the server has;
* **harness tests** — `tests/console_harness.js` loads the page's own script under `node` against a
  fake DOM and the real server. Skipped, loudly, when `node` is absent. These are the ones that
  exercise the wiring: keyboard → panel → save → HTTP → server → refusal text on screen.

Each test names, in its docstring, the wire it fails when cut. The ones marked *cut* were verified
by cutting it, and the report for the change says which.
"""
import ast
import inspect
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from ai_sdlc_runner import cli, engine, graph, policy, server, settings, store  # noqa: E402
from test_server import _without_comments  # noqa: E402

PAGE = ROOT / "src" / "ai_sdlc_runner" / "console" / "index.html"
HARNESS = ROOT / "tests" / "console_harness.js"
_KNOWN_NODE = pathlib.Path("/opt/node22/bin/node")
NODE = shutil.which("node") or (str(_KNOWN_NODE) if _KNOWN_NODE.exists() else None)
needs_node = pytest.mark.skipif(
    NODE is None, reason="`node` is not on PATH (looked at /opt/node22/bin/node too), so the "
                         "page's JavaScript cannot be run here; the static and route tests still do")

OPUS = {"id": "opus", "vendor": "a", "name": "o", "transport": "cli", "command": ["claude", "-p"],
        "tier": "high", "effort_argv": ["--effort", "{effort}"]}
LOCAL = {"id": "local", "vendor": "b", "name": "l", "transport": "cli", "command": ["llama"],
         "tier": "low"}


def _code():
    return _without_comments(PAGE.read_text(encoding="utf-8"))


class Console:
    """A real server with a store, a registry of two models and a settings file."""

    def __init__(self, tmp_path, plan=None):
        self.settings_path = tmp_path / "settings.json"
        self.db = store.connect(tmp_path / "config.sqlite")
        self.operator = server.Operator.mint(tmp_path)
        runner = self.runner = server.Runner(walk=lambda cfg: engine.RunReport(),
                                             make_config=lambda *a, **k: None)
        # A plan's assignments, as `cmd_serve` hands them over: merged, and with their provenance.
        merged, source = store.resolve(plan or {}, {})
        self.httpd = server.serve(runner, self.operator, port=0, db=self.db,
                                  settings_path=str(self.settings_path),
                                  assignments=merged, plan_assignments=plan or {},
                                  assignment_source=source)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        for model in (OPUS, LOCAL):
            assert self.post("/models", {"model": model})[0] == 200

    def call(self, path, body=None):
        request = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode() if body is not None else None,
            method="POST" if body is not None else "GET")
        request.add_header("X-Operator-Token", self.operator.token)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def post(self, path, body):
        _, state = self.call("/run")
        return self.call(path, {**body, "version": state["version"]})

    def harness(self, scenario, **args):
        done = subprocess.run(
            [NODE, str(HARNESS), str(PAGE), self.base, self.operator.token, scenario,
             json.dumps(args)], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    def close(self):
        self.httpd.shutdown()
        self.db.close()


@pytest.fixture
def console(tmp_path):
    made = Console(tmp_path)
    yield made
    made.close()


# ── /flow carries what the panel shows ────────────────────────────────────────────────────────

def test_flow_carries_each_nodes_capabilities_from_policy(console):
    """*cut*: drop `capabilities` from the `/flow` branch in `server.py` and this fails."""
    _, body = console.call("/flow")
    assert [n["id"] for n in body["nodes"]] == [n.id for n in graph.NODES]
    for sent in body["nodes"]:
        want = policy.capabilities(sent["role"]) if sent["role"] in policy.BY_ROLE else None
        assert sent["capabilities"] == want, sent["id"]
    assert any(n["capabilities"] is None for n in body["nodes"]), "a roleless node must say null"
    assert any(n["capabilities"] for n in body["nodes"])


# ── the review dimensions route ───────────────────────────────────────────────────────────────

def test_the_seats_route_lists_every_seat_and_what_is_chosen(console):
    code, out = console.call("/config/seats")
    assert code == 200
    assert [s["name"] for s in out["seats"]] == [s.name for s in policy.SEATS]
    assert len(out["seats"]) == 15
    assert out["review_dimensions"] is None and out["floor"] == policy.SEAT_FLOOR
    # CHG-20261005-02: the flag is `opt_in` (the old `enabled_by_default`, inverted), the veto seat
    # is marked, and the cap on a seat count is sent.
    assert all("enabled_by_default" not in s for s in out["seats"])
    assert [s["name"] for s in out["seats"] if s["opt_in"]] == [
        s.name for s in policy.SEATS if s.opt_in]
    assert [s["name"] for s in out["seats"] if s["veto"]] == ["conformance"]
    assert all(s["question"] for s in out["seats"])
    assert out["max_seat_count"] == policy.MAX_SEAT_COUNT == 12


def test_choosing_dimensions_is_saved_in_order_and_read_back(console):
    """*cut*: make `_set_dimensions` skip `settings.save` and the file assertion fails."""
    chosen = ["security", "conformance", "docs"]
    code, out = console.post("/config/dimensions", {"review_dimensions": chosen})
    assert code == 200, out
    assert out["review_dimensions"] == chosen
    assert settings.load(str(console.settings_path)).review_dimensions == tuple(chosen)
    assert console.call("/config/seats")[1]["review_dimensions"] == chosen

    code, out = console.post("/config/dimensions", {"review_dimensions": None})
    assert code == 200 and out["review_dimensions"] is None
    assert settings.load(str(console.settings_path)).review_dimensions is None


@pytest.mark.parametrize("bad, said", [
    (["conformance", "nobody", "risk"], "no seat"),
    (["defect", "defect", "risk"], "named more than once"),
    (["defect", "risk"], "below the floor of 3"),
    ([], "at least one seat"),
    # CHG-20261005-02 round 1: a named list that leaves out the veto seat is refused, floor met.
    (["defect", "risk", "security"], "leaves out conformance, the veto seat"),
])
def test_dimensions_refusals_are_the_settings_ones(console, bad, said):
    """The same refusals `runner settings` gives, because the route saves through `settings.save`.

    *cut*: have `_set_dimensions` write the file itself (bypass `settings.save`) and the floor and
    unknown-seat cases are accepted instead of refused.
    """
    code, out = console.post("/config/dimensions", {"review_dimensions": bad})
    assert code == 409 and said in out["error"], out
    # And the CLI's own wording is the one shown: same function, same text.
    with pytest.raises(settings.SettingsError) as raised:
        settings.save(settings.Settings(review_dimensions=tuple(bad)),
                      str(console.settings_path.with_name("elsewhere.json")))
    assert str(raised.value).split(": ", 2)[-1] in out["error"]
    assert not console.settings_path.exists(), "a refused choice must not be written"


def test_the_floor_can_be_crossed_only_with_high_risk_mode(console):
    console.settings_path.write_text(json.dumps({"high_risk_mode": True}), encoding="utf-8")
    code, out = console.post("/config/dimensions", {"review_dimensions": ["defect", "risk"]})
    assert code == 200 and out["review_dimensions"] == ["defect", "risk"], out


def test_without_the_veto_seat_is_allowed_only_in_high_risk_mode(console):
    """The veto seat is required unless high-risk mode is on (CHG-20261005-02, round 1).

    Would fail if `_set_dimensions` skipped `settings.save` (the first answer would be 200).
    """
    chosen = ["defect", "risk", "security"]
    code, out = console.post("/config/dimensions", {"review_dimensions": chosen})
    assert code == 409 and "veto seat" in out["error"], out
    console.settings_path.write_text(json.dumps({"high_risk_mode": True}), encoding="utf-8")
    code, out = console.post("/config/dimensions", {"review_dimensions": chosen})
    assert code == 200 and out["review_dimensions"] == chosen, out


def test_opt_in_seats_open_only_when_named(console):
    opt_in = [s.name for s in policy.SEATS if s.opt_in]
    chosen = ["conformance", "defect", "risk", *opt_in]
    code, out = console.post("/config/dimensions", {"review_dimensions": chosen})
    assert code == 200 and out["review_dimensions"] == chosen, out
    # And left out, they stay closed: the list the file holds is exactly the one saved.
    code, out = console.post("/config/dimensions", {"review_dimensions": chosen[:3]})
    assert code == 200 and out["review_dimensions"] == chosen[:3]
    assert settings.load(str(console.settings_path)).review_dimensions == tuple(chosen[:3])


def test_seat_models_are_distinct_registered_ids_and_the_refusal_is_the_servers(console):
    """A duplicate and an unknown id are refused by the store (409) and nothing is written."""
    code, out = console.post("/config/seats", {"seat": "risk", "model_id": ["opus", "opus"]})
    assert code == 409 and "listed more than once" in out["error"], out
    code, out = console.post("/config/seats", {"seat": "risk", "model_id": ["opus", "missing"]})
    assert code == 409 and "'missing'" in out["error"], out
    assert console.call("/config/nodes")[1]["seat_models"] == {}
    code, _ = console.post("/config/seats", {"seat": "risk", "model_id": ["opus", "local"]})
    assert code == 200
    assert console.call("/config/nodes")[1]["seat_models"] == {"risk": ["opus", "local"]}


def test_dimensions_refuses_what_is_not_a_list_and_a_stale_version(console):
    assert console.post("/config/dimensions", {"review_dimensions": "defect"})[0] == 409
    assert console.post("/config/dimensions", {})[0] == 409
    code, out = console.call("/config/dimensions", {"review_dimensions": None, "version": 999})
    assert code == 409 and out["error"]


def test_a_server_with_no_settings_file_says_so(tmp_path):
    operator = server.Operator.mint(tmp_path)
    runner = server.Runner(walk=lambda cfg: engine.RunReport(),
                           make_config=lambda *a, **k: None)
    db = store.connect(tmp_path / "c.sqlite")
    httpd = server.serve(runner, operator, port=0, db=db)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/config/dimensions", method="POST",
            data=json.dumps({"review_dimensions": None, "version": 0}).encode())
        request.add_header("X-Operator-Token", operator.token)
        with pytest.raises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=10)
        assert raised.value.code == 409
        assert "settings file" in json.loads(raised.value.read())["error"]
    finally:
        httpd.shutdown()
        db.close()


def test_serve_hands_the_settings_path_over_and_each_walk_rereads_it():
    """A saved choice has to reach the **next run**, not only the screen.

    `make_config` used to close over `saved`, read once at startup, so a `review_dimensions` saved
    from the console would have changed the display and not the walk. *cut*: change `live` back to
    `saved` in `make_config` and this fails.
    """
    tree = ast.parse(inspect.getsource(cli.cmd_serve))
    serve_calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call)
                   and isinstance(c.func, ast.Attribute) and c.func.attr == "serve"]
    assert any(k.arg == "settings_path" and ast.unparse(k.value) == "args.settings"
               for c in serve_calls for k in c.keywords), (
        "`cmd_serve` does not give `server.serve` the settings path, so the route has no file")

    make_config = next(f for f in ast.walk(tree)
                       if isinstance(f, ast.FunctionDef) and f.name == "make_config")
    loads = [a for a in ast.walk(make_config) if isinstance(a, ast.Assign)
             and isinstance(a.value, ast.Call) and isinstance(a.value.func, ast.Attribute)
             and a.value.func.attr == "load"]
    assert loads, "`make_config` no longer re-reads the settings file per walk"
    fresh = {t.id for a in loads for t in a.targets if isinstance(t, ast.Name)}
    config_call = next(c for c in ast.walk(make_config) if isinstance(c, ast.Call)
                       and isinstance(c.func, ast.Attribute) and c.func.attr == "RunConfig")
    given = {k.arg: k.value for k in config_call.keywords}
    for field in ("review_dimensions", "review_seats", "high_risk_mode"):
        value = given[field]
        assert isinstance(value, ast.Attribute) and value.value.id in fresh, (
            f"RunConfig.{field} is not read from the settings `make_config` just loaded")


# ── static: the page ──────────────────────────────────────────────────────────────────────────

def test_no_node_id_is_typed_into_the_script():
    """The drawing reads ids from `/flow`. *cut*: put `["intake"]` back in the layout and it fails."""
    code = _code()
    typed = [n.id for n in graph.NODES if re.search(r"""["']%s["']""" % re.escape(n.id), code)]
    assert typed == [], f"the script names these nodes by id, so it draws a copy of the graph: {typed}"
    assert 'api("GET", "/flow")' in code and "layout(flow," in code
    assert "flow = f.nodes" in code


def test_the_page_references_nothing_remote():
    """No CDN, no font, no script, no image, nothing that is not this server. *cut*: add a
    `<link href="https://…">` or a `url(//…)` and it fails."""
    page = PAGE.read_text(encoding="utf-8")
    code = _code()
    for tag in ("<link", "<img", "<iframe", "<object", "<embed", "<video", "<audio", "<source"):
        assert tag not in page.lower(), f"the page has a {tag} element"
    assert not re.search(r"<script[^>]*\ssrc\s*=", page, re.I), "the page loads a script"
    for banned in ("@import", "url(", "import(", "importScripts", "WebSocket", "sendBeacon",
                   "XMLHttpRequest"):
        assert banned not in page, f"the page uses {banned}"
    # The only http:// text allowed: the SVG namespace (an identifier, never fetched), and the
    # error message's "http://" + location.host, which prints the address the operator should open.
    urls = re.findall(r"https?://[^\s\"'<>)]*", page)
    assert sorted(set(urls)) == ["http://", "http://www.w3.org/2000/svg"], urls
    assert "//" not in re.sub(r"https?://[^\s\"'<>)]*", "", code).replace("\\/", ""), (
        "a protocol-relative URL or a stray `//` in the script")
    # Every request the page makes goes through `api()`, with a path on this server.
    paths = re.findall(r'(?:api\("(?:GET|POST)",\s*|save\()\s*"([^"]*)"', code)
    assert paths and all(p.startswith("/") and not p.startswith("//") for p in paths), paths
    fetches = re.findall(r"\bfetch\(([^,)]*)", code)
    assert fetches == ["path"], f"fetch is called with something other than api()'s path: {fetches}"
    assert 'new EventSource("/run/events?' in code


def test_the_panel_posts_only_to_routes_the_server_has():
    """*cut*: change `"/config/dimensions"` in the page to a route that does not exist."""
    code = _code()
    posted = set(re.findall(r'(?:save|api)\((?:"POST",\s*)?"(/[a-z/]+)"', code))
    assert {"/config/nodes", "/config/seats", "/config/dimensions"} <= posted, posted
    source = inspect.getsource(server)
    for route in posted:
        assert f'self.path == "{route}"' in source, f"{route} is posted by the panel; no handler"
    assert 'api("GET", "/config/seats")' in code


def test_nodes_are_focusable_named_and_keyboard_operable():
    """*cut*: remove `tabindex`, the aria-label, the Enter/Space handler or the Escape one."""
    code = _code()
    for token in ("tabindex", '"aria-label"', '"Enter"', '" "', '"Escape"', "role: \"button\"",
                  "describeNode(n)"):
        assert token in code, f"the page lost {token}"
    assert re.search(r'return n\.id \+ " — " \+ n\.label', code), (
        "a node's accessible name must carry its id and its label")


def test_the_model_editor_reads_the_modes_from_the_server_and_the_seat_editor_uses_graph_modes():
    code = _code()
    assert "assign.assignable" in code
    for mode in ("seat_panel", "survey"):
        assert mode in graph.MODES and f'"{mode}"' in code
    assert (graph.SEAT_PANEL, graph.SURVEY) == ("seat_panel", "survey")


# ── harness: the page's own JavaScript ────────────────────────────────────────────────────────

def _flow_nodes():
    return [{"id": n.id, "kind": n.kind, "label": n.label, "role": n.role, "gate": n.gate,
             "mode": n.mode, "branches": dict(n.branches), "next": n.next,
             "permanent": n.permanent} for n in graph.NODES]


@needs_node
def test_the_layout_places_every_node_and_every_edge_of_the_real_flow(console):
    """Runs the extracted `layout` on the payload `GET /flow` really sends.

    *cut*: skip a column in the placement loop, or drop an edge push, and this fails.
    """
    _, payload = console.call("/flow")
    synthetic_cycle = [
        {"id": "a", "branches": {}, "next": "b"}, {"id": "b", "branches": {"again": "a"},
                                                   "next": "c"},
        {"id": "c", "branches": {}, "next": None}, {"id": "orphan", "branches": {}, "next": "c"}]
    real, cyc = console.harness("layout", sets=[payload["nodes"], synthetic_cycle])

    ids = [n.id for n in graph.NODES]
    assert sorted(real["pos"]) == sorted(ids), "a node was not placed"
    wanted = sorted(((n.id, t, label) for n in graph.NODES
                     for label, t in list(n.branches.items())
                     + ([(None, n.next)] if n.next else [])), key=str)
    got = sorted(((e["from"], e["to"], e["label"]) for e in real["edges"]), key=str)
    assert got == wanted, "an edge was not drawn, or one was invented"
    for e in real["edges"]:
        assert e["d"] and "NaN" not in e["d"] and math.isfinite(e["lx"]) and math.isfinite(e["ly"])
    boxes = list(real["pos"].values())
    for p in boxes:
        assert all(math.isfinite(p[k]) and p[k] >= 0 for k in ("x", "y"))
        assert p["x"] + 132 <= real["w"] and p["y"] + 34 <= real["h"], "a node is off the canvas"
    assert len({(p["x"], p["y"]) for p in boxes}) == len(boxes), "two nodes share a place"
    for e in real["edges"]:
        if not e["back"]:
            assert real["pos"][e["to"]]["layer"] > real["pos"][e["from"]]["layer"], (
                f"{e['from']} -> {e['to']} does not run top to bottom")
            assert real["pos"][e["to"]]["y"] > real["pos"][e["from"]]["y"]
    assert any(e["back"] for e in real["edges"]), "the flow has loops and none was found"

    assert sorted(cyc["pos"]) == ["a", "b", "c", "orphan"], "an unreached node must still be placed"
    assert [e["back"] for e in cyc["edges"] if e["label"] == "again"] == [True]
    assert cyc["pos"]["c"]["layer"] == 2 and cyc["pos"]["orphan"]["layer"] == 0
    assert cyc["pos"]["c"]["y"] > cyc["pos"]["b"]["y"] > cyc["pos"]["a"]["y"]


@needs_node
def test_the_flow_fits_its_column_and_every_edge_ends_on_its_two_nodes(console):
    """*cut*: lay layers out as columns again, or end a back edge anywhere but on its nodes."""
    _, payload = console.call("/flow")
    narrow, wide = console.harness("layout", sets=[payload["nodes"], payload["nodes"]],
                                   widths=[None, 1416])
    assert narrow["w"] <= 480, f"the flow is {narrow['w']}px wide, the column gives it ~465"
    assert wide["w"] <= 1416 and wide["w"] > narrow["w"] and wide["h"] < narrow["h"]
    for L in (narrow, wide):
        for e in L["edges"]:
            nums = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", e["d"])]
            start, end = (nums[0], nums[1]), (nums[-2], nums[-1])
            for (x, y), who in ((start, e["from"]), (end, e["to"])):
                p = L["pos"][who]
                on_box = (p["x"] <= x <= p["x"] + 132 and p["y"] <= y <= p["y"] + 34
                          and (y in (p["y"], p["y"] + 34) or x in (p["x"], p["x"] + 132)))
                assert on_box, f"{e['from']} -> {e['to']} ({e['label']}) misses {who} at {x},{y}"
        assert any(e["back"] for e in L["edges"])


@needs_node
def test_expand_is_a_pressed_button_and_opening_a_panel_puts_the_flow_back(console):
    """*cut*: drop `aria-pressed`, or leave the page wide when a panel opens over the main column."""
    out = console.harness("expand")
    assert out["before"] == {"cls": "", "pressed": "false"}
    assert out["expanded"] == {"cls": "wide", "pressed": "true"}
    assert out["afterOpen"] == {"cls": "", "pressed": "false"}
    assert out["afterTwo"] == {"cls": "", "pressed": "false"}


@needs_node
def test_every_node_is_a_focusable_named_button_and_the_keys_open_and_close_the_panel(console):
    """*cut*: remove the `Enter`/`" "` branch, the click listener or the document Escape handler."""
    out = console.harness("keyboard", index=3)
    assert [n["id"] for n in out["nodes"]] == [n.id for n in graph.NODES]
    for n in out["nodes"]:
        assert n["tabindex"] == "0"
        node = graph.BY_ID[n["id"]]
        assert n["label"].startswith(f"{node.id} — {node.label}"), n
    assert out["afterTab"] is None, "an ordinary key must not open anything"
    assert out["afterEnter"] == out["target"] and out["panelShown"]
    assert out["afterEscape"] is None and out["panelHiddenAfterEscape"] is True
    assert out["focusAfterEscape"] == out["target"], "Escape must return focus to the opener"
    assert out["afterSpace"] == out["nodes"][1]["id"]
    assert out["afterClick"] == out["nodes"][2]["id"]


def _first(mode_test, role=True):
    return next(n for n in graph.NODES if mode_test(n.mode) and (n.role in policy.BY_ROLE) == role)


@needs_node
def test_the_panel_shows_role_mode_gate_and_capabilities_and_edits_models_only_where_they_apply(
        console):
    """*cut*: render the model editor for every mode, or drop the capabilities line."""
    modelled = _first(lambda m: m in store.MODES_THAT_USE_MODELS)
    gated = next(n for n in graph.NODES if n.gate and n.mode in store.MODES_THAT_USE_MODELS)
    runner_node = next(n for n in graph.NODES if n.mode == graph.RUNNER and n.role is None)
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    survey = next(n for n in graph.NODES if n.mode == graph.SURVEY)
    follows = next((n for n in graph.NODES if n.mode == graph.FOLLOWS), None)
    ids = [modelled.id, gated.id, runner_node.id, seat_node.id, survey.id]
    if follows:
        ids.append(follows.id)
    panels = console.harness("panel", ids=ids)["panels"]

    for n in (modelled, gated):
        text = panels[n.id]["text"]
        caps = policy.capabilities(n.role)
        assert f"role {n.role}" in text and f"mode {n.mode}" in text
        assert ("spawn: " + ("yes" if caps["can_spawn"] else "no")) in text
        assert ("write: " + ("yes" if caps["can_write"] else "no")) in text
        assert ("execute: " + ("yes" if caps["can_execute"] else "no")) in text
        assert f"save the models for {n.id}" in panels[n.id]["buttons"]
        assert "tier high" in text and "tier low" in text and "--effort {effort}" in text
    assert f"gate {gated.gate}" in panels[gated.id]["text"]
    assert "gate none" in panels[modelled.id]["text"] or modelled.gate

    for n in [runner_node] + ([follows] if follows else []):
        assert f"save the models for {n.id}" not in panels[n.id]["buttons"], (
            f"a {n.mode} node got a model editor; the server would refuse what it posts")
        assert "takes no model list" in panels[n.id]["text"]
    assert "no role, so nothing is carried" in panels[runner_node.id]["text"]

    for n in (seat_node, survey):
        text = panels[n.id]["text"]
        assert "review dimensions" in text and "models on each seat" in text
        assert "save the review dimensions" in panels[n.id]["buttons"]
        assert all(s.name in text for s in policy.SEATS)
        assert f"save the models for {n.id}" not in panels[n.id]["buttons"]
    assert "governance and are not editable" in panels[modelled.id]["text"]


@needs_node
def test_saving_models_from_the_panel_reaches_the_store(console):
    """The whole wire: tick in the panel -> `POST /config/nodes` -> store -> `GET /config/nodes`.

    *cut*: change the `save(...)` route in the node editor, or its `models` body, and this fails.
    """
    node = _first(lambda m: m == graph.POOL)
    out = console.harness("save_models", node=node.id, tick=["opus", "local"])
    assert out["error"] == "" and len(out["sent"]) == 1
    assert out["sent"][0]["path"] == "/config/nodes"
    assert out["sent"][0]["body"]["node_id"] == node.id
    assert out["sent"][0]["body"]["models"] == ["opus", "local"]
    assert console.call("/config/nodes")[1]["node_models"] == {node.id: ["opus", "local"]}


@needs_node
def test_a_refused_model_assignment_is_shown_not_swallowed(console):
    """A node that cannot carry models, forced past the page's own check, is refused by the server
    and the server's sentence is what appears on screen.

    *cut*: replace `panelError(e.message)` in `save()` with a no-op and the text is empty.
    """
    runner_node = next(n for n in graph.NODES if n.mode == graph.RUNNER)
    code, refusal = console.post("/config/nodes", {"node_id": runner_node.id, "models": ["opus"]})
    assert code == 409
    # The page will not offer that editor, so drive `save()` itself with the refused body.
    shown = console.harness("drive_save", node=runner_node.id, path="/config/nodes",
                            body={"node_id": runner_node.id, "models": ["opus"]})["error"]
    assert shown == refusal["error"] and "does nothing with a model list" in shown


@needs_node
def test_dimensions_are_chosen_and_ordered_in_the_panel_and_saved(console):
    """Move `defect` ahead of `conformance`, save: the file holds that order.

    *cut*: drop the order handling (`order[i] = order[j]`) or the POST and this fails.
    """
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    out = console.harness("save_dimensions", node=seat_node.id, steps=[
        {"move": "move defect earlier"}, {"tick": "security"}])
    assert out["error"] == "" and out["sent"][0]["path"] == "/config/dimensions"
    assert out["sent"][0]["body"]["review_dimensions"] == [
        "defect", "conformance", "risk", "security"]
    assert settings.load(str(console.settings_path)).review_dimensions == (
        "defect", "conformance", "risk", "security")


@needs_node
def test_a_refused_dimension_choice_shows_the_servers_words_and_writes_nothing(console):
    """*cut*: make `_set_dimensions` skip the floor (bypass `settings.save`) and nothing is refused;
    drop `panelError(e.message)` and the screen says nothing."""
    survey = next(n for n in graph.NODES if n.mode == graph.SURVEY)
    out = console.harness("save_dimensions", node=survey.id, steps=[
        {"untick": "risk"}, {"untick": "defect"}])
    assert "below the floor of 3" in out["error"], out
    assert "Enable high-risk mode" in out["error"]
    assert not console.settings_path.exists()
    out = console.harness("save_dimensions", node=survey.id, steps=[{"untick": "risk"}],
                          press="clear (back to the default prefix)")
    assert out["error"] == "" and out["sent"][0]["body"]["review_dimensions"] is None


@needs_node
def test_the_chooser_marks_the_veto_seat_and_the_opt_in_seats_and_shows_each_question(console):
    """Would fail if the page read `enabled_by_default` again, or dropped
    a question or the veto wording.
    """
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    text = console.harness("panel", ids=[seat_node.id])["panels"][seat_node.id]["text"]
    assert "veto seat, required unless high-risk mode is on" in text
    assert text.count("opt-in, open only when ticked") == sum(s.opt_in for s in policy.SEATS)
    assert all(s.question in text for s in policy.SEATS)


@needs_node
def test_a_default_choice_opens_no_opt_in_seat(console):
    """Saving the untouched chooser sends the first three seats that are not opt-in."""
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    out = console.harness("save_dimensions", node=seat_node.id, steps=[])
    assert out["error"] == ""
    assert out["sent"][0]["body"]["review_dimensions"] == [
        s.name for s in policy.PREFIX_SEATS][:policy.SEAT_FLOOR]


@needs_node
def test_dropping_the_veto_seat_shows_the_servers_refusal_and_writes_nothing(console):
    """Would fail if `panelError(e.message)` were dropped or `_set_dimensions` skipped the veto
    rule."""
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    out = console.harness("save_dimensions", node=seat_node.id, steps=[
        {"untick": "conformance"}, {"tick": "security"}])
    assert "leaves out conformance, the veto seat" in out["error"], out
    assert "enable high-risk mode" in out["error"]
    assert not console.settings_path.exists()


@needs_node
def test_a_duplicate_or_unknown_seat_model_shows_the_servers_words(console):
    """Forced past the page's checkboxes, which cannot tick one model twice."""
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    for ids, said in ((["opus", "opus"], "listed more than once"), (["nobody"], "'nobody'")):
        body = {"seat": "risk", "model_id": ids}
        shown = console.harness("drive_save", node=seat_node.id, path="/config/seats",
                                body=body)["error"]
        code, refusal = console.post("/config/seats", body)
        assert code == 409 and shown == refusal["error"] and said in shown, shown
    assert console.call("/config/nodes")[1]["seat_models"] == {}


@needs_node
def test_models_on_a_seat_are_saved_per_seat_and_in_order(console):
    seat_node = next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)
    nth = [s.name for s in policy.SEATS].index("risk")
    out = console.harness("save_seat_models", node=seat_node.id, seat="risk", nth=nth,
                          tick=["local", "opus"])
    assert out["error"] == "" and out["sent"][0]["path"] == "/config/seats"
    assert out["sent"][0]["body"] == {"seat": "risk", "model_id": ["local", "opus"],
                                      "version": out["sent"][0]["body"]["version"]}
    assert console.call("/config/nodes")[1]["seat_models"] == {"risk": ["local", "opus"]}


@needs_node
def test_the_models_list_shows_tier_effort_and_the_nodes_and_seats_each_model_answers(console):
    """*cut*: drop the tier row, the role in the node row, or the seat row from `drawModels`."""
    node = _first(lambda m: m == graph.POOL)
    assert console.post("/config/nodes", {"node_id": node.id, "models": ["opus"]})[0] == 200
    assert console.post("/config/seats", {"seat": "defect", "model_id": ["opus"]})[0] == 200
    models = console.harness("models")["models"]
    assert models.index("local") < models.index("opus"), "the list is sorted by id"
    opus = models[models.index("opus"):]
    assert "tier high" in opus and "--effort {effort}" in opus
    assert f"{node.id} ({node.mode}, {node.role})" in opus
    assert "defect (review seat)" in opus
    local = models[models.index("local"):models.index("opus")]
    assert "tier low" in local and "no effort control" in local
    assert "nothing dispatches to it" in local, "an unused model must say so"


# ── review round 1 (CHG-20261005-03) ──────────────────────────────────────────────────────────

def _seat_node():
    return next(n for n in graph.NODES if n.mode == graph.SEAT_PANEL)


def _seat_index(name):
    return [s.name for s in policy.SEATS].index(name)


@needs_node
def test_saving_one_section_keeps_the_unsaved_edits_in_the_others(console):
    """Edit two seats and the dimension list, save one seat: the others still hold their edit, and
    saving the second then succeeds (its version advanced with the first save).

    *cut*: make `save()` redraw the whole panel (call `renderPanel()` after it) and the second seat,
    and the unticked `risk`, snap back to what is stored.
    """
    out = console.harness("two_sections", node=_seat_node().id, untick=["risk"], seats=[
        {"seat": "risk", "nth": _seat_index("risk"), "model": "local"},
        {"seat": "defect", "nth": _seat_index("defect"), "model": "opus"}])
    assert out["status"].startswith("Saved: the models on risk") and out["error"] == ""
    assert out["otherSeatTicked"] is True, "saving risk discarded the unsaved edit on defect"
    assert out["dimensionsTicked"] == [False], "saving risk put the unsaved dimension edit back"
    assert out["error2"] == "" and out["status2"].startswith("Saved: the models on defect")
    assert [(s["body"]["seat"], s["body"]["model_id"]) for s in out["sent"]] == [
        ("risk", ["local"]), ("defect", ["opus"])]
    assert console.call("/config/nodes")[1]["seat_models"] == {"risk": ["local"],
                                                                "defect": ["opus"]}


@needs_node
def test_an_editor_submits_the_version_it_opened_from_so_a_second_tab_is_not_overwritten(console):
    """Open an editor, let another tab change the configuration (the version moves and the page's
    state follows, as the stream would), then save: the request carries the opened version, the
    server refuses it, its sentence is on screen and nothing is written.

    *cut*: send `state.version` instead of `panelVersion` in `save()` and the save goes through.
    """
    node = _first(lambda m: m == graph.POOL)
    out = console.harness("stale_editor", node=node.id, tick=["opus"])
    assert out["movedTo"] > out["openedAt"]
    assert [s["body"]["version"] for s in out["sent"]] == [out["openedAt"]]
    assert f"you answered version {out['openedAt']}" in out["error"], out["error"]
    assert out["status"].startswith("Not saved")
    assert console.call("/config/nodes")[1]["node_models"] == {}


@needs_node
def test_a_refused_read_while_opening_a_node_is_shown(console):
    """*cut*: render the panel only after `loadConfig()` resolves (as `openPanel` did) and the
    refusal has no line to land on: the panel stays closed and the error is lost."""
    out = console.harness("open_refused", node=_seat_node().id, say="the store is locked")
    assert out["error"] == "the store is locked"
    assert out["hidden"] is False and "settings are not loaded" in out["panel"]


@pytest.mark.parametrize("content", ["{not json", json.dumps({"review_seats": 0}),
                                     json.dumps({"review_seats": 13})])
def test_the_seats_route_answers_a_bad_settings_file_instead_of_dropping_the_connection(
        console, content):
    """*cut*: take the `try`/`except` out of `do_GET` and the client sees a dropped connection."""
    console.settings_path.write_text(content, encoding="utf-8")
    code, out = console.call("/config/seats")
    assert code == 409 and "settings" in out["error"], out


def test_a_server_with_no_settings_file_answers_the_seats_route_with_the_defaults(tmp_path):
    """`GET /config/seats` is a read: it answers 200 with defaults, and only a write is refused."""
    operator = server.Operator.mint(tmp_path)
    runner = server.Runner(walk=lambda cfg: engine.RunReport(), make_config=lambda *a, **k: None)
    db = store.connect(tmp_path / "c.sqlite")
    httpd = server.serve(runner, operator, port=0, db=db)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/config/seats")
        request.add_header("X-Operator-Token", operator.token)
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read())
        assert response.status == 200 and body["review_dimensions"] is None
        assert body["review_seats"] is None and body["floor"] == policy.SEAT_FLOOR
    finally:
        httpd.shutdown()
        db.close()


@needs_node
def test_a_seat_or_node_the_plan_sets_says_so_and_offers_no_save(tmp_path):
    """`store.resolve` lets the plan win, so a save there would change nothing the run reads.

    *cut*: drop the `fixed` test in `renderSeatEditor` or the node editor and the save button, and
    the unlocked boxes, come back.
    """
    node = _first(lambda m: m == graph.POOL)
    made = Console(tmp_path, plan={"seat_models": {"defect": ["opus"]},
                                   "node_models": {node.id: ["local"]}})
    try:
        seat = made.harness("plan_seat", node=_seat_node().id)
        assert "defect — set by the plan" in seat["text"]
        assert "The plan file sets this seat" in seat["text"]
        assert "save defect models" not in seat["buttons"]
        assert "save risk models" in seat["buttons"]
        assert seat["locked"] == 2, "the plan's seat shows its two registry models, locked"
        panel = made.harness("panel", ids=[node.id])["panels"][node.id]
        assert "The plan file sets this node" in panel["text"]
        assert f"save the models for {node.id}" not in panel["buttons"]
        # And a seat the plan is silent about is still editable.
        quiet = next(n for n in graph.NODES if n.mode == graph.SURVEY)
        assert "save risk models" in made.harness("plan_seat", node=quiet.id)["buttons"]
    finally:
        made.close()


@needs_node
def test_the_control_acted_on_keeps_focus_and_a_save_says_what_happened(console):
    """Ticking a box, moving a row, picking a model and saving each redraw rows; focus lands on the
    control the user pressed, mounted in the new tree.

    *cut*: drop the `want`/`keyed` restore in `checklist()` and `active` is a removed element.
    """
    out = console.harness("focus", node=_seat_node().id, nth=0)
    assert out["afterTick"] == {"who": "open the security seat", "mounted": True}
    assert out["afterMove"] == {"who": "move security earlier", "mounted": True}
    assert out["afterPick"] == {"who": "opus", "mounted": True}
    assert out["afterSave"] == {"who": "save the review dimensions", "mounted": True}


@needs_node
def test_a_save_and_a_refusal_are_each_stated_in_words_in_a_live_region(console):
    """*cut*: drop `panelStatus` from `save()`, or the `aria-live` on the status line."""
    ok = console.harness("save_models", node=_first(lambda m: m == graph.POOL).id, tick=["opus"])
    assert ok["error"] == "" and ok["status"].startswith("Saved: the models for")
    refused = console.harness("save_dimensions", node=_seat_node().id, steps=[
        {"untick": "risk"}, {"untick": "defect"}])
    assert refused["status"] == "Not saved: the server refused it."
    assert "below the floor" in refused["error"]
    live = console.harness("live", node=_seat_node().id)["live"]
    assert live == {"status": "polite", "error": "alert"}


@needs_node
def test_the_model_picker_shows_where_each_model_sends_the_work(console):
    """Every row of a picker states `reach`, and says when it is a guess.

    *cut*: drop `reachSpan(m)` from the picker's `fill` (or the guessed note) and these fail.
    """
    assert console.post("/models", {"model": {
        "id": "far", "vendor": "v", "name": "n", "transport": "api",
        "endpoint": "https://api.example.com/v1", "key_env": "KEY"}})[0] == 200
    assert console.post("/models", {"model": {
        "id": "box", "vendor": "v", "name": "n", "transport": "api",
        "endpoint": "http://gpu-box:8000/v1"}})[0] == 200
    node = _first(lambda m: m == graph.POOL)
    text = console.harness("panel", ids=[node.id])["panels"][node.id]["text"]
    row = lambda m: re.search(m + r" tier .*?(?= (?:far|box|local|opus) tier| save )", text)
    assert "reach external" in row("far").group(0), text
    assert "reach internal? guessed from the host name, not measured" in row("box").group(0)
    assert "reach local" in row("local").group(0)


def test_a_settings_file_that_stops_loading_stops_the_walk(tmp_path, monkeypatch, capsys):
    """`make_config` used to fall back to the settings read at startup, so a malformed file brought
    back the weaker review the operator had since tightened. Now the walk is not started, and the
    error is the one `Runner` puts on the console.

    *cut*: put `live = saved` back in the `except` of `make_config` and nothing is raised.
    """
    from test_model_tier_effort import TEMPLATE, _project, _serve
    _project(tmp_path, [dict(id="coder", vendor="v", name="n", transport="cli", **TEMPLATE)],
             saved={"high_risk_mode": True, "review_seats": 1})
    code, out, make_config = _serve(tmp_path, monkeypatch, capsys)
    assert code == 2 and make_config is not None, out
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"review_seats": 5}), encoding="utf-8")
    cfg = make_config((), (), ())
    assert cfg.review_seats == 5 and cfg.high_risk_mode is False, "the live file is what is read"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(cli.CliError) as raised:
        make_config((), (), ())
    assert "settings" in str(raised.value) and "not started" in str(raised.value)
    # Through the runner, as the console shows it: the walk stops and says why.
    monkeypatch.undo()          # `_serve` swapped the real `Runner` for a catcher
    runner = server.Runner(walk=lambda cfg: engine.RunReport(), make_config=make_config)
    snapshot = runner.start("do it", 0)
    assert snapshot["state"] == engine.STOPPED and "not started" in snapshot["error"], snapshot


# ── review round 2 ────────────────────────────────────────────────────────────────────────────

@needs_node
def test_a_refused_read_after_a_save_is_shown(console):
    """The seats POST does not read the settings file and the seats GET does, so a save can go
    through and its read-back be refused. That sentence reaches the alert line, and a dimensions
    save does not turn it into a TypeError.

    *cut*: drop `if (seatInfoError) panelError(seatInfoError)` from `save()` (the seat case), or
    the `if (!seatInfo) return` of `renderDimensions` (the dimensions case).
    """
    node = _seat_node().id
    seat = console.harness("readback_refused", node=node, press="seat", seat="risk",
                           nth=_seat_index("risk"), say="the settings file is invalid")
    assert seat["status"].startswith("Saved: the models on risk")
    assert seat["error"] == "the settings file is invalid"
    dims = console.harness("readback_refused", node=node, press="dimensions",
                           say="the settings file is invalid")
    assert dims["error"] == "the settings file is invalid", dims
    assert "null" not in dims["error"] and "TypeError" not in dims["error"]


@needs_node
def test_a_save_answered_after_another_panel_opened_does_not_re_authorise_that_panel(console):
    """Save `risk` on one seat node, and open the other seat node before the answer arrives (its
    read returns the old settings). The late answer must not give the new panel the newer version:
    saving its still-empty `risk` would then erase what the first save wrote.

    *cut*: drop the `epoch !== panelEpoch` guard in `save()`'s success handler.
    """
    seat_nodes = [n.id for n in graph.NODES if n.mode in (graph.SEAT_PANEL, graph.SURVEY)]
    assert len(seat_nodes) >= 2
    out = console.harness("late_save", node=seat_nodes[0], other=seat_nodes[1], seat="risk",
                          model="opus", nth=_seat_index("risk"))
    assert out["versionAfter"] == out["openedAt"], "the late answer moved the new panel's version"
    assert out["stored"] == {"risk": ["opus"]}
    assert out["status"] == "", "the late answer wrote its status into another panel"
    assert out["stored"] == console.call("/config/nodes")[1]["seat_models"]
    assert "you answered version" in out["error2"], out
    assert console.call("/config/nodes")[1]["seat_models"] == {"risk": ["opus"]}


@needs_node
def test_a_panel_opened_first_but_answered_last_does_not_set_the_version(console):
    """Two nodes opened in a row; the first one's read answers after the second's. Its older
    answer is dropped whole: the panel on screen keeps the version it read before its own fetch.

    *cut*: drop the `epoch !== panelEpoch` return in `loadConfig()`.
    """
    seat_nodes = [n.id for n in graph.NODES if n.mode in (graph.SEAT_PANEL, graph.SURVEY)]
    out = console.harness("overlap", first=seat_nodes[0], second=seat_nodes[1])
    assert out["panelVersion"] == out["second"], out
    assert out["title"].startswith(seat_nodes[1])


def test_a_config_write_answers_the_version_its_own_edit_made(console, monkeypatch):
    """Another tab's commit landing right after this edit's lock is let go must not change what
    this edit answers: the client adopts that number as its next save's version.

    *cut*: answer `runner.state.version` after the edit in `_config_edit` / `_set_dimensions`.
    """
    runner = console.runner
    real = runner.edit_versioned

    def then_another_tab(version, write):
        done = real(version, write)
        runner.publish_config_change()           # the other tab, between release and answer
        return done

    monkeypatch.setattr(runner, "edit_versioned", then_another_tab)
    for path, body in (("/config/seats", {"seat": "risk", "model_id": ["opus"]}),
                       ("/config/dimensions", {"review_dimensions": None})):
        before = console.call("/run")[1]["version"]
        code, out = console.call(path, {**body, "version": before})
        assert code == 200, out
        assert out["version"] == before + 1, (path, out["version"], before)
        assert console.call("/run")[1]["version"] == before + 2


@needs_node
def test_opening_a_node_moves_focus_into_its_panel_and_closing_returns_it(console):
    """Enter on a node puts focus on the panel's heading (a focus target, named by the region),
    it stays there when the loaded settings redraw the panel, and Escape returns it to the node.

    *cut*: drop the `title.focus()` in `openPanel` (or the `kept` refocus in `renderPanel`).
    """
    node = _seat_node().id
    out = console.harness("opened", node=node)
    assert out["atOpen"] == {"id": "paneltitle", "tabindex": "-1"}
    assert out["afterLoad"] == {"id": "paneltitle", "mounted": True}
    assert out["afterClose"] == node
    assert 'aria-labelledby="paneltitle"' in PAGE.read_text(encoding="utf-8")


@needs_node
def test_visited_nodes_and_taken_edges_say_so_without_colour(console):
    """A visited node carries a check mark and "visited" in its accessible name; the node the run is
    at says HERE and not visited; an edge with both ends visited has an accessible name.

    *cut*: drop the `visited` check mark from `tags`, or the `, visited` from the label, or the
    `aria-label` on the taken edge.
    """
    flow = [n for n in graph.NODES]
    seen, here = [flow[0].id, flow[1].id], flow[2].id
    out = console.harness("chart", at=here, visited=seen + [here])
    assert "\u2713" in out["nodes"][seen[0]]["text"] and "visited" in out["nodes"][seen[0]]["label"]
    assert "HERE" in out["nodes"][here]["text"] and "visited" not in out["nodes"][here]["label"]
    unseen = flow[-1].id
    assert "\u2713" not in out["nodes"][unseen]["text"]
    assert "visited" not in out["nodes"][unseen]["label"]
    taken = [e for e in out["edges"] if "taken" in e["cls"]]
    assert taken and all(e["label"] and e["from"] in e["label"] and e["to"] in e["label"]
                         for e in taken)
    assert all(e["label"] is None for e in out["edges"] if "taken" not in e["cls"])


def test_the_page_says_only_what_the_taken_check_does():
    """The comment and legend must not claim an order or a walked edge the code does not check.

    *cut*: put "in order" / "this run took" back.
    """
    page = PAGE.read_text(encoding="utf-8")
    assert "both ends visited, in order" not in page and "an edge this run took" not in page
    assert "seen.indexOf(e.from) >= 0 && seen.indexOf(e.to) >= 0" in page


def _serve_for_console(tmp_path, monkeypatch, capsys):
    """`cmd_serve`, as far as the arguments it gives `server.serve` and the `make_config` it gives
    the `Runner`; `real_serve` is the function the test may call afterwards."""
    real_serve = server.serve
    seen = {}

    class Catch:
        def __init__(self, **kw):
            seen["make_config"] = kw["make_config"]

    def capture(*a, **kw):
        seen["args"], seen["kw"] = a, kw
        raise server.ServerError("stopped by the test")

    monkeypatch.setattr(server, "Runner", Catch)
    monkeypatch.setattr(server, "serve", capture)
    code = cli.main(["--config", str(tmp_path / "runner.yaml"),
                     "--settings", str(tmp_path / "settings.json"),
                     "serve", "--plan", str(tmp_path / "plan.json"),
                     "--token-dir", str(tmp_path / "tok"),
                     "--assignment-store", str(tmp_path / "config.sqlite"),
                     "--ask-journal", str(tmp_path / "asks")])
    out = capsys.readouterr().out
    assert code == 2 and "stopped by the test" in out, out
    monkeypatch.undo()
    return real_serve, seen, seen["make_config"]


def test_the_console_names_the_coder_the_next_walk_will_use(tmp_path, monkeypatch, capsys):
    """`make_config` re-reads the settings file per walk. The console's coder default read the copy
    from startup, so after the file changed it named one coder and the walk built with another.

    *cut*: pass `saved` instead of `settings_mod.load(args.settings)` in `coder_default()`.
    """
    from test_model_tier_effort import TEMPLATE, _project
    _project(tmp_path, [dict(id="a", vendor="v", name="n", transport="cli", **TEMPLATE),
                        dict(id="b", vendor="v", name="n", transport="cli", **TEMPLATE)],
             saved={"coder_model": "a"})
    real_serve, seen, make_config = _serve_for_console(tmp_path, monkeypatch, capsys)
    coder_default = seen["kw"]["coder_default"]
    path = tmp_path / "settings.json"
    build_chain = {"engineer_build"} | {n.id for n in graph.NODES if n.follows == "engineer_build"}
    assert set(coder_default()) == build_chain and coder_default()["engineer_build"] == ["a"]

    path.write_text(json.dumps({"coder_model": "b"}), encoding="utf-8")
    assert coder_default()["engineer_build"] == ["b"]
    assert make_config((), (), ()).node_models["engineer_build"] == ["b"]

    # Through the route the page reads, so the model list and the node panel say "b" too.
    operator = seen["args"][1]
    runner = server.Runner(walk=lambda cfg: engine.RunReport(), make_config=make_config)
    httpd = real_serve(runner, operator, **{**seen["kw"], "port": 0})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/config/nodes")
        request.add_header("X-Operator-Token", operator.token)
        with urllib.request.urlopen(request, timeout=10) as response:
            by_model = json.loads(response.read())["by_model"]
    finally:
        httpd.shutdown()
    assert any(u.get("default") for u in by_model["b"]["nodes"]), by_model
    assert "a" not in by_model or not any(u.get("default") for u in by_model["a"]["nodes"])

    path.write_text("{not json", encoding="utf-8")
    assert coder_default() == {}, "a file that does not load starts no walk, so names no coder"


def test_the_stop_message_for_a_broken_settings_file_says_only_what_works(
        tmp_path, monkeypatch, capsys):
    """The console cannot save the review dimensions while the file does not load (the save reads
    it first), so the message must not send the operator there.

    *cut*: put "save it again from the console" back in the `CliError` of `make_config`.
    """
    from test_model_tier_effort import TEMPLATE, _project
    _project(tmp_path, [dict(id="a", vendor="v", name="n", transport="cli", **TEMPLATE)])
    _, _, make_config = _serve_for_console(tmp_path, monkeypatch, capsys)
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(cli.CliError) as raised:
        make_config((), (), ())
    message = str(raised.value)
    assert "fix the settings file" in message and "from the console" not in message, message


def test_every_text_mode_subprocess_run_names_its_encoding():
    """Node writes UTF-8 and the harness leaves non-ASCII unescaped; a locale codec (cp950,
    cp1252) would mis-decode it, so a text-mode run must say which codec it reads."""
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    runs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == "run"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "subprocess"]
    assert runs, "no subprocess.run found; this check would pass on nothing"
    for call in runs:
        names = {k.arg for k in call.keywords}
        if names & {"text", "universal_newlines"}:
            assert "encoding" in names, f"line {call.lineno}: subprocess.run(text=True) names no encoding"
