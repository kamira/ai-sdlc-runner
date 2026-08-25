# fable-seat — CHG-20260823-19 deliberation (SQLite only)

Dispatched via the Agent tool on the fable model, against
[`sqlite-only-brief.md`](sqlite-only-brief.md). Committed whole and unedited below.

---

# VERDICT: `sound with changes`

The proposition implements what was ruled — sqlite as the only conversation store, mongo and tinydb removed, files kept for server config, the model registry moved into SQLite — and it understood both new requirements. But it carries one safety regression (the stored `reach` column, which reverses a documented invariant of the very module it moves), one constraint that SQLite will not enforce as written (the `REFERENCES` clause), and two present-tense factual claims I checked and could not confirm. Those must change before implementation; none of them changes the direction.

---

## 2. The two new requirements, and whether §1 got it right

**My reading of the ruling:**

- 「file 只作為 server 的 config 才處理」 — files exist in this system only as server configuration; the conversation store stops being a file tree.
- 「sqlite 內容不僅限於紀錄，也包含 model 模型配置的紀錄儲存」 — the SQLite store's contents are not limited to the conversation log; the model-configuration records go in too. Note the singular: *the* sqlite's content includes both — one store, not two.

**§1 gets the outcome right and the principle wrong.** The apparent collision (the registry *is* server config, so sentence 1 keeps it in a file while sentence 2 moves it) does not need the "hand-written vs machine-maintained" theory to resolve, because **the ruling resolves it itself**: sentence 2 names the model registry explicitly. A specific instruction carves out of a general one. No interpretive principle is required, and inventing one creates the exact hazard the proposition warns about — a rule that will later be applied to files the person never ruled on.

The theory is also factually leaky, and the proposition knows it: `settings.json` is machine-written too — `settings.py:188-192` (`save`) is called by `cmd_settings` at `cli.py:270`. The proposition's own footnote calling settings.json "the awkward one" is the tell that the principle is not carrying the decision. If a principle is wanted for future cases, the accurate line is **"written by the running server while it serves"** vs "written outside any run": `server.py:565` writes `models.json` at runtime on a console POST; `settings.json` is written only by a separate, short-lived, human-driven CLI command; nothing in `src/` writes `runner.yaml` (verified — only `load_config` at `cli.py:36` reads it). Under that line, settings.json is unambiguous, not awkward.

The evidence claims in §1 that I could verify are all true: `server.py:565` calls `models_mod.save` (the only production call site), and `runner.yaml` has no writer anywhere in `src/`.

---

## 3. The single worst thing

> "`reach` is a **stored column**, not recomputed on read. It is what the console shows to say whether a model leaves the machine, and a value recomputed at display time can disagree with the value that was validated."

This reverses a documented safety invariant of `models.py` without acknowledging the reversal exists. `reach_of`'s docstring (`src/ai_sdlc_runner/models.py`): *"Where a model actually is. Computed, never declared."* And `save()` at the bottom of the same file strips `reach` and `leaves_this_machine` with the comment: *"both are computed; storing them would let a stale label outlive the truth."*

The proposition's own §3 says the `key_env` property "is in `models.py` and must survive the move intact" — while one section earlier it silently kills the module's *other* safety property. And the stored column is the worse design: `reach_of` is deterministic from `(transport, endpoint)`, so the stored value diverges from the computed one in exactly two cases — an endpoint UPDATE that forgets to recompute (the stale-label hazard the code names), or a future tightening of the classification rules (where the *recomputed* value is the truth an operator needs). In both, the console would show "safe" about something the current code would call external — this repository's second-most-frequent defect, written as a column. Bonus trap: `models._model_from` **refuses unknown fields by design**, so a loader that reassembles a payload containing `reach` gets a `ModelError`. The column is either dead or a refusal trigger.

What to do: drop it and recompute (validation already recomputes — `Registry.__post_init__` runs `validate`, which derives reach, on every load). If a column is wanted for SQL-side listing, it must be recomputed-and-compared on load with a mismatch refused by name — never trusted at display.

---

## 4. Answers to the five questions

**1. Is the hand-written vs machine-maintained reading right, and is settings.json on the correct side?**
The *outcome* is right: `models.json` → SQLite, `runner.yaml` and `settings.json` stay files. The *principle* is wrong, for the reasons in §2 above: the ruling's second sentence is a specific carve-out and needs no theory, and the theory misclassifies `settings.json` (machine-written at `settings.py:188`), which the proposition's "awkward one" footnote concedes. Settings.json stays a file — by the ruling's own category (it is server config), not by the proposed line. Replace §1's principle with: *the ruling names the registry; everything else that is server config stays a file; if a line is ever needed, it is "written by the running server while serving."*

**2. Same SQLite file or its own?**
**Same file.** The ruling's phrasing is singular — 「sqlite 內容…也包含」 describes one store whose content includes both. The blast-radius argument for separation is weak here: the registry is a handful of rows an operator can re-enter in minutes; the history is the irreplaceable part and it is in the file either way. Write contention is one row per console edit against WAL — nothing. Two conditions the proposition must add: (a) `serve` will now open/create the conversation store at startup *even when no `--project` is given* — today `serve` can run with no conversation store at all (`cli.py:689` loads the registry from `<token-dir>/models.json`, independent of `_store_flags`), and a database file created as a side effect of listing models must be said out loud; (b) the `--models` flag's disposition is unaddressed — it must die or repoint, and `serve` and `run` must resolve the same store file by default, or the "one file" simplicity is fiction across commands.

**3. Is removing `file` as a conversation store right, and is export real or consolation?**
The removal is ruled; the question is what is lost. Honestly: `runner export` (`json`/`markdown`/`csv` — verified real, `conversations.py` `FORMATS` and `cli.py:816`) is a **real replacement for post-hoc reading** and grep. It is a **consolation for `tail -f`** — nothing replaces watching a live run's store, though the serve console shows live state, which covers the operator who is present. Git-diffability is simply gone; an exported JSON can be committed, which is a workflow, not a property. The `sqlite3` CLI mitigates "survives this program being deleted." The residual loss is real and tolerable, and the proposition's §3 states it fairly. What §3 misses is in finding 3 below: the *silent default switch*.

**4. Is the schema correct? Name every guessed column.**
I ran the DDL on Python 3.11.9 / SQLite 3.45.1: it executes, and `PRIMARY KEY (conversation_id, seq)` genuinely refuses a duplicate (`IntegrityError: UNIQUE constraint failed`). `turns` matches `Turn(seq, kind, at, body)` exactly. `conversations` matches the header at `conversations.py:571-576` (`schema`, `conversation_id`, `project{id,name}`, `run`) — **except `opened_at`, which is a guess**: the header carries no timestamp anywhere. It is mintable at open and recoverable on import from the OPENED turn's `at`, but the proposition should say where it comes from. `models` table: `transport`, `endpoint`, `key_env` are real fields; **`reach` is worse than a guess** (§3 above); **`updated_at` is invented** — nothing in `models.py` produces or reads an update time (defensible for 「紀錄儲存」, but it must be named as new, and kept out of `_model_from`'s payload or it is refused). `vendor`, `name`, `command`, `note` presumably ride in `body_json` — the proposition should say so, since `validate` requires `vendor` and `name` non-empty and `command` is load-bearing for CLI models. And one thing the code needs that the schema check exposed — see finding 1.

**5. What is a name standing in for a constraint, and what is asserted about nonexistent code?**
The planted defect the questions predicted exists, and there is more than one:
- The stored `reach` column (§3) — a label standing where a computation is the constraint.
- **`REFERENCES conversations(conversation_id)` is decorative**: I verified that SQLite accepts an orphan turn with no conversation row, because `PRAGMA foreign_keys` is OFF by default *per connection*. The proposition names WAL, `busy_timeout`, and `synchronous` — and not `foreign_keys`. As written, the FK is exactly a name standing in for a constraint, in the schema block itself.
- *"`--store-root` **and the config file** answer that"* (§3, bootstrap bullet) — **claim about code that does not exist.** `config/runner.yaml` carries no store key (verified: `agent_timeout` and a commented `agent_command` only), and `load_config`'s output feeds only `session_factory`. Today, flags alone locate the store (`cli.py:434-443`).
- *"An existing `models.json` and existing `.jsonl` conversations both exist on this machine right now"* — **I could not find either.** No `.runner` directory exists in the repo root, in any worktree, or in the home directory (searched). If they exist elsewhere, the proposition must name the path; as written this is an unexamined factual claim propping up the migration section.
- *"`PRAGMA synchronous` chosen and documented"* — no level is chosen. Restating codex-seat's demand is not answering it. Name the level (`NORMAL` under WAL is the defensible choice) and the boundary it buys (process crash: safe; power loss: last transactions may roll back).

---

## 5. Further findings

**1. The bootstrap is sound — because the store's location comes only from flags, and it must stay that way.** `serve` has `_store_flags(pv)` (`cli.py:770`), so it can locate a SQLite registry without reading anything out of a store. There is no circularity. But the proposition's §3 says the config file shares this duty, which is false today (finding above) — and if `runner.yaml` *does* grow a `store_path` key, that is fine (a file locating the store is config); what may never happen is the store's location being read from the store. The proposition's own sentence — "'files are only server config' is doing real work and must not erode" — is right; its supporting claim is the part that's wrong.

**2. `models.load`'s missing-file semantics must survive the move.** `models.py` `load`: *"A missing file is an empty one; a malformed file is an error."* An SQLite loader inherits a new wrinkle: `sqlite3.connect` **creates** the file. "Missing store = empty registry" now means "listing your models creates a database" — acceptable, but it is a side effect `models.load` does not have today and it should be stated. A *corrupt* SQLite file must remain an error by name, never an empty registry, for the reason `load`'s docstring gives.

**3. The removal's refusal-by-name covers the wrong two names.** §2 says mongo and tinydb "refuse by name, with the change id." Right — but `file` is the one being removed that operators actually used, because it was **the default** (`cli.py:434`: `default="file"`). Two untreated cases: (a) `--store file` typed explicitly must refuse by name with the change id, same as the others; (b) far sharper, the operator who typed *nothing* silently switches stores, and any existing `.jsonl` tree at `.runner/conversations` simply stops appearing in `runner conversations` — old data made invisible with no message. That is "must not be silent" territory (defect-log: the silent-total-loss finding). The sqlite backend should notice an existing `file`-store tree at the default root and say so, pointing at `runner import`.

**4. What removal actually breaks, by grep:** production code touching the file backend is confined to `conversations.py` (FileBackend, `BACKENDS`, `backend()`) and `cli.py` (`--store` default and help, `--store-root` help text "where the file/tinydb store lives"). `tests/test_conversations.py` (37 tests) builds on a `FileBackend` fixture at line 23 and parametrizes refusal tests over tinydb/mongo (line 265) — all rewrites, not blockers; nothing outside those three files imports it. `server.py` holds no conversation store at all (its `store` is the *attachment* store, `cli.py:656`). Mongo/tinydb removal also deletes `local_mongo_uri`, `_unix_socket`, `_hardened`, `MONGO_OPTIONS`, `LOOPBACK_HOSTS` and their tests — the proposition's claim that this is "the entire surface" of the locality findings checks out against `conversations.py`.

**5. Small: "`enforces_unique_seq` becomes true rather than aspirational"** — that attribute lives on `_DocumentBackend`, which dies with the two backends being removed. The *property* becomes true via the PK; the *flag* the sentence names will not exist. Trivial, but this document is precise everywhere else.

**6. Baseline verified:** `pytest tests/test_conversations.py tests/test_models.py` — 106 passed on this machine, so every claim above is measured against a green tree.

---

## 6. What I could not check, and what I would need

- **Whether `models.json` / `.jsonl` stores exist elsewhere on this machine** — I searched the repo, all worktrees, and the home directory (depth-limited). A full-disk search was out of proportion; the proposition's author should name the path or strike the sentence.
- **Python 3.9 × Windows SQLite behavior** — only 3.11.9 / SQLite 3.45.1 is here. Irrelevant to JSON1 (the schema never asks — correct), but WAL-under-3.9's-bundled-DLL and the four CI cells still need the killed-process/reopen tests both prior seats demanded; nothing in this round discharges that debt.
- **Concurrent write contention in practice** (server thread saving the registry while a run appends turns — `ThreadingHTTPServer`, `server.py:45`): needs the built backend and a two-writer test; `busy_timeout` should get a named value, not just a named pragma.
- **The `runner import` command** — proposed, honestly labeled as proposed, unbuildable to check. Its "refuses rather than guesses" promise is the right shape; the refusal cases (duplicate conversation ids across trees, malformed rows, a models.json entry `validate` now rejects) are where the next seat should look.
