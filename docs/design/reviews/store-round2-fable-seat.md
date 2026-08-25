# fable-seat — CHG-20260823-27 round 2 (the corrections)

Dispatched via the Agent tool on the fable model, against
[`store-round2-brief.md`](store-round2-brief.md). Committed whole and unedited below.

---

# ROUND 2 — CHG-20260823-26, the corrections — fable seat

**Reviewed at commit `8936d0d` ("fix: the assignment store went to the seats…").** One process note before anything else: while this review ran, `src/ai_sdlc_runner/cli.py` and `src/ai_sdlc_runner/store.py` were **modified in the shared worktree, uncommitted** — patches that fix two of the defects named below, plus an untracked round-2 file from the other seat. Those edits are not part of CHG-26 and were not reviewed; every claim below was re-proven against a clean extraction of `8936d0d` (test suite there: **1053 passed, 2 skipped in 256s** — the record's count is true). The mid-review edits corroborate two findings; they do not answer them, because the correction under review shipped without them.

## 1. VERDICT: `not sound`

Findings 2, 5, 6, 7, 8 are genuinely fixed, in behaviour, with real tests. But fix 1 introduced a defect of the same class it was written to remove — `run` now *reads* the store and still does not *dispatch* to it, and a stored seat assignment makes `run` execute the model id as a program — fix 4 traded the brick for silently blessing a malformed store, fix 3 silently narrowed a three-route finding to two routes, and the test named for the decisive missing behaviour ("a stored assignment reaches an actual dispatch") performs no dispatch.

## 2. Round-1 findings

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | store governed no run | **partial** | **serve: answered in behaviour** — I drove the real `cmd_serve` (stubbed `serve_forever`, spy on `engine.walk`): console-assigned `pm_confirm→opus` arrived in the next walk's `cfg.node_models` as `{'pm_confirm': ['opus']}`, no restart; `build_factory()` is rebuilt per walk with the registry (cli.py:761-765). **run: the values arrive, dispatch does not change** — see New defect A. The only shipped tests for this finding assert on source text. |
| 2 | `DELETE FROM models` + write ordering | **answered** | Upsert + removal refused by name (store.py:219-238); `POST /models` writes the store **first** and a `StoreError` becomes a 409 before memory or `models.json` move (server.py:677-684). Tests test_store.py:343-373 are real behaviour, including the atomicity assert after a refused removal. |
| 3 | `version` presence-checked, never compared | **partial** | `/config/nodes` and `/config/seats` now compare and advance (proven: same version twice → 409 "answered version"; version advances). **But both round-1 seats named three routes** — fable F3: "`/config/nodes`, `/config/seats`, and `/models` accept any integer". Driven at HEAD: `POST /models` with `version: 999` → **200, twice, and the run version stayed 0** — no comparison, no bump, so other tabs are never woken about a new model. `docs/API.md:140-167` still lists `/models` under the unconditional "version does not match → 409" rule. |
| 4 | crash mid-migration bricked the store | **partial, new defect introduced** | The brick is fixed — reopening a half-built store recovers (test passes; reproduced). But the claimed mechanism is false and the recovery blesses garbage — see New defect B and §5. |
| 5 | corrupt file escaped as raw `DatabaseError` | **answered** | `connect` wraps both the open and `_migrate` into `StoreError` by name (store.py:119-137); test_store.py:76-82 is real. |
| 6 | `held` unlocked RMW | **answered** | `held_lock` wraps the registry read-modify-write in `POST /models` (server.py:668). Residue: `_reassign` writes `held["assignments"]`/`held["source"]` outside the lock — wholesale replacement from a fresh store read, so no lost update, but a reader between the two statements sees a new merge with the old provenance map. Cosmetic. |
| 7 | `if node is None: continue` | **answered** | `assert node is not None` with a message (test_store.py:157-158). |
| 8 | three of five pragmas | **answered** | All five asserted, including `busy_timeout` and `synchronous` (test_store.py:50-54). |

**The two locks (question 3): they cannot deadlock.** The only nesting is `held_lock → runner_lock` (`POST /models` holds `held_lock` across `save_registry`, which takes the connection's `runner_lock`). Nothing anywhere takes `runner_lock` and then `held_lock` — `store.py` has no reference to `held_lock`, and no store function calls back into the handler. `Runner._lock` is a third lock; it is never taken while `held_lock` is held (`/models` never calls `require_version` or `publish_config_change` — which is itself finding 3's residue). One direction, no cycle. `held_lock` is held across a file write (`models_mod.save`) — latency, not deadlock.

## 3. New defects introduced by the fixes

**A. (fix 1 — HIGH) `cmd_run` resolves the store and then cannot dispatch to it.** cli.py:566 at HEAD: `session_factory(config, seat_models)` — **no `registry`**; `cmd_run` never loads one from anywhere. Every model-routing branch in the factory is guarded by `registry is not None` (cli.py:185, 193). Proven against the factory exactly as `run` builds it:
- a stored **node** assignment: `factory(model="from-store")` → argv = **the default command**. The engine still keys panel verdicts and `report.asks` by model, so a stored 3-model panel in `run` is answered three times by one backend and **adjudicated as a cross-model majority attributed to models that never ran**. The code's own error message (cli.py:196-200) names this exact failure — "would send the work to the default and report it as {model}" — and the refusal is unreachable in `run` because it sits behind the `registry` guard.
- a stored **seat** assignment (`store.seat_models` returns model **ids**): `factory(seat="defect")` → `_Process(["opus"])` — `run` tries to **execute a program named `opus`**. In `serve`, `build_factory` passes the registry and the same id resolves to `claude -p`; the two commands the record says now "read the same file by default" read the same file and do different things with it.

The uncommitted worktree patch (a `config_registry` threaded into `session_factory`, its comment crediting "a seat reading the call") fixes exactly this — confirming the defect is real and that CHG-26 shipped without the fix.

**B. (fix 4 — MEDIUM) The recovery blesses a malformed store, then fails raw on first use.** Proven at HEAD, using the shipped test's own scenario (a version-0 file whose `models` table has only `id` — test_store.py:67 verbatim): `store.connect` stamps it `user_version = 1`, and the first `save_registry` raises **raw `OperationalError: table models has no column named vendor`** — past `cmd_serve`'s `StoreError`-only catch at startup (cli.py:737-740). `IF NOT EXISTS` matches a table by *name*: a name standing in for a constraint, installed as the fix for the previous brick. The shipped recovery test builds exactly this malformed shape and asserts **only the version number** — a check answering safe about the precise thing it was built to examine. (The realistic crash — interrupted `executescript`, fully-shaped partial tables — does recover correctly, which is why the brick counts as fixed.) The uncommitted `_verify_or_refuse` patch confirms this too.

**C. (fix 3 — LOW) check→write→bump on the config routes is not one critical section.** On the run routes, `_require_version` and the mutation share one `with self._lock` block; on `/config/nodes` the check (server.py:471), the store write, and `_bump` (481) are three separate acquisitions. Two truly concurrent same-version edits can both pass. I could not demonstrate it — 0/30 barrier-synchronized attempts over real HTTP — so this is a structural observation, not a proven behaviour: the sequential case (double-click, the case that mattered) is genuinely fixed and tested.

**D. (fix 1 — LOW, two residues in `run`)** A bare `runner run --plan x` now **creates `.runner/config.sqlite`** as a side effect (`connect` mkdirs and creates). And `cmd_run` computes `assignment_source` (cli.py:490-496) and never uses it — store-filled assignments apply with no printed line, while `serve` prints its override count; "neither source is silent" holds on one of the two commands.

## 4. The single worst thing still in the code

**cli.py:566 — `session_factory(config, seat_models)` with no registry.** A stored seat assignment makes `runner run` execute the model id as a program; a stored node panel is answered by the default backend under three model names and adjudicated as if it were cross-model. This is round 1's worst finding — configuration that displays as governing and does not govern — reintroduced by its own fix, one command over, with the additional property that the misattribution now reaches `report.adjudications` and the conversation record.

## 5. Change-record claims that are not true

1. **"The store governs runs" / Task 1 `[x]`** — true for `serve`, half-true for `run`: the store's assignment reaches `RunConfig`, and the dispatch it exists to govern either doesn't change (nodes → default backend, reported as the store's model) or breaks (seats → model id as argv). "Fix 1 changes what a run dispatches to" is, for `cmd_run`'s node half, false — it changes what the run *reports* dispatching to.
2. **Row 4: "the version set inside the same transaction" (also store.py:150)** — false, proven: `executescript` **commits** the enclosing transaction (simulated crash inside the `with db:` block left the tables committed at `user_version 0`). The comment even contradicts itself — line 152 states `executescript` autocommits, ten lines above a call to `executescript`. The brick is fixed by `IF NOT EXISTS` alone; the transaction half of the claim is prose.
3. **"The two tests whose absence let it through… exist now"** — the first (add-after-assign) genuinely exists. The second, `test_a_stored_assignment_reaches_an_actual_dispatch`, **performs no dispatch**: its docstring says "walks the engine and looks at which model was asked"; its body never calls `engine.walk`, opens no session, and asserts that `resolve()` merges and that `RunConfig` stores its own constructor argument (`monkeypatch` requested, unused). The decisive test is still missing — which is how new defect A shipped green.
4. **Row 3: "both call `require_version`"** — a silent narrowing. Round 1's F3, in both seats' words, covered three routes; `/models` still compares nothing and bumps nothing (proven, §2), and API.md still promises it does.

Claims verified true: 1053 passed / 2 skipped (reproduced); store-first write order in `POST /models`; `--assignment-store none` opts out; `run` and `serve` default to the same `.runner/config.sqlite`; `DATABASE.md` §0.1 no longer contradicts itself ("only one is persisted here" and "proposed" are gone); the "Not claimed" section is honest.

**On the two source-reading tests (question 4):** justified as *tripwires* — they encode the exact string that was round 1's critical defect, cheaply. Not justified as the *only* evidence, because the behavioural test was writable: I drove the real `cmd_serve` end-to-end in ~40 lines (stub `serve_forever`, spy `engine.walk`). And they are demonstrably brittle: a full-suite run in the live worktree failed `test_an_assignment_edited_in_the_console_reaches_the_next_run` solely because `cli.py` changed on disk mid-run and `inspect.getsource` desynced — a source-text test can fail, and therefore also pass, for reasons unrelated to behaviour.

## 6. What I could not check

- **Two processes on one store** — still no harness; the record correctly does not claim it.
- **Disk-full / read-only file** — not driven; the record correctly does not claim it.
- **The concurrent same-version race (defect C)** — structurally present, not demonstrable in 30 attempts; degree unproven.
- **The uncommitted worktree patches** (`config_registry` in `cmd_run`, `_verify_or_refuse` in `_migrate`) — deliberately not reviewed: they are not part of CHG-26. They should arrive as their own change, with tests that assert behaviour — the `_verify_or_refuse` hunk's comment already claims "no `executescript`, no autocommit" two lines above a surviving `executescript` call, so it needs its own round.
- **The other seat's round-2 file** sits untracked in this worktree; I did not open it — independence — though one comment in the uncommitted `cli.py` diff credits "a seat reading the call", so defect A has likely been found twice, independently.
