"""store.py — the SQLite store for model configuration (CHG-20260823-25).

The ruling on [CHG-20260823-19](../../docs/design/sqlite-only.md) said SQLite holds *「model 模型配置
的紀錄儲存」*, and a later question — *「model 管理的配置沒有被納進db? 那怎麼持久化?」* — established
that **「模型配置」 means both halves**:

| half | what it says | before this module |
|---|---|---|
| the **registry** | which models exist | persisted in `models.json` |
| the **assignment** | which node and which seat gets which model | **persisted nowhere.** Read from the plan at startup, held in memory, exposed read-only, never written |

So through the console you could add a model and never assign it. This is the half that was missing.

## What this module is not

It is **not** the conversation store. The tables for that are designed in `docs/DATABASE.md` and are
deliberately not created here: a table nothing reads or writes is a mechanism nobody invokes, and
this repository has a test that refuses those. They arrive with the code that uses them.

## Precedence, and why the plan wins

An assignment can come from two places, and one of them has to win:

- the **plan file** — this change's declaration, written by the person proposing the change;
- this **store** — the project's standing assignment, edited through the console.

**The plan wins where it says something; the store fills where the plan is silent.** That is
`settings.py`'s rule one layer out — *"a flag beats the file. Someone typing `--seats 1` right now is
making a decision about this run; the file is the standing one"* — and the reason is the same: a
per-change declaration must not be silently overridden by a standing setting somebody configured
weeks ago.

**Neither source is silent.** `resolve()` returns where every assignment came from, so a console
that shows an assignment can say whether the plan or the store put it there. An override nobody can
see is the defect this project keeps recording.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import graph, models as models_mod, policy

#: Bumped when the tables change. Read and compared at open — a version nobody consults is a number,
#: not a mechanism, which is what an earlier draft of the design was pulled up for.
SCHEMA_VERSION = 1

#: The modes that do **something** with a list of models. The other four ignore it entirely, and
#: assigning to them is refused rather than stored: a setting that looks configured and does nothing
#: is worse than one that was rejected.
MODES_THAT_USE_MODELS = (graph.SINGLE, graph.MODEL_PANEL, graph.POOL)

#: Where each half of a resolved assignment came from. Returned, never inferred.
FROM_PLAN = "plan"
FROM_STORE = "store"


class StoreError(Exception):
    """Refused. A store that accepted this would be describing something else."""


class Connection(sqlite3.Connection):
    """A connection that carries its own lock.

    A subclass rather than an attribute on `sqlite3.Connection`, because the C type takes no
    arbitrary attributes — found by it raising `AttributeError` on the first attempt.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runner_lock = threading.RLock()


@contextmanager
def _locked(db: sqlite3.Connection):
    """Hold the connection's lock. Every entry point takes it, including the read-only ones.

    Readers too, because a read that lands between the `DELETE` and the `INSERT` of an assignment
    edit would see a node with no models and report it as "unassigned" -- which is a different fact
    from the one that is true a millisecond later.
    """
    lock = getattr(db, "runner_lock", None)
    if lock is None:                            # a connection this module did not open
        yield
        return
    with lock:
        yield


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the store, with every pragma set **on this connection**.

    Three of the five are per-connection state and reset on reconnect; two live in the file. Getting
    that backwards is how a `REFERENCES` clause ends up enforcing nothing, which is exactly what an
    independent seat found in the first draft of this schema:

    ```
    foreign_keys default -> 0
    orphan turn accepted -> [('ghost', 0)]
    ```
    """
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    # `check_same_thread=False`, and a lock to make that safe. The server is a
    # `ThreadingHTTPServer` -- **every request is handled in its own thread** -- so a connection
    # bound to the thread that opened it raises `ProgrammingError` on the first console edit.
    #
    # Found by driving the real server, not by a unit test: every refusal that fires *before*
    # touching SQLite returned 409 correctly, and everything that reached the database returned
    # 500. A test that exercised the store directly would have passed on both.
    #
    # A lock rather than a connection per thread, because the design already declares **one writer**
    # (`docs/DATABASE.md`): serialising is the honest implementation of a rule that is already
    # stated, where a pool of connections would quietly permit what the design says is unsupported.
    db = sqlite3.connect(str(file), check_same_thread=False, factory=Connection)
    db.execute("PRAGMA journal_mode = WAL")        # the file's
    db.execute("PRAGMA foreign_keys = ON")         # per connection, OFF by default
    db.execute("PRAGMA busy_timeout = 5000")       # per connection
    db.execute("PRAGMA synchronous = NORMAL")      # per connection; resets to FULL
    _migrate(db)
    return db


def _migrate(db: sqlite3.Connection) -> None:
    """Ordered, and refusing a version from the future rather than guessing at it."""
    found = db.execute("PRAGMA user_version").fetchone()[0]
    if found > SCHEMA_VERSION:
        raise StoreError(
            f"this store is at schema {found} and this runner speaks {SCHEMA_VERSION}. A newer "
            f"store may hold columns this version would drop on write; upgrade the runner rather "
            f"than opening it.")
    if found < 1:
        db.executescript("""
            CREATE TABLE models (
              id           TEXT PRIMARY KEY,
              vendor       TEXT NOT NULL,
              name         TEXT NOT NULL,
              transport    TEXT NOT NULL,
              command_json TEXT NOT NULL DEFAULT '[]',
              endpoint     TEXT NOT NULL DEFAULT '',
              key_env      TEXT NOT NULL DEFAULT '',
              note         TEXT NOT NULL DEFAULT ''
            );

            -- `ordinal` because the order of a list is load-bearing: a pool's seeded choice and a
            -- model panel's ask ids both depend on it, so a set would lose something real.
            CREATE TABLE node_assignments (
              node_id  TEXT NOT NULL,
              ordinal  INTEGER NOT NULL,
              model_id TEXT NOT NULL REFERENCES models(id),
              PRIMARY KEY (node_id, ordinal)
            );

            -- One model per seat. A seat is one voice; a list would be a panel inside a panel.
            CREATE TABLE seat_assignments (
              seat     TEXT PRIMARY KEY,
              model_id TEXT NOT NULL REFERENCES models(id)
            );
        """)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    db.commit()


# ── the registry ──────────────────────────────────────────────────────────────────────────────

def save_registry(db: sqlite3.Connection, registry: models_mod.Registry) -> None:
    """Replace the stored registry with this one.

    `reach` and `leaves_this_machine` are **not** written, and there is no column for them.
    `models.py` computes both and strips them on save, with the reason on the line that does it:
    *"storing them would let a stale label outlive the truth."*
    """
    with _locked(db), db:
        db.execute("DELETE FROM models")
        db.executemany(
            "INSERT INTO models (id, vendor, name, transport, command_json, endpoint, key_env, "
            "note) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(m.id, m.vendor, m.name, m.transport, json.dumps(list(m.command)),
              m.endpoint, m.key_env, m.note) for m in registry])


def load_registry(db: sqlite3.Connection) -> models_mod.Registry:
    """Read it back, **through `models.validate`**.

    Every row goes through the same validator a file entry does. The database enforces identity and
    referential integrity and nothing else — a `CHECK (transport IN ('cli','api'))` would be coarser
    than `validate`, which enforces the real biconditionals, and two validators that disagree is
    worse than one that is authoritative.
    """
    with _locked(db):
        rows = db.execute(
            "SELECT id, vendor, name, transport, command_json, endpoint, key_env, note "
            "FROM models ORDER BY id").fetchall()
    return models_mod.Registry(models=tuple(
        models_mod._model_from({
            "id": r[0], "vendor": r[1], "name": r[2], "transport": r[3],
            "command": json.loads(r[4]), "endpoint": r[5], "key_env": r[6], "note": r[7]})
        for r in rows))


# ── the assignment ────────────────────────────────────────────────────────────────────────────

def _check_node(node_id: str, model_ids: Sequence[str]) -> None:
    node = graph.BY_ID.get(node_id)
    if node is None:
        raise StoreError(f"no node {node_id!r} in this flow")
    if not model_ids:
        return
    if node.mode not in MODES_THAT_USE_MODELS:
        raise StoreError(
            f"node {node_id!r} is mode {node.mode!r}, which does nothing with a model list — "
            f"{graph.RUNNER} asks nobody, {graph.FOLLOWS} reuses the model from the node it "
            f"follows, and {graph.SEAT_PANEL}/{graph.SURVEY} route by seat. Storing this would be "
            f"a setting that looks configured and does nothing.")


def _check_seat(seat: str) -> None:
    # Every seat this runner defines, not only the ones a given run opens: a seat assigned now
    # must survive a later run that opens more seats, and refusing  because today's floor is
    # three would be a rule about this run leaking into a standing configuration.
    known = [s.name for s in policy.SEATS]
    if seat not in known:
        raise StoreError(f"no seat {seat!r}; this runner's seats are {known}")


def set_node_models(db: sqlite3.Connection, node_id: str, model_ids: Sequence[str]) -> None:
    """Assign a node's models, or clear them with an empty list.

    Clearing through an empty list rather than a `DELETE` route: this API has no `DELETE` verb, and
    adding one for a single case would be a second way to say a thing that already has one.
    """
    _check_node(node_id, model_ids)
    with _locked(db), db:
        db.execute("DELETE FROM node_assignments WHERE node_id = ?", (node_id,))
        for ordinal, model_id in enumerate(model_ids):
            try:
                db.execute(
                    "INSERT INTO node_assignments (node_id, ordinal, model_id) VALUES (?, ?, ?)",
                    (node_id, ordinal, model_id))
            except sqlite3.IntegrityError:
                # The foreign key. Refused by name, because "assigned a model the project does not
                # have" is a different problem from "assigned nothing" and must not read the same.
                raise StoreError(
                    f"no model {model_id!r} in this store; assign one the registry has") from None


def set_seat_model(db: sqlite3.Connection, seat: str, model_id: Optional[str]) -> None:
    _check_seat(seat)
    with _locked(db), db:
        db.execute("DELETE FROM seat_assignments WHERE seat = ?", (seat,))
        if model_id:
            try:
                db.execute("INSERT INTO seat_assignments (seat, model_id) VALUES (?, ?)",
                           (seat, model_id))
            except sqlite3.IntegrityError:
                raise StoreError(
                    f"no model {model_id!r} in this store; assign one the registry has") from None


def node_models(db: sqlite3.Connection) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    with _locked(db):
        rows = db.execute(
            "SELECT node_id, model_id FROM node_assignments ORDER BY node_id, ordinal").fetchall()
    for node_id, model_id in rows:
        out.setdefault(node_id, []).append(model_id)
    return out


def seat_models(db: sqlite3.Connection) -> Dict[str, str]:
    with _locked(db):
        rows = db.execute("SELECT seat, model_id FROM seat_assignments ORDER BY seat").fetchall()
    return {seat: model_id for seat, model_id in rows}


# ── resolution ────────────────────────────────────────────────────────────────────────────────

def resolve(plan: Mapping[str, object], stored: Mapping[str, object]
            ) -> Tuple[Dict[str, object], Dict[str, str]]:
    """Merge a plan's assignment with the store's, and **say where each one came from**.

    The plan wins where it says something; the store fills where the plan is silent. Returns the
    merged assignment and a ``key -> "plan" | "store"`` map beside it, because an override nobody
    can see is worse than no override — the console has to be able to show which source put an
    assignment there, and a merged dict alone cannot say.
    """
    merged: Dict[str, object] = {}
    source: Dict[str, str] = {}
    for half in ("node_models", "seat_models"):
        from_plan = dict(plan.get(half) or {})
        from_store = dict(stored.get(half) or {})
        combined = {**from_store, **from_plan}          # plan last, so the plan wins
        merged[half] = combined
        for key in combined:
            source[f"{half}.{key}"] = FROM_PLAN if key in from_plan else FROM_STORE
    return merged, source
