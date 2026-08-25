"""The assignment store and its two routes (CHG-20260823-25).

The user ruled that 「模型配置」 includes the **assignment**, not just the registry — so this is the
half that had no writer anywhere in `src/`, now built.

Two of these tests exist because **driving the real server found what unit tests could not**:
`ThreadingHTTPServer` handles each request in its own thread, and a SQLite connection bound to the
thread that opened it raises on the first console edit. Every refusal that fires *before* touching
the database returned `409` correctly; everything that reached it returned `500`.
"""
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_sdlc_runner import engine, graph, models, server, store  # noqa: E402

MODEL = {"id": "opus", "vendor": "anthropic", "name": "claude-opus-5",
         "transport": "cli", "command": ["claude", "-p"]}


def _model(**over):
    return models.Model(**{**{k: (tuple(v) if isinstance(v, list) else v)
                              for k, v in MODEL.items()}, **over})


@pytest.fixture
def db(tmp_path):
    connection = store.connect(tmp_path / "config.sqlite")
    yield connection
    connection.close()


# ── the store ─────────────────────────────────────────────────────────────────────────────────

def test_the_pragmas_this_connection_needs_are_on_it(db):
    """All five `connect` sets, not the three that were easy to check.

    A seat pointed out that `busy_timeout` and `synchronous` were asserted nowhere — the two that
    decide what happens under contention and what a power cut costs.
    """
    assert db.execute("pragma foreign_keys").fetchone()[0] == 1
    assert db.execute("pragma journal_mode").fetchone()[0] == "wal"
    assert db.execute("pragma user_version").fetchone()[0] == store.SCHEMA_VERSION
    assert db.execute("pragma busy_timeout").fetchone()[0] == 5000
    assert db.execute("pragma synchronous").fetchone()[0] == 1        # NORMAL


def test_a_store_that_died_between_its_tables_and_its_version_still_opens(tmp_path):
    """`executescript` autocommits, so a crash there left tables at version 0.

    Every later open re-ran the script and died with `table models already exists` — the store
    bricked permanently by an interruption at the one moment it could least survive one. Simulated
    by a seat; reproduced here.
    """
    import sqlite3
    path = tmp_path / "half.sqlite"
    half = sqlite3.connect(str(path))
    half.executescript("CREATE TABLE models (id TEXT PRIMARY KEY);")
    half.close()
    assert sqlite3.connect(str(path)).execute("pragma user_version").fetchone()[0] == 0

    recovered = store.connect(path)
    assert recovered.execute("pragma user_version").fetchone()[0] == store.SCHEMA_VERSION
    recovered.close()


def test_a_file_that_is_not_a_database_is_refused_by_name(tmp_path):
    """It raised a raw `sqlite3.DatabaseError`, and `cmd_serve` catches only `StoreError` — so an
    operator whose store got corrupted met a traceback instead of a sentence."""
    junk = tmp_path / "junk.sqlite"
    junk.write_text("not a database at all", encoding="utf-8")
    with pytest.raises(store.StoreError, match="could not be opened as a store"):
        store.connect(junk)


def test_a_store_from_the_future_is_refused_rather_than_guessed_at(tmp_path):
    path = tmp_path / "future.sqlite"
    ahead = store.connect(path)
    ahead.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
    ahead.commit()
    ahead.close()
    with pytest.raises(store.StoreError, match="upgrade the runner"):
        store.connect(path)


def test_the_registry_round_trips_and_reach_is_recomputed(db):
    store.save_registry(db, models.Registry(models=(_model(),)))
    back = store.load_registry(db)
    assert [m.id for m in back] == ["opus"]
    assert back.models[0].reach == models.LOCAL          # computed on read, not a column
    assert "reach" not in {row[1] for row in db.execute("pragma table_info(models)")}


def test_every_row_is_read_back_through_the_validator(db):
    """The database enforces identity; `models.validate` enforces the rest, and only it does."""
    store.save_registry(db, models.Registry(models=(_model(),)))
    with db:
        db.execute("UPDATE models SET vendor = ''")      # a row the validator refuses
    with pytest.raises(models.ModelError, match="names no vendor"):
        store.load_registry(db)


def test_an_assignment_survives_being_written_and_read(db):
    store.save_registry(db, models.Registry(models=(_model(),)))
    store.set_node_models(db, "pm_plan", ["opus"])
    store.set_seat_model(db, "defect", "opus")
    assert store.node_models(db) == {"pm_plan": ["opus"]}
    assert store.seat_models(db) == {"defect": "opus"}


def test_the_order_of_a_node_list_is_kept(db):
    """A pool's seeded choice and a model panel's ask ids both depend on it."""
    store.save_registry(db, models.Registry(models=(
        _model(id="a"), _model(id="b"), _model(id="c"))))
    # A model_panel: the order decides which ask id each voice gets. A pool would do as well —
    # its seeded choice reads the list positionally.
    store.set_node_models(db, "pm_confirm", ["c", "a", "b"])
    assert store.node_models(db)["pm_confirm"] == ["c", "a", "b"]


def test_an_empty_list_clears_a_node(db):
    store.save_registry(db, models.Registry(models=(_model(),)))
    store.set_node_models(db, "pm_plan", ["opus"])
    store.set_node_models(db, "pm_plan", [])
    assert store.node_models(db) == {}


@pytest.mark.parametrize("node_id, why", [
    ("nope", "no node"),
    ("record_module", "does nothing with a model list"),      # mode `runner`
])
def test_a_node_that_cannot_use_models_is_refused(db, node_id, why):
    store.save_registry(db, models.Registry(models=(_model(),)))
    with pytest.raises(store.StoreError, match=why):
        store.set_node_models(db, node_id, ["opus"])


def test_every_mode_that_ignores_a_list_is_refused(db):
    """Four of the seven modes do nothing with one. Assigning to them would be a setting that
    looks configured and does nothing — the house doctrine, so it is refused."""
    store.save_registry(db, models.Registry(models=(_model(),)))
    ignored = [m for m in graph.MODES if m not in store.MODES_THAT_USE_MODELS]
    assert len(ignored) == 4
    for mode in ignored:
        node = next((n for n in graph.NODES if n.mode == mode), None)
        # No `continue`. The first version skipped a mode with no representative node and still
        # passed — a coarse check licensed to answer safe without examining, which a seat named.
        assert node is not None, (
            f"no node has mode {mode!r}, so this test silently stopped covering it")
        with pytest.raises(store.StoreError, match="does nothing with a model list"):
            store.set_node_models(db, node.id, ["opus"])


def test_a_model_the_registry_does_not_have_is_refused_by_the_foreign_key(db):
    with pytest.raises(store.StoreError, match="no model 'ghost'"):
        store.set_node_models(db, "pm_plan", ["ghost"])


def test_an_unknown_seat_is_refused_and_every_defined_seat_is_allowed(db):
    store.save_registry(db, models.Registry(models=(_model(),)))
    with pytest.raises(store.StoreError, match="no seat 'vibes'"):
        store.set_seat_model(db, "vibes", "opus")
    from ai_sdlc_runner import policy
    for seat in policy.SEATS:
        store.set_seat_model(db, seat.name, "opus")       # including seats above today's floor


# ── precedence ────────────────────────────────────────────────────────────────────────────────

def test_the_plan_wins_and_the_store_fills_and_both_are_named():
    merged, source = store.resolve(
        {"node_models": {"lead_review": ["from-plan"]}},
        {"node_models": {"lead_review": ["from-store"], "pm_plan": ["also-store"]}})
    assert merged["node_models"]["lead_review"] == ["from-plan"]
    assert merged["node_models"]["pm_plan"] == ["also-store"]
    assert source["node_models.lead_review"] == store.FROM_PLAN
    assert source["node_models.pm_plan"] == store.FROM_STORE


def test_an_override_is_never_silent():
    """A merged dict alone cannot say which source put an assignment there."""
    _, source = store.resolve({"seat_models": {"defect": "a"}}, {"seat_models": {"defect": "b"}})
    assert source["seat_models.defect"] == store.FROM_PLAN


# ── the routes, driven over real HTTP ─────────────────────────────────────────────────────────

class _Console:
    def __init__(self, tmp_path, plan_assignments=None, registry=None):
        self.db = store.connect(tmp_path / "config.sqlite")
        self.operator = server.Operator.mint(tmp_path)
        runner = server.Runner(walk=lambda cfg: engine.RunReport(),
                               make_config=lambda *a, **k: None)
        self.httpd = server.serve(runner, self.operator, port=0, registry=registry,
                                  db=self.db, plan_assignments=plan_assignments or {})
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def post(self, path, body):
        """Post at the run's current version, the way a client that reloads state must.

        Every config edit advances the version -- a configuration that moved under another tab
        should invalidate the answer it was about to send -- so a fixed `0` is stale after the
        first write. That is the mechanism working, and a test that hard-coded the version was
        testing a client that does not exist.
        """
        _, state = self.call("/run")
        return self.call(path, {**body, "version": state["version"]})

    def call(self, path, body=None):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if body else "GET")
        request.add_header("X-Operator-Token", self.operator.token)
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def close(self):
        self.httpd.shutdown()
        self.db.close()


@pytest.fixture
def console(tmp_path):
    made = _Console(tmp_path)
    yield made
    made.close()


def test_a_console_edit_does_not_die_on_a_thread_boundary(console):
    """`ThreadingHTTPServer` handles every request in its own thread.

    Driving the real server is the only thing that found this: a connection bound to the thread
    that opened it raised `ProgrammingError`, every pre-database refusal still returned `409`, and
    every route that reached SQLite returned `500`. A test that used the store directly passed.
    """
    assert console.post("/models", {"model": MODEL})[0] == 200
    code, out = console.post("/config/nodes", {"node_id": "pm_plan", "models": ["opus"]})
    assert code == 200, out
    assert out["node_models"] == {"pm_plan": ["opus"]}


def test_a_model_added_and_assigned_through_the_console_survives_a_restart(tmp_path):
    first = _Console(tmp_path)
    assert first.post("/models", {"model": MODEL})[0] == 200
    assert first.post("/config/nodes", {"node_id": "pm_plan", "models": ["opus"]})[0] == 200
    assert first.post("/config/seats", {"seat": "defect", "model_id": "opus"})[0] == 200
    first.close()

    again = _Console(tmp_path)
    try:
        _, out = again.call("/config/nodes")
        assert out["node_models"] == {"pm_plan": ["opus"]}
        assert out["seat_models"] == {"defect": "opus"}
        # The registry too. Driving this found it empty: the store had the model and the console
        # showed none, so an assignment referenced a model the console said did not exist.
        assert [m["id"] for m in out["models"]] == ["opus"]
    finally:
        again.close()


def test_the_read_route_says_which_source_each_assignment_came_from(tmp_path):
    made = _Console(tmp_path, plan_assignments={"node_models": {"lead_review": ["planned"]}})
    try:
        made.post("/models", {"model": MODEL})
        made.post("/config/nodes", {"node_id": "pm_plan", "models": ["opus"]})
        _, out = made.call("/config/nodes")
        assert out["source"]["node_models.lead_review"] == store.FROM_PLAN
        assert out["source"]["node_models.pm_plan"] == store.FROM_STORE
        assert out["assignable"] == list(store.MODES_THAT_USE_MODELS)
    finally:
        made.close()


def test_the_plan_cannot_be_overwritten_from_the_console(tmp_path):
    """Clearing a node the plan speaks for leaves the plan's assignment standing.

    That is the point of the precedence, and it must be visible rather than surprising: the store
    row goes, and the resolved answer does not change.
    """
    made = _Console(tmp_path, plan_assignments={"node_models": {"lead_review": ["planned"]}})
    try:
        _, out = made.post("/config/nodes", {"node_id": "lead_review", "models": []})
        assert out["node_models"]["lead_review"] == ["planned"]
        assert out["source"]["node_models.lead_review"] == store.FROM_PLAN
    finally:
        made.close()


@pytest.mark.parametrize("path, body, fragment", [
    ("/config/nodes", {"node_id": "nope", "models": []}, "no node"),
    ("/config/nodes", {"node_id": "record_module", "models": ["opus"]}, "does nothing"),
    ("/config/nodes", {"node_id": "pm_plan", "models": ["ghost"]}, "no model 'ghost'"),
    ("/config/nodes", {"node_id": "pm_plan", "models": "opus"}, "must be a list"),
    ("/config/seats", {"seat": "vibes", "model_id": "opus"}, "no seat"),
])
def test_every_refusal_reaches_the_operator_as_409(console, path, body, fragment):
    console.post("/models", {"model": MODEL})
    code, out = console.post(path, body)
    assert code == 409, out
    assert fragment in out["error"]


@pytest.mark.parametrize("path", ["/config/nodes", "/config/seats"])
def test_an_assignment_edit_needs_the_run_version_like_every_other_post(console, path):
    code, out = console.call(path, {"node_id": "pm_plan", "models": [], "seat": "defect"})
    assert code == 409
    assert "version" in out["error"]


# ── the three findings an independent seat made on this change ────────────────────────────────

def test_an_assignment_edited_in_the_console_reaches_the_next_run(tmp_path):
    """The worst finding: the edit changed the display and not the run.

    `make_config` read `plan.get("node_models")`, so `_reassign` refreshed what the console showed
    while the engine went on receiving whatever the plan said at startup — and `_reassign`'s own
    comment claimed the opposite. Both are now resolved per walk.
    """
    import inspect
    from ai_sdlc_runner import cli

    serve = inspect.getsource(cli.cmd_serve)
    assert 'node_models=plan.get("node_models"' not in serve, (
        "make_config is reading the plan again; a console edit would be display-only")
    assert "current_assignments()" in serve
    assert "build_factory()" in serve, (
        "the session factory is captured once again; seat routing would freeze at startup")


def test_a_model_can_be_added_after_an_assignment_exists(db):
    """`DELETE FROM models` was refused by the foreign key the moment anything was assigned.

    Worse than a failed write: `POST /models` had already updated memory and `models.json`, so the
    request 500'd with the file and the store disagreeing — and on the next start the store won and
    the added model silently vanished.
    """
    first = _model()
    store.save_registry(db, models.Registry(models=(first,)))
    store.set_node_models(db, "pm_plan", ["opus"])
    store.save_registry(db, models.Registry(models=(first, _model(id="second"))))
    assert [m.id for m in store.load_registry(db)] == ["opus", "second"]
    assert store.node_models(db) == {"pm_plan": ["opus"]}


def test_removing_a_model_something_is_assigned_to_is_refused_by_name(db):
    """"You cannot delete this yet" and "your registry saved" must not look the same."""
    store.save_registry(db, models.Registry(models=(_model(), _model(id="other"))))
    store.set_node_models(db, "pm_plan", ["opus"])
    store.set_seat_model(db, "risk", "opus")
    with pytest.raises(store.StoreError) as exc:
        store.save_registry(db, models.Registry(models=(_model(id="other"),)))
    assert "node 'pm_plan'" in str(exc.value) and "seat 'risk'" in str(exc.value)
    # ...and nothing was half-removed on the way out.
    assert [m.id for m in store.load_registry(db)] == ["opus", "other"]


def test_a_model_nothing_points_at_can_still_be_removed(db):
    store.save_registry(db, models.Registry(models=(_model(), _model(id="other"))))
    store.save_registry(db, models.Registry(models=(_model(),)))
    assert [m.id for m in store.load_registry(db)] == ["opus"]


def test_a_stale_version_is_refused_on_an_assignment_edit(console):
    """They accepted any integer. A field named `version` that is not compared is a name."""
    console.post("/models", {"model": MODEL})
    _, state = console.call("/run")
    current = state["version"]
    assert console.call("/config/nodes", {"version": current, "node_id": "pm_plan",
                                          "models": ["opus"]})[0] == 200
    code, out = console.call("/config/nodes", {"version": current, "node_id": "pm_plan",
                                               "models": []})
    assert code == 409, "the same version was accepted twice; a double-click writes twice"
    assert "answered version" in out["error"]


def test_a_config_edit_advances_the_version_so_other_tabs_see_it(console):
    console.post("/models", {"model": MODEL})
    _, before = console.call("/run")
    console.post("/config/nodes", {"node_id": "pm_plan", "models": ["opus"]})
    _, after = console.call("/run")
    assert after["version"] > before["version"]


def test_a_stored_assignment_reaches_an_actual_dispatch(tmp_path, monkeypatch):
    """The test whose absence let the worst finding ship with every other test green.

    A seat put it plainly: *"No test anywhere asserts a store assignment reaches a dispatch — which
    is why this survived."* So this one walks the engine and looks at which model was asked.
    """
    from ai_sdlc_runner import engine, graph

    db = store.connect(tmp_path / "config.sqlite")
    store.save_registry(db, models.Registry(models=(_model(id="from-store"),)))
    store.set_node_models(db, "pm_confirm", ["from-store"])

    merged, source = store.resolve(
        {"node_models": {}},
        {"node_models": store.node_models(db), "seat_models": store.seat_models(db)})
    db.close()

    assert merged["node_models"]["pm_confirm"] == ["from-store"]
    assert source["node_models.pm_confirm"] == store.FROM_STORE

    # ...and the engine reads exactly that field, so a config built from `merged` dispatches to it.
    cfg = engine.RunConfig(node_specs={}, decisions={},
                           node_models=merged["node_models"])
    assert list(cfg.node_models.get("pm_confirm") or ()) == ["from-store"]
    assert graph.BY_ID["pm_confirm"].mode in store.MODES_THAT_USE_MODELS


def test_neither_command_reads_the_plan_directly_for_node_models():
    """Both `run` and `serve` must resolve. `run` did not open the store at all."""
    import inspect
    from ai_sdlc_runner import cli

    for command in (cli.cmd_run, cli.cmd_serve):
        source = inspect.getsource(command)
        assert 'node_models=plan.get("node_models"' not in source, (
            f"{command.__name__} reads the plan directly; a stored assignment would be ignored")
