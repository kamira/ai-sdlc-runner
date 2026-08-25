# fable-seat — CHG-20260823-17 design review (conversation store)

Dispatched via the Agent tool on the fable model, against the brief at
[`conversation-store-brief.md`](conversation-store-brief.md), **before any code existed**.
Committed whole and unedited below.

---

## 1. VERDICT

`not sound`

## 2. The single worst thing in the brief

> "The `AskJournal` already writes every ask down before asking it, with the order and the result. The store is therefore **derived**, not a second source of truth: the journal remains what a resumed run reads, and the store is what a person reads afterwards."

This sentence is the keystone of the design and it is false on the brief's own definition, stated fourteen lines earlier. §1 defines a conversation as asks **and decisions** — "A person answering is as much a turn as a model answering, and a store that keeps only the model side has thrown away half of what a reader would come to it for." The journal does not contain the decisions. The only two writers to the journal in the entire codebase are `journal.record(...)` at `src/ai_sdlc_runner/engine.py:564` and `journal.answered(...)` at `engine.py:576` — both asks. Confirmations, rejections, and rulings go only to the in-memory `RunReport` (`engine.py:1144`, `1159`, `1166`, `1422`), which nothing persists; a mid-run instruction lives in `RunConfig.instructions` and surfaces only as text merged into later orders (`engine.py:493-500`). A store "derived from the journal" therefore contains **zero operator turns** — it is exactly the model-side-only store §1 says would have "thrown away half," and the claim of a single source is the design congratulating itself on avoiding a drift problem it has instead guaranteed: to hold decisions at all, the store must read a second source, or the journal must grow decision entries — either way the brief's stated architecture is not the one that can be built.

This is the house defect at maximum size: "derived from the journal" is a name standing in for a constraint the named source cannot keep.

## 3. Answers to the five questions

**Q1 — Is "derived from the journal" right?** No, on three counts, of which the brief admits only the smallest.

- (a) The admitted case: `run` without `--ask-journal` has no journal (`cli.py:358` — `journal = engine.AskJournal(args.ask_journal) if args.ask_journal else None`) and `run_id` is `None` (`engine.py:446-459`). No journal → nothing to derive → the conversation is lost, against a requirement of *every* conversation stored. (`serve` always has one — `cli.py:523` defaults it to `<token-dir>/asks`.)
- (b) The decisions case — see §2 above. The journal never held half the turns.
- (c) The overwrite case, which the brief does not mention: `AskJournal.record` overwrites `{ask_id}.json` unconditionally (`engine.py:564` → `_write`, `engine.py:172-175`). Ask ids are positional — `f"{len(report.asks):03d}-{node.id}"` (`engine.py:1217, 1288, 1378`). When a re-walk carries a new instruction, the same id is a "genuinely different question wearing the same id" — the journal's own docstring says so (`engine.py:156-170`) — and re-asking **destroys the previous order and answer at that position**. The journal is a resume mechanism keyed by position, not an append-only conversation log. A store derived from it holds the *latest* question at each position, never the conversation that actually happened. For a feature whose one purpose is "a person reads it afterwards," that is fatal.

The right design: turns (asks, answers, decisions, instructions) are written to the store **as they happen**, append-only, by the engine/server — with the journal remaining the resume mechanism. That makes the store a first-class log, not a derivation, and the brief's "two writers drift" objection does not apply because they record different facts: the journal records "what is the current question at position N," the store records "what happened, in order."

**Q2 — Is loopback-only the right test for the Mongo URI?** It is necessary and it is not sufficient, and the gap is worse than the three cases the brief lists. A `pymongo.MongoClient` given a loopback seed performs **topology discovery**: if `localhost:27017` is a replica-set member or a `mongos`, the driver reads the topology from the server and opens connections to every member it learns of — including remote ones — with no further consultation of the URI. The loopback test answers "local" about a URI while the driver connects off-machine. That is the second house defect verbatim: a coarse check answering safe about something it had not examined. The rule that actually constrains the client is: loopback host **plus `directConnection=true` forced on the client options**, refuse `mongodb+srv://` (it is a DNS seedlist lookup by construction), refuse multi-host URIs, refuse a URI that supplies `replicaSet=`. A unix socket path (`mongodb://%2Ftmp%2F...sock`) is genuinely local and should be *allowed*, not merely tolerated. The SSH-tunnel case should be accepted as out of scope and said so plainly: the server's own loopback bind (`server.py:56`) cannot stop a tunnel either; the threat model there — and it is the right one — is config-borne and browser-borne exfiltration, not a determined operator. `--store-remote allow` recording itself as a relaxation is the right shape, with the caveat in Q-further below about where it records during `export`.

**Q3 — Is `(project, run)` the right key?** No, as specified, on four counts.

- The run half collides: `run_id` is the resolved journal directory (`engine.py:446-459`), and `serve` defaults every run in a repo to the **same** directory, `.runner/asks` (`cli.py:523`; README quickstart uses exactly this). Two successive changes in one repo → same `(project, run)` → the second run's document overwrites the first conversation. The journal itself already behaves this way — "a second run restarted from `intake` and re-asked everything, overwriting the same files" (`engine.py:144-148`) — so the store inherits it.
- The run half is not a usable name: `str(self.journal.dir.resolve())` on this machine is `C:\Users\haruharu\...\asks`. As `<root>/<project>/<run>.json` that is an invalid filename on every platform (separators, colon). Any sanitisation or hashing mints a second, derived id — which the brief's own `run_id` docstring argues against ("a minted id would need storing somewhere"). The brief must say what the file is actually called; it does not.
- The project half is the house defect by name: defaulting to the plan file's parent directory means `--plan examples/plan.json` files the conversation under project **"examples"**, and every repo whose plan sits at the root files under the repo's directory name. A directory name constrains nothing. And `serve` takes no plan at all as a valid state (`cli.py:617`, no default, optional) — the brief does not say what the project is then.
- Resume under a different `--project`: same run, two documents, both claiming to be it, neither knowing of the other. The brief asks the question and proposes no answer. The answer should be: the project is recorded **in** the run's document at first write, and a resume that supplies a different project is refused by name, the same way a stale `run_id` on a decision is refused (`engine.py:1043-1049`).

The workable key: `(project, run-instance)` where a run instance is minted per walk (journal dir + a monotonically increasing walk counter stored beside the journal, or a timestamp) and the store never overwrites — a re-walk appends turns to the same instance, a fresh start is a new instance.

**Q4 — Is CSV-as-JSON-in-cells the honest lossy form?** The form is right — flattening nested keys into per-row-varying columns would be worse, and the brief is correct to refuse it. There are two worse-than-useless cases it misses:

- **Formula injection.** The cell content is model-produced text. A cell beginning `=`, `+`, `-`, `@`, or a tab/CR variant executes as a formula when the file is opened in Excel — `=HYPERLINK(...)` is an exfiltration channel — and "for a spreadsheet" is this export's stated purpose, in a project whose standing constraint is local-only. Cells must be defused (prefix `'`, or space-prefix dangerous leading characters) and the brief must say so.
- **Silent truncation.** Excel's cell limit is 32,767 characters; a full work order serialised into one cell routinely exceeds it, and Excel truncates without error — loss beyond the declared loss, invisible exactly where the brief promised visibility.

Also: "say in the export itself that it is lossy" has no honest mechanism inside CSV — a comment row is a data row (CSV has no comments), and a note row will be read as a record by any consumer. Put the notice in the header naming (e.g. a `lossy_json` column name) or refuse to promise in-band annotation.

**Q5 — What in this brief is a name standing in for a constraint?**

1. **"Derived from the journal"** — the source lacks half the defined turns and overwrites the other half on re-walk (§2, Q1).
2. **`--project`, defaulting to a directory name** — a project is asserted by where a file happened to sit (Q3).
3. **"The Mongo URI's host must be loopback"** — "loopback" names locality the driver does not keep once topology discovery runs (Q2).
4. **"Written with owner-only permissions where the platform offers them"** — "where the platform offers them" is the coarse check answering safe unexamined: the README concedes `chmod 0600` "does little on Windows" (README, token paragraph), and for the `mongo` backend the runner sets no permissions at all — the data's protection is whatever the mongod's auth is, typically nothing on localhost. One sentence is doing safety work for three backends and holds for at most one.
5. **"Records itself as a relaxation in the run report"** — see further findings: for `export`, and for any store write after the report is sealed, there is no run report to record into. The mechanism's name outlives its availability.
6. Milder, and the brief half-admits it: the **`file` backend as "a NoSQL document store"** — the user asked for a NoSQL DB and the *default* hands them a directory, justified by argument-from-definition. The brief refuses silent fallback between backends and then makes the fallback the default. Defensible, but it should be named as the choice it is: the default satisfies "store," not "db," and the document should say the user accepted that or didn't.

## 4. Further findings

- **The relaxation has nowhere to live for export.** `export(document, fmt)` runs outside any walk; `RunReport.relaxations` (`engine.py:290-291`) exists only during one. If `--store-remote allow` also governs *reading* from a remote store at export time — and it must, or export is the unguarded path to the same remote — the brief's "records itself as a relaxation in the run report" is unimplementable for exactly the invocation most likely to use it. The store document itself needs a relaxations field.
- **"Must not be silent" has no named mechanism.** "A failed store write must not fail a run … and must not be silent either" — where does it speak? If into `RunReport`, the write ordering matters (the store presumably writes at end-of-walk, after the report is complete); if to stderr, `serve` operators never see it. The brief should name the field and the moment, or this is a sentence nothing will check — precisely how "one project, one runner" shipped (defect log, task 10).
- **Ordering breaks past 999 asks.** Ask ids are `%03d`-prefixed (`engine.py:1217`) and `AskJournal.entries()` orders by filename sort (`engine.py:137-138`). The 1000th ask sorts between `100-` and `101-`. `max_steps` is 200, but a step can be many asks (four seats per panel, panel reruns, per-model panels), so 1000 is reachable. A store that presents "the ordered sequence of turns" inherits an ordering that silently goes wrong at scale — the defect-log's own lesson is that the one-module demo will look fine.
- **Markdown export's fenced JSON can be broken by its content.** An answer containing a ``` sequence inside a string terminates the fence early. Use a longer fence or indent; say so in the design, since "for reading" is the format's whole claim.
- **The README sentence the preamble mentions:** the brief says this change is the test of "reviews happen before changes land." As of this review the store code does not exist anywhere in `src/` (no hits for `conversation|tinydb|pymongo|store-remote`), so the practice is being followed here. The sentence can stay only if this remains true at merge; the ledger does not enforce it (README, *Known gaps*).

## 5. What I could not check, and what I would need

- **pymongo topology-discovery behaviour** (Q2) is asserted from knowledge of the MongoDB driver spec, not demonstrated here — no network access and no mongod on this machine. To check: a local replica-set config listing a remote member, `MongoClient("mongodb://localhost:27017")` without `directConnection`, and a packet capture or `client.topology_description` showing the remote member being contacted.
- **Excel's exact injection and truncation behaviour** by version — asserted from documented limits (32,767 chars; `=`-prefix execution), not run. A generated CSV opened in a current Excel would confirm both.
- **Whether `serve`'s re-walk-per-approval still overwrites journal entries when an instruction arrives mid-run** — I verified the write path is unconditional overwrite (`engine.py:564`, `172-175`) and the docstring describes the changed-order re-ask; I did not drive a live `serve` session to watch a file change. A run of the `examples/` plan with one mid-run instruction, diffing `.runner/asks/000-pm_plan.json` before and after, would show it.
- **The other seat's brief-round documents** (`docs/design/reviews/`) for whether any of this was already adjudicated — deliberately not read, per the independence instruction.
