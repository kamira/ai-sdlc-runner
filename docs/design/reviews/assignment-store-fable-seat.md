# fable-seat — CHG-20260823-25 (the assignment store)

Dispatched via the Agent tool on the fable model, against
[`assignment-store-brief.md`](assignment-store-brief.md). Committed whole and unedited below.

---

# VERDICT: `not sound`

Two of the findings below are critical, both proven by driving the real server, and each one falsifies a headline claim of the change record. Everything durable in the store survives — no finding here loses operator data at the SQLite level — but the change's central promise is not delivered, and one of its two features breaks the other.

---

## 2. The single worst thing

`src/ai_sdlc_runner/cli.py:675`, inside `cmd_serve`'s `make_config` — the config every console-started run receives:

```python
node_models=plan.get("node_models", {}),
```

**The stored assignment never reaches a run.** `cmd_serve` computes the merged `assignments` at line 716-718 and hands it to the server — but only for *display*. The run config reads the plan alone; `engine.py:1295` (`configured = list(cfg.node_models.get(node.id) or ())`) therefore only ever sees plan assignments. The seat half is barely better: `factory = session_factory(config, dict(assignments.get("seat_models") or {}), ...)` (cli.py:720-722) copies the merged seats **once at startup**, so a seat edited through the console takes effect only after a restart. A node assignment takes effect **never** — not in this process, not after restart, and not in `cmd_run` (cli.py:526, same `plan.get`, and `cmd_run` never opens the store at all).

So the operator assigns a model to `pm_plan`, `GET /config/nodes` answers `{"pm_plan": ["opus"]}` with `source: "store"` — and the next run dispatches as if nothing was configured. This is precisely the defect the module's own docstring says the project keeps recording: *"An override nobody can see is worse than no override"* — except here it is an entire configuration surface nobody can see through. The `node_assignments` table is written, displayed, and consumed by no run path: by the house's own doctrine, *"a table nothing reads or writes is a mechanism nobody invokes"* — this one is read only to be shown back to the person who wrote it.

---

## 3. Findings

### F1 — CRITICAL: stored assignments do not configure runs (above)
Evidence: cli.py:675 vs cli.py:714-718; engine.py:1295; cli.py:526 (`cmd_run`); factory built once at cli.py:720-722 from a startup copy. No test anywhere asserts a store assignment reaches a dispatch — which is why this survived.

### F2 — CRITICAL: adding a model breaks as soon as any assignment exists, and leaves three stores disagreeing
`store.py:177-183` — `save_registry` is `DELETE FROM models` + reinsert. With `PRAGMA foreign_keys = ON` and `node_assignments.model_id REFERENCES models(id)`, the DELETE violates the FK the moment one assignment exists. Proven over real HTTP:

```
add opus      200
assign node   200
add sonnet    500  IntegrityError: FOREIGN KEY constraint failed
assign sonnet 409  no model 'sonnet' in this store; assign one the registry has
GET /models shows: ['opus', 'sonnet']
```

Worse than the 500: `server.py:626-637` updates `held["registry"]` and writes `models.json` **before** `store_mod.save_registry` raises. After the failure the console *shows* sonnet, the file *has* sonnet, the store *doesn't* — the exact "visible and unassignable" split the code comments twice claim to have prevented. On restart, `make_handler` (server.py:462-468) sees a nonempty store and silently discards the file's registry, so sonnet vanishes from the console although `models.json` still lists it. There is no test that adds a second model after an assignment exists.

### F3 — HIGH: `version` on the config routes is presence-checked, never compared
`server.py:614-617` checks `isinstance(version, int)`; only the `/run*` routes call `_require_version` (server.py:352-356). `/config/nodes`, `/config/seats`, and `/models` accept any integer — proven: `{"version": 999, ...}` → `200`. The double-click / stale-tab protection the version exists for is absent on exactly the routes this change added. `docs/API.md:147-150` states unconditionally that a non-matching version gets 409; the change record says the routes are "version-checked". Both are names standing in for a constraint that is not there. The test (`test_an_assignment_edit_needs_the_run_version_like_every_other_post`, tests/test_store.py:271-275) asserts only that a *missing* version is refused — the change record admits its last too-weak test; this is the next one.

### F4 — MEDIUM: a crash mid-migration bricks the store permanently
`store.py:137-165` — `executescript` autocommits each `CREATE TABLE`; `PRAGMA user_version = 1` is a separate statement. A crash between them leaves tables at `user_version 0`; every subsequent open re-runs the script and dies with raw `OperationalError: table models already exists` — proven by simulation. No `IF NOT EXISTS`, no transaction, no `StoreError`, no recovery path. The same window makes two processes racing a fresh store fail the same way.

### F5 — MEDIUM: a corrupt or unreadable store crashes `serve` with a traceback
`store.connect` on a non-database file raises raw `sqlite3.DatabaseError: file is not a database` (proven). `cmd_serve` (cli.py:708-710) catches only `store_mod.StoreError`, so the operator gets an unhandled traceback instead of a refusal by name. The docstring boast that the future-schema case "refus[es] rather than guess[es]" covers the one failure that was tested; corruption, the likelier one for a kept file, was not examined — a coarse check answering safe about something it had not looked at.

### F6 — MEDIUM: `held` is mutated without a lock under `ThreadingHTTPServer`
The RLock lives on the SQLite connection (`store.py:66-91`); `held["registry"]`, `held["assignments"]`, `held["source"]` (server.py:412-429, 626-637) have none. `held["registry"] = held["registry"].add(model)` is an unlocked read-modify-write: two concurrent `POST /models` can each add to the same base registry and the last `save_registry` wins — one model lost with both callers told 200. GETs can also read `held` mid-`_reassign`. The change record's concurrency story ("a lock on a Connection subclass") secures the database and leaves the in-memory half of the same state unguarded.

### F7 — LOW: after the first migration, `models.json` is silently dead
cli.py:700-707: once the store is nonempty, the file is never read again (`registry = store_mod.load_registry(db)`), with no message. An operator who edits `models.json` — the file every previous version taught them to edit, and which `POST /models` still *writes* (server.py:630-631) — sees the edit ignored without a word. The registry has no `source` map; the provenance doctrine applied to assignments was not applied to the registry.

### F8 — LOW: the four refusals hold at the store boundary only
`_check_node`/`_check_seat` (store.py:207-227) cannot be bypassed via the routes or direct `set_*` calls — verified. But the plan file bypasses all four: a plan may assign a ghost model to a `runner`-mode node and nothing refuses it (mode-ignoring entries are silently unused; unknown models fail only at dispatch). Pre-existing, but the refusal table in the change record does not scope its claim.

---

## 4. What the change record claims that is not true

| Claim (docs/changes/CHG-20260823-25.md) | Reality |
|---|---|
| "Both take the run `version` like every other POST" / task 2 "version-checked" | Presence-checked only; `version: 999` → 200 (F3). `docs/API.md:147-150` repeats the false general rule. |
| The implicit whole-change claim — the persisted assignment is the project's "standing assignment" | It stands in the database and governs no run: nodes never, seats only after restart, `cmd_run` never (F1). |
| Task 6 "Every page updated" | `docs/DATABASE.md:28` still headlines §0.1 "**only one is persisted here**" and line 33 still says the models table is "**proposed**" — both contradicted by the same page's own status line 3. The page the record says was fixed after the too-weak-test incident still disagrees with itself. |
| "a model the registry does not have [is refused by] a foreign key" — presented as the FK's whole role | The same FK also makes `POST /models` fail with a 500 once anything is assigned (F2). The mechanism was tested in one direction only. |
| "1043 passed, 2 skipped" | True — reproduced (122s). |
| "Not claimed: two runners on one store are safe" | Honest, and correct to withhold. |

## 5. The tests

**Real (drive behaviour, would catch regressions):** the restart round-trip (`test_a_model_added_and_assigned_through_the_console_survives_a_restart`), the thread-boundary test, the future-schema refusal, validator-on-read, ordering kept, empty-list-clears, the 409 refusal matrix, plan-wins-over-console-clear. These exercise the real server over real HTTP and assert on responses.

**Weak:**
- `test_an_assignment_edit_needs_the_run_version_like_every_other_post` (tests/test_store.py:271) — the promised "next one". Its name asserts run-version agreement; its body asserts only that omission is refused. It passes today over a route that accepts any integer.
- `test_every_mode_that_ignores_a_list_is_refused` (tests/test_store.py:118-120) — `if node is None: continue`: a mode with no representative node would be silently skipped while the test still passes. Currently all four modes have nodes, so the skip is dormant, but it is a coarse check licensed to answer safe without examining.
- `test_the_pragmas_this_connection_needs_are_on_it` — checks three of the five pragmas `connect` sets; `busy_timeout` and `synchronous` are asserted nowhere.

**Missing, and decisive:** (a) add a second model after an assignment exists — would have caught F2 on the first run; (b) any test that a store assignment influences an actual dispatch — its absence is why F1 could ship with every test green.

## 6. What I could not check

- **Two processes on one store** — DATABASE.md:272 already owes this test; I did not build the harness. Needed: two `serve` processes, interleaved writes, and a statement of which one's `held` cache lies.
- **Disk-full mid-write** — needs fault injection (a full filesystem or an SQLite VFS shim). WAL + transactions make atomicity *likely*, but that is inference, not evidence.
- **The read-only-file result** — `connect` on a `chmod`-read-only file succeeded on this machine, but Windows `S_IREAD` is a weak proxy for a POSIX read-only file; the finding is "unexamined", not "broken".

The store module itself — schema, refusals, ordering, provenance in `resolve()` — is careful work. But the change persists an assignment nothing consumes and ships a registry writer its own foreign key breaks, and both were findable by the change's own stated method: driving the real server one step further than it was driven.
