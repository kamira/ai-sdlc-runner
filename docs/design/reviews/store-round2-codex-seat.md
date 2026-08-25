# codex-seat — CHG-20260823-27 round 2 (the corrections)

Dispatched via `codex exec --sandbox read-only` on
[`store-round2-brief.md`](store-round2-brief.md). Committed whole and unedited below.

---

# VERDICT: `not sound`

The two critical corrections are not both operational. `serve` now consumes stored routing, but `run` resolves model IDs without supplying the registry needed to dispatch them. The version correction also remains non-atomic.

## Round-1 findings

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Stored assignments governed no run | **partial** | `serve` correctly resolves node and seat assignments per walk at [cli.py:707](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:707>) and [cli.py:764](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:764>). `run` resolves the store into `RunConfig` at [cli.py:548](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:548>), but calls `session_factory` **without the registry** at [cli.py:566](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:566>). Consequently, `session_factory` cannot translate a stored node model ID into its command and falls through to the default backend. |
| 2 | `save_registry` deleted referenced models | **answered** | It now upserts at [store.py:220](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:220>), checks references before deleting stale rows, and the server writes SQLite before memory/file at [server.py:674](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:674>). The behavioral add-after-assignment test is at [test_store.py:343](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:343>). |
| 3 | Versions were presence-checked only | **partial** | Sequential stale assignment requests are refused by [server.py:352](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:352>) and tested at [test_store.py:376](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:376>). But check, mutation, and bump are three separate critical sections at [server.py:471](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:471>), [server.py:477](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:477>), and [server.py:481](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:481>). Two concurrent requests can both validate the same version. `/models` still only receives the global integer type check; it neither compares nor advances the version at [server.py:667](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:667>). |
| 4 | Half-migration permanently bricked the store | **partial** | `IF NOT EXISTS` makes the specific “tables exist, version 0” case reopen, so permanent bricking is answered. But `executescript` remains at [store.py:160](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:160>) and `user_version` is a later statement at [store.py:187](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:187>); they are not one transaction. Worse, the recovery accepts tables by name without verifying their shape. |
| 5 | Corrupt file leaked raw `DatabaseError` | **answered** | Database errors while opening or migrating are translated to `StoreError` at [store.py:119](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:119>) and [store.py:132](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/store.py:132>). The corrupt-file behavior test is real at [test_store.py:75](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:75>). |
| 6 | `held` was unlocked | **partial** | The registry RMW is serialized by `held_lock` at [server.py:668](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:668>). But `_reassign` writes `held["assignments"]` and `held["source"]` without it at [server.py:446](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:446>), and GET routes read the same state without it. The lock fixes one named RMW, not “in-memory state.” |
| 7 | Test silently skipped modes | **answered** | It now asserts that every ignored mode has a representative node at [test_store.py:147](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:147>). |
| 8 | Pragma test checked only three of five | **answered** | All five are asserted at [test_store.py:44](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:44>). |

## New defects introduced by the fixes

### CRITICAL — `cmd_run` resolves stored IDs but cannot dispatch them

`cmd_run` opens the assignment store and puts stored IDs in `cfg.node_models`, but never loads the registry and passes none to `session_factory`:

```python
engine.walk(cfg, session_factory(config, seat_models), enabled=True)
```

At [cli.py:162](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:162>), model-ID resolution happens only when `registry is not None`. Without it, the selected model is ignored and dispatch falls through to the seat/default command.

Thus `runner run` can record/select a stored model while another backend answers. This is the same class of critical defect as round 1: configuration appears connected but does not govern execution.

### HIGH — migration “recovery” blesses arbitrary malformed tables

The new test creates only:

```sql
CREATE TABLE models (id TEXT PRIMARY KEY)
```

at [test_store.py:57](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:57>). Migration sees the name, skips creation via `IF NOT EXISTS`, and marks the database schema version 1 without checking its columns.

I reproduced this entirely in memory:

```text
version 1
models_columns ['id']
OperationalError table models has no column named vendor
```

The recovery converts a visibly incomplete version-0 database into an officially version-1 database that fails on first use.

### HIGH — optimistic concurrency remains a TOCTOU check

`require_version()` locks only while comparing; the assignment write and `publish_config_change()` happen later. Two threads can follow:

```text
A: require version N → releases runner lock
B: require version N → releases runner lock
A: write
B: write
A: bump
B: bump
```

Both requests succeed, precisely the double-submit condition the version is supposed to refuse.

`POST /models` is worse: any integer—including stale integers—is still accepted, and adding a model does not bump the version. This contradicts [API.md:140](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/API.md:140>) and its statement that every state change advances the version at [API.md:211](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/API.md:211>).

### Lock ordering

I found no present deadlock cycle.

- `/models` takes `held_lock`, then `runner_lock` indirectly through store operations.
- Assignment routes take `runner_lock` for the version check, release it, then take `runner_lock` on the SQLite connection, release it, then reacquire the server runner lock to bump.
- No path holds the server runner lock or connection lock while acquiring `held_lock`.

So there is no opposing `runner_lock → held_lock` edge. The defect is insufficient atomicity and incomplete coverage, not deadlock.

## The single worst thing still in the code

`cmd_run` reports and records a stored model assignment but dispatches through a factory incapable of resolving that model.

The alleged behavioral proof is not behavioral. `test_a_stored_assignment_reaches_an_actual_dispatch` at [test_store.py:397](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:397>) never calls `engine.walk`, never opens a session, and never observes a backend. It constructs `RunConfig` and asserts that the ID is present. Its name stands in for the constraint it did not examine.

The two deliberate source-reading tests at [test_store.py:325](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:325>) and [test_store.py:424](</C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_store.py:424>) are defensible only as narrow architectural regression guards: they prohibit the exact old spelling. They do not prove dispatch behavior and are not substitutes for a real command/server run.

## False claims in the correction record

- “Both `run` and `serve` resolve per walk.” `cmd_run` resolves once, not per walk—there is only one walk—and fails to pass the registry required to use the result.
- “A stored assignment reaches an actual dispatch.” The named test does not dispatch anything.
- “Both call `require_version`.” `/config/nodes` and `/config/seats` do; `/models`, one of the round-1 routes identified by both seats, does not.
- “A config edit advances the version.” Model-registry edits do not.
- “Other tabs see” the version protection. Concurrent requests can both pass because validation and mutation are not atomic.
- “The version [is] set inside the same transaction” as table creation. `executescript` and the subsequent `PRAGMA user_version` are separate.
- “A half-migrated store recovers.” It reopens, but the supplied recovery test blesses a malformed `models` table and leaves the store unusable.
- “In-memory state is locked too.” Only the `/models` registry RMW uses `held_lock`; assignments, provenance, and GET reads do not.
- “1053 passed, 2 skipped.” I could not reproduce this in the supplied read-only environment.

## What I could not check

`pytest` could not initialize because no writable temporary directory exists:

```text
FileNotFoundError: No usable temporary directory found
```

For the same reason I could not run an on-disk WAL server, the full CLI, restart tests, killed-process tests, or a filesystem-backed real-HTTP race. I could inspect all named files, run read-only repository checks, and reproduce the malformed-migration failure using SQLite `:memory:`.
