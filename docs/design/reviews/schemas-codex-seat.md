# codex-seat — CHG-20260823-21 (the schema design)

Dispatched via `codex exec --sandbox read-only` on
[`schemas-brief.md`](schemas-brief.md). Committed whole and unedited below.

---

# VERDICT: `not sound`

The catalogue is not a trustworthy description of the implemented shapes. One advertised closed schema is open at its outer boundary, one documented structured schema accepts bodies that can overwrite its structural fields, several process-boundary schemas are missing entirely, and the proposed SQLite schema claims migration versioning it does not execute.

## Single worst schema

**Conversation document + turn — broken.**

`Turn.as_dict()` writes structural fields first and then expands the arbitrary body:

```python
return {"seq": self.seq, "kind": self.kind, "at": self.at, **self.body}
```

([conversations.py:255](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:255))

Therefore body keys can overwrite `seq`, `kind`, or `at`. Meanwhile `Conversation.turn()` validates only the original `kind`, then accepts unrestricted `**body`:

([conversations.py:680](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:680))

```python
conversation.turn("note", seq=999, kind="closed", at="false")
```

produces a stored turn whose structural identity disagrees with the values allocated and checked by `Conversation`. The catalogue’s per-kind body table is consequently descriptive convention, not a schema. No code enforces required, forbidden, or typed body fields for any of the nine kinds.

That is worse than ordinary openness: the payload can replace the envelope.

## Findings per schema

| # | Schema | Finding | Evidence |
|---:|---|---|---|
| 1 | Node | **needs change** | The fields match `Node`, but `kind` is an unrestricted `str`. `validate()` handles known kinds conditionally without ever checking membership in `{step, decision, loop, terminal}` ([graph.py:246-256](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/graph.py:246)). An unknown kind can pass if its other fields avoid those conditional branches. The shape admits a value the engine was not designed around. |
| 2 | Plan file | **broken** | The catalogue presents a compact plan shape, but CLI ingestion is open and unversioned: it takes `plan.get(...)` field by field and silently ignores unknown top-level keys ([cli.py:512-529](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:512)). It also omits several runtime configuration dimensions represented by `RunConfig`, and supplies no plan-version discriminator. |
| 3 | Node spec | **sound** | `_check()` rejects both missing and extra keys, and `render()` invokes it before use ([workorder.py:77-100](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/workorder.py:77)). This is genuinely closed on the dispatch path. Its weakness is lack of value-type validation, but the advertised key-set constraint is real. |
| 4 | Operation | **needs change** | `classify()` enforces `kind` and rejects a string `targets`, but extra keys are ignored and `description` is coerced with `str()`. Element types are not validated. Thus the documented three-field object is not its accepted shape. It needs either a closed validator or explicit extension semantics. |
| 5 | Work order | **sound** | It is constructed internally from a literal key set and guarded against drift ([workorder.py:113-137](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/workorder.py:113)). Node spec and nested policy verdict are checked closed first. |
| 6 | Answer contract | **broken** | The supposed contract is a set of node-specific conventions plus “anything else: any JSON object.” Intake accepts/coerces heterogeneous scalar/list values through `_strings()` ([intake.py:105-113](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/intake.py:105)). There is no version, discriminator, or common envelope, despite stdout being a process boundary. |
| 7 | Ask journal entry | **needs change** | The writer matches the catalogue ([engine.py:120-130](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:120)), but readers perform raw `json.loads()` and interpret keys opportunistically ([engine.py:132-170](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:132)). Unknown status values, malformed field types, extra keys, and incompatible historical shapes are neither rejected nor versioned. |
| 8 | Conversation document + turn | **broken** | Arbitrary body fields can overwrite `seq`, `kind`, and `at`; only the initial kind argument is validated. Required/permitted fields per kind are not checked ([conversations.py:248-256](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:248), [680-718](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:680)). Readers assemble arbitrary mappings rather than validate schema 1. `SCHEMA = 1` names a version but does not enforce it. |
| 9 | CSV export columns | **sound** | `CSV_COLUMNS` exactly matches the catalogue and `_csv()` emits that order ([conversations.py:782-786](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:782), [860-874](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:860)). Formula defusing and the oversize flag are implemented. |
| 10 | Model registry | **broken** | Individual model entries are closed by `_model_from()` ([models.py:239-254](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:239)), but the advertised registry envelope is not: `load()` reads `payload["models"]` and ignores every other top-level key ([models.py:270-276](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/models.py:270)). Therefore `{"models": [], "modelz": [...]}` is silently accepted. “Closed” is false for the registry as catalogued. No schema version exists. |
| 11 | Settings | **sound** | The fields match, and loading rejects unknown keys and invalid types ([settings.py:147-184](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/settings.py:147)). Ironically this is actually closed but is not marked closed in the catalogue. It remains unversioned. |
| 12 | Attachment manifest | **broken** | The entry dataclass matches the listed five fields, but persisted input is loaded using `raw.get("attachments", [])`; unknown envelope keys are ignored ([attachments.py:158-165](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/attachments.py:158)). Loaded IDs, sizes, instruction numbers, filenames, and media types are not revalidated against stored bytes. It has no schema version. |
| 13 | Run report | **needs change** | `as_dict()` emits the catalogued fields exactly ([engine.py:340-364](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:340)). But `state` is merely annotated `str`; no constructor or serializer check requires membership in `STATES`. This process/API output is unversioned, and many nested dict/list shapes are undocumented. |
| 14 | SQLite DDL | **broken** | The catalogue includes `PRAGMA user_version = …` ([SCHEMAS.md:237](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/SCHEMAS.md:237)), and the design says it “carries the database schema version” ([sqlite-only.md:176](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/design/sqlite-only.md:176)), but the actual DDL block ends its pragmas at `synchronous` ([sqlite-only.md:94-103](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/design/sqlite-only.md:94)). No `user_version` is assigned. The claimed migration constraint is only a name. |

The catalogue also contradicts itself at the top: it says “Two schemas are closed” while its table marks node spec, work order, and model registry—three ([SCHEMAS.md:6-20](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/docs/SCHEMAS.md:6)). Of those three, only the first two are actually closed as catalogued.

## Missing schemas

These are durable or cross a meaningful boundary and therefore belong in the catalogue:

- **RunConfig** — the real engine input contract, with substantially more fields than the plan catalogue exposes: effects, undeclared policy, artifacts, instructions, dispatch seed, panel reruns, intake history, approvals/rejections/rulings, journal and conversation ([engine.py:368-455](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:368)).

- **Runner YAML/config shape** — `load_config()` is a file/process configuration boundary, separate from both plan and Settings.

- **Approval, Rejection, and Ruling** — operator decisions crossing the server/engine boundary. The catalogue mentions their flattened conversation turns but not their input shapes or identity fields.

- **Ask / dispatch record** — `Ask` is distinct from the durable AskJournal entry and from the conversation `ask` turn; conflating them hides which fields are deliberately lost from `RunReport.as_dict()`.

- **Effect and EffectOutcome** — effect callbacks are runtime-only, but `EffectOutcome.as_dict()` is durable/report output with the fixed shape `frontier`, `already_met`, `applied`, `out_of_order` ([effects.py:72-89](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/effects.py:72)).

- **Intake Survey and option request/answer** — these cross agent/operator boundaries and are included inside reports. `Survey.as_dict()` adds computed `complete`, a field absent from the answer contract ([intake.py:71-102](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/intake.py:71)).

- **Conversation marker** — `.conversation` is durable resume state with `conversation_id` and `project` ([conversations.py:611-672](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:611)). It is particularly important because malformed or stale marker data controls reattachment.

- **Conversation assembled-read diagnostics** — `incomplete_lines`, `duplicate_seqs`, and write errors are additions to the read document but are not part of the catalogued document shape.

- **Server/operator state and HTTP request/response bodies** — `Operator` and `RunState` are the console’s process boundary. They should be catalogued if the HTTP/console interface is supported rather than purely internal.

## Delete or merge

- **Merge the plan-file schema with a serializable RunConfig input schema.** Today the plan page looks authoritative while the engine consumes a larger, partly CLI-derived contract. Documenting both independently will drift unless the relationship and transformations are explicit.

- **Merge the answer contract with per-node discriminated answer schemas.** “Anything else is any JSON object” is not a useful contract. Define a common versioned envelope and discriminated bodies for decision, module plan, module build, panel verdict, intake survey, and options.

- **Do not merge AskJournal and Conversation.** They intentionally have different mutability and fidelity. The catalogue is right on that distinction.

- **Delete `suspended` from RunReport if it merely re-encodes `state`, `halted_at`, and the applicable decision identity; otherwise formalize it as a named nested schema.** An undocumented arbitrary dict beside several related top-level fields creates multiple places for the same stop fact to disagree.

- **Delete duplicated `opened` data unless its purpose is explicitly archival.** The conversation header contains `project` and `run`, and the first turn repeats them. If both remain, readers need a mismatch rule; currently there can be two truths.

- **Do not add database constraints that only duplicate Python validation partially.** Either validate all reconstructed model rows through `models.validate()` on every read/write, or encode the full invariant transactionally. A lone `transport TEXT NOT NULL` is too coarse: it permits values the code rejects and does not enforce the CLI/API field biconditionals.

## Evolution

Only conversation documents carry a version, and even that version is written rather than enforced.

The following durable/process-boundary schemas should be versioned:

- plan files;
- agent answer envelopes;
- ask journals;
- model registry;
- settings;
- attachment manifests;
- run reports/API snapshots;
- SQLite database schema via an actually assigned and checked `PRAGMA user_version`.

Node, operation, node spec, and work order may evolve in lockstep with code if they never persist independently, but persisted work orders inside journals and conversations mean their evolution still needs either a nested contract version or a containing-document migration policy.

## Could not check

The full test suite could not start because the read-only environment has no usable temporary directory. `pytest` failed before collection with:

```text
FileNotFoundError: No usable temporary directory found
```

I could inspect all requested source and prior SQLite reviews, but could not run tests requiring filesystem writes, SQLite database creation, journal/attachment stores, or temporary subprocess files. Closing that gap requires a writable temporary directory. The SQLite implementation is still proposed, so migration, concurrency, constraint enforcement, corrupt-row handling, and round-trip validation cannot yet be tested.
