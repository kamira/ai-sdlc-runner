# codex-seat — CHG-20260823-17 design review (conversation store)

Dispatched via `codex exec --sandbox read-only` on the brief at
[`conversation-store-brief.md`](conversation-store-brief.md), **before any code existed**.
Committed whole and unedited below.

---

# VERDICT: not sound

## The single worst thing

> “The store is therefore **derived**, not a second source of truth: the journal remains what a resumed run reads, and the store is what a person reads afterwards.” — `docs/design/conversation-store.md:30-33`

The journal does not contain the proposed conversation.

`AskJournal.record()` stores only `ask_id`, `node_id`, `seat`, `status`, and `order`; `answered()` later adds `result` ([engine.py:119](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:119), [engine.py:125](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:125)). Operator approvals, rejections, rulings, and instructions live in `RunConfig`, `RunReport`, or in-memory server state, not in the journal ([engine.py:410](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:410), [engine.py:437](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:437), [server.py:165](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:165)). The brief defines those decisions as turns at lines 22–28, then selects a source that never recorded them.

This is not an edge case. It makes the central architecture unable to produce its declared document.

## Answers to the five questions

1. **“Derived from the journal” is wrong.**

   It loses more than journal-less runs:

   - CLI journals are optional: `journal = ... if args.ask_journal else None` ([cli.py:358](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:358)), and `--ask-journal` has no default ([cli.py:664](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:664)). Such a run has neither a durable source nor a `run_id` ([engine.py:459](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:459)).
   - The journal does not contain human decisions.
   - It also does not store the answering model. `_ask()` receives `model` but does not pass it to `journal.record()` ([engine.py:541](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:541), [engine.py:563](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:563)); model identity exists only in the transient `Ask` report object ([engine.py:1224](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:1224)).
   - `RunReport.as_dict()` omits ask results and model identities entirely ([engine.py:334](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:334)).

   The right design is a durable ordered event log containing both ask events and operator-decision events. The resume journal may be a projection of that log, or the existing journal must be extended into it. Calling a post-run reconstruction “derived” does not create missing events.

2. **Loopback-only is the right default policy, but the proposed test is insufficient and the Origin analogy is wrong.**

   A Mongo URI is not one HTTP origin. It can contain multiple seed hosts and can trigger topology discovery. Checking only the parsed URI hostname can approve:

   - a loopback seed whose replica-set metadata advertises non-loopback members;
   - a multi-host URI where only one host was examined;
   - `mongodb+srv`, whose actual endpoints come from DNS;
   - a Unix-socket or encoded-host form the generic URL parser does not interpret as intended;
   - a loopback SSH tunnel, where the socket endpoint is local but the data destination is not.

   `_loopback_origin()` validates one tightly constrained browser Origin and explicitly parses `scheme`, `hostname`, and `port` ([server.py:81](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/server.py:81)). It is not a suitable Mongo URI validator.

   For the non-relaxed mode, require `mongodb://`, exactly one loopback seed, no SRV lookup or replica-set discovery, and a direct connection—or enforce the actual socket destinations. Refuse malformed/ambiguous forms. An SSH tunnel cannot be identified from the URI; if “local” means ultimate data residency rather than the runner’s network peer, loopback can never prove the constraint and the brief must say so.

3. **`(project, run)` is not a sound key with the proposed meanings.**

   `run_id` is the resolved journal directory path ([engine.py:446](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:446)). That creates three failures:

   - A second fresh run in the same journal directory has the same key.
   - Deterministic ask IDs such as `000-<node>` are written directly as filenames, so the later run overwrites the earlier entries ([engine.py:116](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:116), [engine.py:1378](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:1378)). The proposed store cannot recover the first conversation.
   - Resuming the same journal under a different `--project` gives one run identity two project identities. If project participates in the primary key, it creates two documents for one run; if project is updated, categorisation history silently changes.

   There is also no safe file mapping: a resolved Windows path contains a drive colon and separators, yet the file backend promises `<project>/<run>.json` at brief line 46. `--project` is likewise proposed directly as a path component without validation, allowing separators, `..`, reserved names, and collisions.

   The right key is an immutable generated run identifier stored durably when the run starts. Project should have a stable identity and a separately editable/displayable name. Resume must verify the stored project identity rather than accept a new categorisation silently.

4. **JSON-in-CSV cells is reasonable, but the brief mislabels the problem and misses a dangerous case.**

   Nested JSON encoded into correctly quoted CSV cells is not necessarily lossy. It can preserve the nested value exactly if the schema also preserves type, ordering, nulls, and document-level metadata. Saying “lossy” does not specify what is actually omitted.

   The worse-than-useless case is spreadsheet formula injection. Conversation text is operator/model-controlled; a cell beginning with `=`, `+`, `-`, or `@` may be executed or interpreted when opened in spreadsheet software. RFC-compliant CSV quoting does not neutralize formulas. The export must either:

   - define CSV as raw data and prominently warn that it is unsafe to open directly in a spreadsheet; or
   - provide an explicitly spreadsheet-safe mode, document its escaping transformation, and stop calling that mode lossless.

   The brief also needs a fixed column schema and a declaration of which document-level fields CSV omits. “One row per turn” is not enough to implement or assess the export.

5. **Names standing in for constraints include:**

   - **“conversation”**: the selected source contains asks but not the human turns that the brief itself says are part of the conversation.
   - **“derived”**: there is no derivation capable of reconstructing absent events or model identities.
   - **“every conversation stored”**: CLI runs may have no journal, and store-write failure is explicitly allowed.
   - **“project”**: a plan parent-directory basename is a location-derived label, not a project identity.
   - **“run”**: a journal directory identifies storage location, not one execution; it can be reused.
   - **“local”**: loopback establishes the immediate socket peer, not Mongo’s discovered peers or ultimate data destination.
   - **“lossless” / “verbatim” JSON**: no document schema or canonical source is defined, so the claim cannot be tested.
   - **“owner-only permissions”**: the brief says only “where the platform offers them”; README already concedes that `chmod 0600` provides little on Windows ([README.md:273](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/README.md:273)). That is best effort, not a kept confidentiality constraint.
   - **“records itself as a relaxation in the run report”**: the report is not itself durable, and `RunReport.as_dict()` currently has no store configuration or project/run identity. Recording into an object that may disappear is not an audit record.

## Further findings

### The document schema is absent

The brief names a document key and turns, but does not define required fields, schema version, timestamps, decision attribution, completion state, backend metadata, write-error status, or ordering invariant. This makes “JSON document verbatim” uncheckable.

Evidence: the entire proposed export contract is `export(document, fmt)` at `docs/design/conversation-store.md:68-78`; no document schema appears elsewhere in the brief.

### Store timing and consistency are unspecified

A run can suspend and resume repeatedly. The brief does not say whether the store is updated:

- after every ask;
- after every operator decision;
- only when `walk()` returns;
- only at terminal completion.

If it writes only at the end, suspended/crashed conversations are not stored. If it rewrites after each walk, it needs idempotent update and concurrency semantics. The project’s defect log specifically identifies repetition and multi-run behaviour as where defects escaped simple demonstrations (`docs/defect-log.md:452-455`).

### “A failed store write must not fail a run” conflicts with “every conversation stored”

The brief requires non-fatal writes at lines 87–88 but defines no durable retry queue, failed-write marker, exit status, or recovery command. A warning printed once is not enough: after process exit, both the conversation and evidence of its loss may be gone.

The right rule is to keep execution outcome separate from archival outcome, while making archival failure durable and machine-detectable.

### The file backend repeats known storage hazards

The closest existing store:

- hashes user-controlled content before using it as a filesystem name ([attachments.py:131](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/attachments.py:131));
- explicitly prevents operator-provided names from becoming paths ([attachments.py:150](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/attachments.py:150));
- documents Windows path-length failure ([attachments.py:141](C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/attachments.py:141)).

The proposed `<root>/<project>/<run>.json` does the opposite with two unbounded identifiers, one user-controlled and one an absolute path. This repeats a defect class already recorded rather than applying its lesson.

### Backend equivalence is asserted, not designed

“Three backends” implies interchangeable behaviour, but the brief specifies no common guarantees for:

- duplicate-key handling;
- atomic replacement;
- concurrent writers;
- ordering/query semantics;
- schema migration;
- connection/write timeouts;
- authentication;
- acknowledgement/write concern;
- partial failure.

Without these, `file`, TinyDB, and Mongo are three names over materially different durability contracts.

## What I could not check

The implementation does not exist, so I could not check:

- the actual Mongo URI parser or whether topology discovery is constrained;
- file-path canonicalisation and traversal refusal;
- TinyDB/Mongo uniqueness and atomicity;
- CSV quoting and formula handling;
- schema validation and migration;
- write timing, retries, and failure reporting;
- permission behaviour on Windows and POSIX;
- whether exports round-trip.

To check those, I would need the proposed document schema, backend interface and write lifecycle, precise URI-validation algorithm, export column/schema specification, and executable acceptance tests covering journal-less CLI runs, repeated runs in one journal directory, project changes on resume, multi-host/SRV Mongo URIs, store-write failure, hostile project names, and formula-leading CSV cells.
