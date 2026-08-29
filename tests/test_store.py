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

from ai_sdlc_runner import engine, graph, models, paths, server, store  # noqa: E402

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


def test_a_half_built_store_with_the_RIGHT_shape_recovers(tmp_path):
    """`executescript` autocommits, so a crash before `PRAGMA user_version` leaves tables at 0.

    The first version of this test created `models(id)` — a table with **one** of its eight columns
    — and asserted the reopen succeeded. It did, and the store was then marked current and failed on
    first use. **The test written to prove the recovery works was demonstrating the defect and
    reporting green**, which is this repository's most-recorded shape appearing inside the check
    built to catch it.

    So the case is split. Here: the correct shape, which must recover.
    """
    import sqlite3
    path = tmp_path / "half.sqlite"
    made = store.connect(tmp_path / "reference.sqlite")
    ddl = [row[0] for row in made.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name")]
    made.close()

    half = sqlite3.connect(str(path))
    for statement in ddl:                       # the real tables, and no version
        half.executescript(statement + ";")
    half.commit()
    half.close()
    assert sqlite3.connect(str(path)).execute("pragma user_version").fetchone()[0] == 0

    recovered = store.connect(path)
    assert recovered.execute("pragma user_version").fetchone()[0] == store.SCHEMA_VERSION
    # ...and it is usable, which is the part the old test never checked.
    store.save_registry(recovered, models.Registry(models=(_model(),)))
    assert [m.id for m in store.load_registry(recovered)] == ["opus"]
    recovered.close()


def test_a_half_built_store_with_the_WRONG_shape_is_refused_not_blessed(tmp_path):
    """`IF NOT EXISTS` skipped creation on any table with the right **name**.

    ```
    blessed to version: 1
    actual columns    : ['id']
    first real use    -> OperationalError: table models has no column named vendor
    ```

    A name standing in for a constraint, inside the recovery written for the previous name standing
    in for a constraint. Found by a seat.
    """
    import sqlite3
    path = tmp_path / "wrong.sqlite"
    broken = sqlite3.connect(str(path))
    broken.executescript("CREATE TABLE models (id TEXT PRIMARY KEY);")
    broken.close()

    with pytest.raises(store.StoreError) as exc:
        store.connect(path)
    assert "already exists with columns" in str(exc.value)
    assert "move it aside" in str(exc.value)


def test_a_file_that_is_not_a_database_is_refused_by_name(tmp_path):
    """It raised a raw `sqlite3.DatabaseError`, and `cmd_serve` catches only `StoreError` — so an
    operator whose store got corrupted met a traceback instead of a sentence."""
    junk = tmp_path / "junk.sqlite"
    junk.write_text("not a database at all", encoding="utf-8")
    with pytest.raises(store.StoreError, match="could not be opened as a store"):
        store.connect(junk)


def test_the_refusal_shows_the_path_a_person_would_type(tmp_path, monkeypatch):
    r"""The message runs `str(exc)` through `paths.plain`, and nothing checked that it does.

    The path handed to the OS carries the extended-length prefix, so a message quoting the driver's
    text raw can say `\\?\C:\…` — which sends whoever is debugging it looking for a network share
    that does not exist. `store.connect` has a comment saying exactly this, and the guarantee had no
    test: replacing `paths.plain(str(exc))` with `str(exc)` left the whole suite green.

    **The obvious test does not work, and that is the point of this one.** Opening a junk file
    raises `file is not a database` — a message with no path in it at all — so an assertion that the
    prefix is absent passes whether or not `paths.plain` is applied. The first version of this test
    did exactly that, in the change whose subject is tests that pass either way.

    So the driver is made to produce the message the guard exists for (CHG-20260828-24).
    """
    import sqlite3

    long_form = paths.PREFIX + str(tmp_path / "config.sqlite")

    def refuse(*args, **kw):
        raise sqlite3.DatabaseError(f"unable to open database file {long_form}")

    monkeypatch.setattr(store.sqlite3, "connect", refuse)
    with pytest.raises(store.StoreError) as caught:
        store.connect(tmp_path / "config.sqlite")

    said = str(caught.value)
    assert paths.PREFIX not in said, f"the extended-length prefix reached the operator: {said}"
    assert "unable to open database file" in said, "the driver's reason must survive the stripping"


def test_plain_in_strips_the_prefix_wherever_it_sits():
    r"""The helper the refusal above depends on, and the reason it had to be a new one.

    `plain` strips a **leading** prefix, which is right for a path and wrong for a sentence quoting
    one. Both call sites that quote an OS error were using `plain`, both carried a comment saying
    the prefix must not reach the reader, and neither delivered it (CHG-20260828-24).
    """
    inside = paths.PREFIX + r"C:\x"
    assert paths.plain_in(f"unable to open {inside} now") == r"unable to open C:\x now"
    assert paths.plain_in(inside) == r"C:\x"
    assert paths.plain_in("nothing to strip") == "nothing to strip"


def test_plain_in_puts_a_unc_path_back_the_way_a_person_types_it():
    r"""`\\?\UNC\srv\share` starts with `\\?\` too, so the order of the two replacements is the
    guarantee: strip the shorter one first and the reader is left with `UNC\srv\share`, which is
    not a path anybody can use."""
    assert paths.plain_in("at " + paths.UNC_PREFIX + r"srv\share end") == r"at \\srv\share end"


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


def test_a_stored_assignment_reaches_an_actual_dispatch(tmp_path):
    """Walk the engine and watch which model the factory was asked for.

    The first version of this test built a `RunConfig` and asserted the id was in it. A seat named
    it exactly: *"never calls engine.walk, never opens a session, never observes a backend — its
    name stands in for the constraint it did not examine."* That is the defect this whole file is
    about, in the test written to prove the defect was gone.

    So this one runs the walk and records every `(seat, model)` the factory is asked to open.
    """
    from ai_sdlc_runner import engine, graph, workorder

    db = store.connect(tmp_path / "config.sqlite")
    store.save_registry(db, models.Registry(models=(_model(id="chosen"),)))
    store.set_node_models(db, "pm_plan", ["chosen"])
    merged, _ = store.resolve(
        {"node_models": {}, "seat_models": {}},
        {"node_models": store.node_models(db), "seat_models": store.seat_models(db)})
    db.close()

    asked = []

    class Recorder(engine.Session):
        def __init__(self, model):
            self.model = model

        def ask(self, order):
            asked.append((order["node_id"], self.model))
            node = graph.BY_ID[order["node_id"]]
            # Every key any node on the way might read. A stub that answers half the contract
            # stops the walk before the node under test, which is how the first attempt at this
            # test saw an empty list and blamed the wiring.
            return {"verdict": list(node.branches)[0] if node.branches else "done",
                    "modules": [], "module": "",
                    "missing": [], "problems": [], "unsafe": []}

        def close(self):
            pass

    def factory(seat=None, model=None):
        return Recorder(model)

    # A spec with content in it. The first version was `{field: "" for field in NODE_SPEC_FIELDS}`
    # — enough keys to satisfy a check that only counted them, which is exactly the defect
    # CHG-20260823-34 closed. This test is about which *model* gets dispatched, so the spec only has
    # to be real, not elaborate.
    spec = {field: f"{field} for the dispatch test" for field in workorder.NODE_SPEC_FIELDS}
    spec.update({"input_artifacts": [], "expected_outputs": [], "idempotence_probes": [],
                 "workdir": "."})
    cfg = engine.RunConfig(
        node_specs={node.id: dict(spec) for node in graph.NODES},
        decisions={}, risk="low",
        operations={node.id: [{"description": "x", "kind": "ordinary", "targets": []}]
                    for node in graph.NODES},
        node_models=merged["node_models"],
        max_steps=40)
    try:
        engine.walk(cfg, factory, enabled=True)
    except engine.EngineError:
        pass                                    # the walk may stop early; the ask is what matters

    dispatched = [model for node_id, model in asked if node_id == "pm_plan"]
    assert dispatched, f"pm_plan was never asked; asked = {asked[:5]}"
    assert dispatched[0] == "chosen", (
        f"the engine dispatched {dispatched[0]!r}, not the model the store assigned")


def test_neither_command_reads_the_plan_directly_for_node_models():
    """Both `run` and `serve` must resolve. `run` did not open the store at all."""
    import inspect
    from ai_sdlc_runner import cli

    for command in (cli.cmd_run, cli.cmd_serve):
        source = inspect.getsource(command)
        assert 'node_models=plan.get("node_models"' not in source, (
            f"{command.__name__} reads the plan directly; a stored assignment would be ignored")


# ── round 2: the corrections' own findings ────────────────────────────────────────────────────

def test_run_hands_the_registry_to_the_factory_it_resolved_ids_for():
    """The critical round-2 finding, and the same class as round 1's.

    `cmd_run` resolved stored model ids into `RunConfig` and then called `session_factory` **without
    the registry** — and `session_factory` only translates an id to a command when
    `registry is not None`. So `run` selected a stored model and dispatched to the default backend.
    Configuration that looks connected and does not govern execution, one command over.
    """
    import inspect
    from ai_sdlc_runner import cli

    walk_call = [line for line in inspect.getsource(cli.cmd_run).splitlines()
                 if "session_factory(" in line]
    assert walk_call, "cmd_run no longer builds a factory"
    assert any("registry=" in line for line in
               inspect.getsource(cli.cmd_run).split("session_factory(")[1].splitlines()[:3]), (
        "cmd_run calls session_factory without a registry; a stored model id cannot be dispatched")


def test_a_config_edit_checks_and_bumps_the_version_without_letting_go(console):
    """Three separate critical sections is a check-then-act window.

    Two threads validate version N, both write, both bump — and the double-submit the version
    exists to refuse happens anyway. `Runner.edit` holds one lock across all three.
    """
    import inspect
    from ai_sdlc_runner import server as server_mod

    edit = inspect.getsource(server_mod.Runner.edit)
    assert "with self._lock:" in edit
    body = edit.split("with self._lock:")[1]
    for step in ("_require_version", "write()", "self.state.version += 1"):
        assert step in body, f"{step} is outside the lock"


def test_adding_a_model_also_checks_the_version(console):
    """The fix stopped one route short of the one that writes a file."""
    _, state = console.call("/run")
    assert console.call("/models", {"version": state["version"], "model": MODEL})[0] == 200
    code, out = console.call("/models", {"version": state["version"],
                                         "model": {**MODEL, "id": "second"}})
    assert code == 409, "POST /models accepted a stale version"
    assert "answered version" in out["error"]


def test_concurrent_config_edits_and_model_adds_do_not_deadlock(tmp_path):
    """Two lock orderings deadlock, and this file had two for exactly one round.

    The fix for the check-then-act window took the store's lock inside `write()` and `held_lock`
    after it, while `POST /models` took `held_lock` first — so one thread holding `held` and waiting
    for the store, and another holding the store and waiting for `held`, would both block forever.

    Driven with real concurrent requests rather than reasoned about, because a lock order argued
    from is a lock order nobody measured.
    """
    import concurrent.futures

    made = _Console(tmp_path)
    try:
        made.post("/models", {"model": MODEL})
        for extra in ("second", "third", "fourth"):
            made.post("/models", {"model": {**MODEL, "id": extra}})

        def edit(n):
            return made.post("/config/nodes",
                             {"node_id": "pm_plan", "models": ["opus"] if n % 2 else []})[0]

        def add(n):
            return made.post("/models", {"model": {**MODEL, "id": f"m{n}"}})[0]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(edit if n % 2 else add, n) for n in range(16)]
            codes = [job.result(timeout=30) for job in jobs]

        # Some lose the version race — that is the mechanism, not a hang. Nothing may block.
        assert set(codes) <= {200, 409}, codes
        assert 200 in codes
    finally:
        made.close()


def test_the_lock_order_is_stated_and_every_path_takes_it():
    """A lock order that lives only in the author's head is the one that gets inverted."""
    import inspect
    from ai_sdlc_runner import server as server_mod

    source = inspect.getsource(server_mod.make_handler)
    assert "LOCK_ORDER" in source, "the order must be written down, not remembered"

    # The BODY of , not the docstring above it — prose mentioning `write()` is not
    # the call to it, and a test that cannot tell them apart is reading the wrong thing.
    body = source.split("def under_lock():")[1].split("out = runner.edit")[0]
    code = [line for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")]
    joined = chr(10).join(code)
    assert joined.index("with held_lock") < joined.index("write()"), (
        f"_config_edit reaches the store before held; that is the inverted order:{chr(10)}{joined}")
