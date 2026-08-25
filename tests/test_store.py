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
    assert db.execute("pragma foreign_keys").fetchone()[0] == 1
    assert db.execute("pragma journal_mode").fetchone()[0] == "wal"
    assert db.execute("pragma user_version").fetchone()[0] == store.SCHEMA_VERSION


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
        if node is None:
            continue
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
    assert console.call("/models", {"version": 0, "model": MODEL})[0] == 200
    code, out = console.call("/config/nodes", {"version": 0, "node_id": "pm_plan",
                                               "models": ["opus"]})
    assert code == 200, out
    assert out["node_models"] == {"pm_plan": ["opus"]}


def test_a_model_added_and_assigned_through_the_console_survives_a_restart(tmp_path):
    first = _Console(tmp_path)
    assert first.call("/models", {"version": 0, "model": MODEL})[0] == 200
    assert first.call("/config/nodes", {"version": 0, "node_id": "pm_plan",
                                        "models": ["opus"]})[0] == 200
    assert first.call("/config/seats", {"version": 0, "seat": "defect",
                                        "model_id": "opus"})[0] == 200
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
        made.call("/models", {"version": 0, "model": MODEL})
        made.call("/config/nodes", {"version": 0, "node_id": "pm_plan", "models": ["opus"]})
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
        _, out = made.call("/config/nodes", {"version": 0, "node_id": "lead_review", "models": []})
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
    console.call("/models", {"version": 0, "model": MODEL})
    code, out = console.call(path, {"version": 0, **body})
    assert code == 409, out
    assert fragment in out["error"]


@pytest.mark.parametrize("path", ["/config/nodes", "/config/seats"])
def test_an_assignment_edit_needs_the_run_version_like_every_other_post(console, path):
    code, out = console.call(path, {"node_id": "pm_plan", "models": [], "seat": "defect"})
    assert code == 409
    assert "version" in out["error"]
