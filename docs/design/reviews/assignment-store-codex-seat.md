# codex-seat — CHG-20260823-25 (the assignment store)

Dispatched via `codex exec --sandbox read-only` on
[`assignment-store-brief.md`](assignment-store-brief.md). Committed whole and unedited below.

---

# VERDICT: not sound

## Single worst thing

> `node_models=plan.get("node_models", {}),`  
> — [cli.py](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:675)

The assignment store is not wired into subsequent runs. `POST /config/nodes` updates SQLite and the console’s cached display, but `make_config` continues giving the engine only the plan’s node assignments. Seat routing is similarly frozen when `session_factory(...)` captures the resolved seat map once at startup ([cli.py:721](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:721)).

That directly contradicts the comment that `_reassign()` prevents the console from showing something different from “the one the next run will use” ([server.py:417](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:417)). The console reports the new assignment and its source, while the next run uses another assignment. This is the repository’s recurring “mechanism exists but nothing calls it” defect.

## Findings

### Critical — persisted edits do not control execution

Evidence:

- `_reassign()` changes only `held["assignments"]` and `held["source"]` ([server.py:424](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:424)).
- `make_config` uses `plan.get("node_models", {})`, not the resolved assignments ([cli.py:675](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:675)).
- The session factory captures `assignments["seat_models"]` once, before serving ([cli.py:721](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:721)).
- Assignment POSTs never rebuild either object ([server.py:431](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:431)).

A restart happens to load the persisted settings, but edits made during the current server lifetime are display-only until restart.

### High — adding a model after making an assignment fails and splits the two registries

`save_registry` begins with:

> `db.execute("DELETE FROM models")`  
> — [store.py:178](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:178)

Existing assignment rows reference `models`, so foreign-key enforcement rejects that deletion. I reproduced this in an in-memory database:

```text
registry update: IntegrityError FOREIGN KEY constraint failed
registry now: ['a']
assignment now: {'pm_plan': ['a']}
```

`POST /models` makes this worse:

1. It first changes `held["registry"]`.
2. It writes the enlarged `models.json`.
3. It then calls the failing `save_registry`.
4. The unexpected `IntegrityError` becomes HTTP 500.

See [server.py:624](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:624). Afterward, memory and `models.json` contain the new model while SQLite does not. On restart, the nonempty SQLite registry wins, silently hiding the added file model.

This disproves the stated reason for writing both copies: the implementation itself creates “visible but unassignable” state.

### High — request versions are names standing in for concurrency control

Both assignment routes require that `version` merely be an integer ([server.py:614](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:614)). They do not:

- compare it with `runner.state.version`;
- increment the version after mutation;
- return a new version.

Two clients can therefore submit conflicting assignments with the same version. The per-connection `RLock` serializes the SQL, but both requests succeed and the last silently wins. The lock prevents simultaneous use of one connection; it does not implement the advertised optimistic concurrency rule.

The weak test at [test_store.py:270](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:270) checks only that an omitted version is refused. It never tries a stale integer.

### High — migration silently ignores later `models.json` changes

At startup:

- An empty store imports `models.json`.
- A nonempty store replaces the loaded file registry with the store registry.

See [cli.py:690](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:690).

Consequences:

- Second start: the store wins.
- Changed `models.json`: ignored without warning.
- Different nonempty file and store: store wins without comparison or conflict report.
- A prior partially failed `POST /models` writes the file but not SQLite; restart makes that apparent update disappear.

“Imported once” describes the mechanism, but nothing honestly tells the operator that a subsequently edited file is obsolete or conflicts with the authoritative store.

### Medium — the four refusals constrain only one ingress

The HTTP/store path refuses unknown nodes, ignored modes, unknown models, and unknown seats. The route tests genuinely exercise those refusals.

They are not global assignment constraints:

- Plan `node_models` goes directly into `RunConfig` without these store checks.
- Plan `seat_models` enters routing without the store’s seat validation.
- The documentation explicitly admits unknown plan assignment keys are ignored ([MODELS.md:325](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/MODELS.md:325)).
- A caller with a raw SQLite connection can bypass the Python name checks; the schema constrains model references but not node or seat vocabulary.

The change record’s unqualified “Four refusals” overstates their boundary.

### Medium — corruption and filesystem failures are not handled as operator errors

Handled:

- SQL statements inside `with db:` are transactional.
- WAL plus `synchronous=NORMAL` gives process-crash recovery for committed transactions.
- Future `user_version` is explicitly refused.
- SQLite coordinates transactions across processes; the Python `RLock` correctly protects one shared connection within one process.

Not handled:

- Corrupt databases can raise `sqlite3.DatabaseError`.
- Read-only files/directories and inability to create WAL/SHM raise `sqlite3.OperationalError`.
- Disk-full raises an SQLite exception.
- Lock contention after five seconds raises an SQLite exception.
- `load_registry` can raise `ModelError` for corrupt rows.

`cmd_serve` catches only `StoreError` around opening and loading ([cli.py:699](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:699)). These failures therefore escape as tracebacks rather than controlled refusals. HTTP-time failures become generic 500 responses.

The database page does acknowledge that killed-process and two-writer tests are owed, and that corruption is a single point of failure ([DATABASE.md:257](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/DATABASE.md:257)). It does not document the startup failure behavior.

### Medium — two runners are serialized by SQLite, not made operationally safe

The process-local `RLock` does nothing across connections or processes. SQLite/WAL provides transaction integrity, and `busy_timeout=5000` may allow short contention. After five seconds the request fails with an unclassified 500.

More importantly, each runner holds its own in-memory registry, resolved assignment and source map. A write by runner A does not refresh runner B. Runner B can display and run stale configuration, then overwrite it on its next edit.

The change record says two-runner safety is not claimed, but “one writer” is documentation, not an enforced constraint. There is no file lock or single-owner lease.

## What the change record claims that is not true

- **“Precedence, and never silent.”** Resolution itself is correct, but execution does not consume the refreshed result. The console can show `source: store` while the next run uses the plan/startup configuration.
- **“Everything configured through the routes persists and is usable.”** Node and seat edits do not affect runs until restart.
- **“Both [registry copies] … would prevent visible/unassignable divergence.”** Adding a model after any assignment causes exactly that divergence.
- **“Both take the run version like every other POST.”** They accept a field named `version`; they do not enforce its value or advance it.
- **“Four refusals.”** True only for store-mediated writes, not the plan ingestion boundary.
- **“1043 passed, 2 skipped.”** I could not independently reproduce this in the supplied environment.

## Tests

Real behavioral tests:

- Store round-trip and recomputation through model validation.
- Assignment ordering and clearing.
- Foreign-key rejection.
- Real HTTP thread-boundary test.
- Persistence across server restart.
- HTTP refusal status and error text.
- Pure `resolve()` precedence/provenance behavior.

Weak or misleading tests:

- `test_an_assignment_edit_needs_the_run_version_like_every_other_post`: checks only presence/type, not stale-version rejection or version advancement.
- `test_the_read_route_says_which_source_each_assignment_came_from`: proves display provenance, not that execution uses that assignment.
- `test_the_plan_cannot_be_overwritten_from_the_console`: checks the response only, not the following run.
- Restart persistence test: confirms stored values are displayed after restart, not dispatched.
- Registry tests never add a model after creating an assignment, missing the foreign-key failure.
- `test_every_mode_that_ignores_a_list_is_refused`: skips a mode when no current node represents it, so its “every mode” name is stronger than its check.
- Documentation/source-count tests establish that names and routes appear, not their operational wiring.

The next false-page-style test is the version test: a coarse “field is required” check answers “stale updates are safe” about behavior it never examines.

## What I could not check

The workspace is read-only and has no writable temporary directory. Consequently:

- `pytest`, including `tests/test_store.py` and the full suite, could not initialize its capture/temp files.
- I could not create an on-disk WAL database for real killed-process, disk-full, corrupt-file, read-only-file, or two-process contention tests.
- I could not drive the complete CLI over HTTP with a writable token/store directory.

I did run the registry/foreign-key failure against SQLite `:memory:` successfully. Completing the remaining checks requires a writable temporary directory and permission to create, corrupt, chmod/ACL, and kill processes owning disposable database files.
