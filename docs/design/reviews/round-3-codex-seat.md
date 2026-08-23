# Round 3 review — CHG-20260823-11 (codex-seat)

**T1 — FAIL.** Round 2 introduced or preserved three defects in its corrections:

1. Task 11 can be completed without implementing failure paths: merely writing why the console is happy-path-only satisfies its done-when. That contradicts the requirement to show the “whole flow” and is exactly a non-doing implementation satisfying the task. Evidence: `docs/changes/CHG-20260823-11.md:62`, `docs/changes/CHG-20260823-11.md:190`.
2. Task 12 replaces missing semantics with instructions to decide them later. It does not state whether `main` and `follows` refer to roles or node IDs, assign modes to the 23 nodes, or name which node kinds may use each mode. Two builders can make incompatible choices while satisfying the prose by documenting their respective choices. Evidence: `docs/changes/CHG-20260823-11.md:209`; current structural kinds and fields: `src/ai_sdlc_runner/graph.py:45`, `src/ai_sdlc_runner/graph.py:50-75`.
3. Task 1’s correction identifies two governance decisions but assigns neither a task nor an answer. “Must be written down” does not say who decides them or what acceptance closes them. The correction therefore names consequences without producing a buildable decision. Evidence: `docs/changes/CHG-20260823-11.md:180`, `docs/changes/CHG-20260823-11.md:219-229`.

The other round-2 corrections checked here are supported: terminal completion does set `halted_at`; confirmations are counted and consumed; non-seat voices are refused by `policy.adjudicate`. Evidence: `src/ai_sdlc_runner/engine.py:631-642`, `src/ai_sdlc_runner/engine.py:668-678`, `src/ai_sdlc_runner/engine.py:719-722`, `src/ai_sdlc_runner/policy.py:649-655`.

**T2 — NOT BUILDABLE.** The vocabulary is closed, but its semantics are not. The record says the referent type “is stated” rather than stating it; says all 23 nodes receive modes without giving the mapping; and asks validation to decide “which kinds may be a panel” without supplying the validity matrix. It also leaves unclear whether non-asking runner nodes are `single`, whether `seat_panel` requires role `seat`, whether `model_panel` requires a decision node, whether `pool.main` is a role or node, whether `follows` may chain or cycle, and whether irrelevant references must be absent. Evidence: `docs/changes/CHG-20260823-11.md:209`; the present graph has only structural kind, role, successors, branches, and `answer_decides`: `src/ai_sdlc_runner/graph.py:45-75`; validation has no execution-mode rules: `src/ai_sdlc_runner/graph.py:159-194`.

Two competent builders could therefore produce incompatible graphs—especially for `pm_plan`, `qa_verify`, `pr`, runner-owned nodes, and the `engineer_build`/`engineer_selfverify` relationship—without inferring from IDs or branch shape. The record itself still calls several of those cases unsettled. Evidence: `docs/changes/CHG-20260823-11.md:400-410`.

**T3 — NO.** Neither question is answerable from the record.

For confirmations, the existing mechanism is a preloaded, per-gate counter spent when the gate is reached, with audit text and unspent reporting. Nothing establishes whether a later suspension decision becomes that same counter entry or is an atomic continuation token with a separate audit record. Evidence: `src/ai_sdlc_runner/engine.py:575-590`, `src/ai_sdlc_runner/engine.py:631-642`, `src/ai_sdlc_runner/engine.py:668-678`; unresolved explicitly at `docs/changes/CHG-20260823-11.md:222-226`.

For run identity, neither `RunConfig` nor `RunReport` currently supplies one, and the record does not choose whether it is minted by the engine, HTTP server, journal, or caller—or define its persistence and uniqueness boundary. A builder would invent both the authority and lifecycle. Evidence: `docs/changes/CHG-20260823-11.md:227-229`; repository support beyond the journal-directory observation is **not substantiated**.

**T4 — STOP REVIEWING.** Round 1 produced nine substantive corrections. Round 2 found seven material correction problems in its own account, including three defects introduced by round 1’s fixes. Round 3 finds three defects in round 2’s changes. Evidence: `docs/changes/CHG-20260823-11.md:342-386`; both prior rounds split and failed: `docs/design/reviews/README.md:8-16`.

The raw count is declining, but the load-bearing correction—task 12—has again converted missing decisions into prose that still requires the builder to decide them. Another prose round is therefore not the best next action. Build task 12, but first make its implementation choices explicit as part of that task’s governed design/confirmation step. Executable constructors, validation failures, and tests will expose ambiguity more cheaply than another retrospective correction layer.

**T5 — HIGHEST COST: WRONG EXECUTION-MODE AUTHORITY.** If execution mode and its relationships are modeled incorrectly, every later dispatch, panel, follow-model, adjudication, configuration, and UI decision will be built on the wrong graph contract. That would require migration across the graph, engine, policy, API, persisted configuration, and front end. Evidence: task 12 is the dependency for tasks 4 and 5 at `docs/changes/CHG-20260823-11.md:194-197`; current engine behavior still infers seat panels from role and treats every other role as a single ask: `src/ai_sdlc_runner/engine.py:685-709`, `src/ai_sdlc_runner/engine.py:724-730`.

ROUND 3: fail  
NEXT: build task 12
