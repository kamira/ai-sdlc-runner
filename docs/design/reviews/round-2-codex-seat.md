## R1 — partly

The corrections are uneven.

- **`policy.py` / `graph.py` “unchanged” contradiction — answered.** The false claim was removed, and the record now explicitly assigns the adjudication change to policy and execution-mode data to graph. The remaining problem is a new contradiction: §“three things the engine must learn” still specifies a blocking `Approver`, while task 1 specifies returning a suspended report for caller-driven resume. Those are different control-flow designs.
  Evidence: `docs/changes/CHG-20260823-11.md:140`, `docs/changes/CHG-20260823-11.md:150`, `docs/changes/CHG-20260823-11.md:154`, `docs/changes/CHG-20260823-11.md:174`, `docs/changes/CHG-20260823-11.md:212`

- **Mock-up node count — partly answered.** The correction accurately identifies the invented `next_module2` and the five omitted graph nodes. It does not reconcile this with the still-active requirement that the main screen show “the whole flow, every node,” and no task requires correcting the mock-up or ensuring `/flow` renders all graph nodes, including failure paths.
  Evidence: `docs/changes/CHG-20260823-11.md:40`, `docs/changes/CHG-20260823-11.md:56`, `docs/changes/CHG-20260823-11.md:229`, `docs/design/console-mockup.html:565`, `docs/design/console-mockup.html:580`, `src/ai_sdlc_runner/graph.py:108`, `src/ai_sdlc_runner/graph.py:119`, `src/ai_sdlc_runner/graph.py:126`

- **“Ends the process” — answered factually, partly answered architecturally.** The corrected explanation matches the implementation: the engine returns a halted report and the outer caller exits. But the record retains the incompatible live-blocking `Approver` design elsewhere.
  Evidence: `docs/changes/CHG-20260823-11.md:206`, `docs/changes/CHG-20260823-11.md:212`, `src/ai_sdlc_runner/engine.py:674`, `src/ai_sdlc_runner/engine.py:680`

- **§3 seat exclusion — partly answered.** The prose now excludes review seats from attributed carry-over, which answers the conceptual finding. It is not made a testable configuration constraint: task 3 still says only that round 2 carries both sides, `/config/panel` remains the named panel endpoint, and task 12’s execution modes do not specify separate retry/carry policies for seat panels.
  Evidence: `docs/changes/CHG-20260823-11.md:92`, `docs/changes/CHG-20260823-11.md:110`, `docs/changes/CHG-20260823-11.md:159`, `docs/changes/CHG-20260823-11.md:176`, `docs/changes/CHG-20260823-11.md:195`

- **Collapsed design-only claims — answered.** The task-table State column is now the declared authority, and the Type, Rollback, and Status language defer to it instead of independently asserting that nothing has been built.
  Evidence: `docs/changes/CHG-20260823-11.md:6`, `docs/changes/CHG-20260823-11.md:166`, `docs/changes/CHG-20260823-11.md:223`, `docs/changes/CHG-20260823-11.md:227`

- **Task 1 tightened done-when — partly answered.** It replaces the unsafe “wait in `walk`” acceptance language with a distinguishable suspended report and checks several bad answers. It still does not define the durable decision record, legal state transition, restart behavior, or atomic consumption needed to make “consumes exactly one recorded decision” demonstrable.
  Evidence: `docs/changes/CHG-20260823-11.md:174`, `docs/changes/CHG-20260823-11.md:206`, `src/ai_sdlc_runner/engine.py:575`

- **Task 2 tightened done-when — answered.** It explicitly binds the policy outcome to the engine caller, requires preservation of `undecided`, and requires unknown outcomes to raise. That directly closes the existing flattening behavior.
  Evidence: `docs/changes/CHG-20260823-11.md:175`, `src/ai_sdlc_runner/engine.py:570`, `src/ai_sdlc_runner/engine.py:572`, `src/ai_sdlc_runner/policy.py:642`

- **Task 4 tightened done-when — answered for the stated silent-underexecution finding.** A configured count differing from opened sessions must be refused. It remains dependent on task 12 defining valid execution configuration.
  Evidence: `docs/changes/CHG-20260823-11.md:177`, `src/ai_sdlc_runner/engine.py:701`

## R2 — not sound

The eight tasks are not all well-formed.

- **12 — not well-formed; load-bearing defect.** It names four modes and two references, but does not define their invariants: which modes require or prohibit `main`/`follows`, whether references must resolve, whether they can self-reference or cycle, whether `follows` must point to a pool execution, or whether role/capability compatibility matters. A validator could merely check enum membership and target existence while accepting nonsensical execution data.
  Evidence: `docs/changes/CHG-20260823-11.md:195`, `src/ai_sdlc_runner/graph.py:50`, `src/ai_sdlc_runner/graph.py:159`

- **13 — partly well-formed.** Blocking, recording a choice, and taking that branch are observable. It does not require refusal of an invalid choice, persistence across server restart, or exactly-once consumption; code with an in-memory boolean could satisfy its words without providing a reliable operator decision.
  Evidence: `docs/changes/CHG-20260823-11.md:196`, `src/ai_sdlc_runner/graph.py:114`, `src/ai_sdlc_runner/engine.py:724`

- **14 — partly well-formed.** Waiting versus running is observable, but the required snapshot schema, run identity, current node/gate, terminal state, and consistency point relative to SSE are unspecified. A two-valued status endpoint could pass while failing to rebuild the advertised view.
  Evidence: `docs/changes/CHG-20260823-11.md:197`, `docs/changes/CHG-20260823-11.md:54`, `docs/changes/CHG-20260823-11.md:183`

- **15 — not well-formed.** “Record who” is satisfiable with a caller-supplied string. No authentication or trusted identity source is specified, so server-side independence can still be enforced against a self-asserted identity—the same caption-level assurance in another form.
  Evidence: `docs/changes/CHG-20260823-11.md:198`

- **16 — well-formed in intent, but missing the atomicity mechanism’s observable test.** The listed duplicate, stale, mismatched, and concurrent cases can be demonstrated. The concurrency case must explicitly require one accepted transition and one refusal against durable shared state.
  Evidence: `docs/changes/CHG-20260823-11.md:199`

- **17 — not well-formed.** It permits either exemption or collision-proof storage without pinning the safety invariant. Exempting all `input_artifacts` from target scanning could hide an artifact path that genuinely names a prohibited target. It also overlooks the second pass, which scans every field as prose, so merely removing attachments from `_TARGET_FIELDS` does not prevent a `production` filename from tripping the word backstop.
  Evidence: `docs/changes/CHG-20260823-11.md:200`, `src/ai_sdlc_runner/engine.py:385`, `src/ai_sdlc_runner/engine.py:411`, `src/ai_sdlc_runner/engine.py:424`, `src/ai_sdlc_runner/policy.py:219`

- **18 — partly well-formed.** An edge or absent button is observable, but the task does not define rejection semantics per gate. A blanket edge from every rejection to `pm_plan` could satisfy it while discarding the graph’s existing local failure/rework routes.
  Evidence: `docs/changes/CHG-20260823-11.md:201`, `src/ai_sdlc_runner/graph.py:82`, `src/ai_sdlc_runner/graph.py:102`, `src/ai_sdlc_runner/graph.py:124`

- **19 — not well-formed.** “Size and type limits” supplies no limits or type policy; “defined behaviour” supplies no required behavior. Almost any implementation and documentation could claim completion.
  Evidence: `docs/changes/CHG-20260823-11.md:202`

## R3 — not sound

The cited code claims are mostly accurate:

- `engine.py:572` really does collapse every non-`pass` result to `fail`.
- `engine.py:674–678` sets the halted state and returns a report through `_finish`; the caller then returns it again.
- `engine.py:16` explicitly states that seat independence is not configurable.
- `policy.py:219` matches `prod` or `production` at path-like boundaries.
- `_TARGET_FIELDS` includes `input_artifacts`, and `_spoken_halt` sends those values through `policy.derive`.

Evidence: `src/ai_sdlc_runner/engine.py:16`, `src/ai_sdlc_runner/engine.py:385`, `src/ai_sdlc_runner/engine.py:412`, `src/ai_sdlc_runner/engine.py:572`, `src/ai_sdlc_runner/engine.py:674`, `src/ai_sdlc_runner/policy.py:212`, `src/ai_sdlc_runner/policy.py:219`

The corrections newly break or assert three things:

1. **Two incompatible task-1 architectures remain:** an engine-called approver whose server implementation waits, versus `walk` returning a suspended report for a later caller resume.
   Evidence: `docs/changes/CHG-20260823-11.md:150`, `docs/changes/CHG-20260823-11.md:174`, `docs/changes/CHG-20260823-11.md:212`

2. **Task 17 describes only the target-scanner half of `_spoken_halt`.** Every spec field is subsequently scanned as prose, so the proposed exemption does not necessarily fix the claimed failure.
   Evidence: `docs/changes/CHG-20260823-11.md:200`, `src/ai_sdlc_runner/engine.py:424`, `src/ai_sdlc_runner/engine.py:429`

3. **The record says the mock-up simulates “all of” the happy path while also admitting one simulated node does not exist.** More importantly, its interaction sequence is a linear surrogate, not the graph’s actual branch structure.
   Evidence: `docs/changes/CHG-20260823-11.md:40`, `docs/changes/CHG-20260823-11.md:231`, `docs/design/console-mockup.html:565`, `docs/design/console-mockup.html:580`

## R4 — partly substantiated

The split verdict and “does not pass” handling are internally honest: neither seat is presented as the winner, and the record labels the two verdicts separately.

Evidence: `docs/changes/CHG-20260823-11.md:237`, `docs/changes/CHG-20260823-11.md:242`

The claimed attribution is not fully checkable without the raw round-1 verdicts:

- That each item under “Found by both” was independently found by both: **not substantiated**.
- That each item under “Found by one seat” belongs only to the named seat: **not substantiated**.
- That both called decisions 1, 2, and 4 sound: **not substantiated**.
- That both flagged the uncorroborated hand-run: **not substantiated**.

Evidence: `docs/changes/CHG-20260823-11.md:247`, `docs/changes/CHG-20260823-11.md:279`, `docs/changes/CHG-20260823-11.md:301`, `docs/changes/CHG-20260823-11.md:331`

There is also an internal overclaim: the introduction to tasks 12–19 says both seats independently found that tasks 1–11 lacked the data or routes addressed by all eight additions, while the later attribution assigns several additions to only one seat. That separation is not accurate even on the record’s own terms.

Evidence: `docs/changes/CHG-20260823-11.md:188`, `docs/changes/CHG-20260823-11.md:281`, `docs/changes/CHG-20260823-11.md:288`

## R5 — not sound

Task 1 is not specified tightly enough to start safely.

The desired primary mechanism is still contradictory: §146 says `walk` calls an `Approver` and the server waits inside it, while task 1 and the corrected risk note say `walk` returns a suspended report and a caller later resumes it.

Even choosing the suspended-report version, the design is missing:

- A closed run-state machine and legal transitions.
- The persistent schema for a pending gate decision.
- An opaque decision/version token binding run, node, gate, phase, and suspension generation.
- Atomic exactly-once decision consumption.
- Restart/crash semantics between recording a decision and advancing the graph.
- Whether resume reconstructs from the beginning, a node checkpoint, or a serialized continuation.
- Interaction with existing counted `RunConfig.confirmed` entries and unspent confirmations.
- A requirement that no ask, effect, or successor node executes while suspended.

Evidence: `docs/changes/CHG-20260823-11.md:150`, `docs/changes/CHG-20260823-11.md:174`, `docs/changes/CHG-20260823-11.md:206`, `src/ai_sdlc_runner/engine.py:631`, `src/ai_sdlc_runner/engine.py:668`, `src/ai_sdlc_runner/engine.py:680`

## R6 — incomplete

Specific missing tasks or constraints:

1. **Resolve the task-1 architecture** by striking either the waiting `Approver` design or the return-and-resume design.

2. **Add a durable run-state/decision protocol task** covering state transitions, persistence, atomic consumption, restart recovery, and decision tokens.

3. **Tighten task 12 with a validity matrix** for every mode and reference field, including existence, prohibition, compatibility, and cycle rules.

4. **Add a trusted identity mechanism** to task 15; a submitted display name is insufficient.

5. **Make task 17 preserve both safety checks:** an ordinary attachment named `production/spec.pdf` must not halt merely because of storage metadata, while a brief genuinely naming a production target must still halt.

6. **Specify concrete attachment policy** for task 19: byte limits, allowed/detected types, filename normalization, content-addressed immutable identity, and exact missing/changed-file outcomes.

7. **Require the real graph—including every failure route—to drive `/flow` and the front end.** The present “whole flow” requirement has no corresponding done-when.

8. **Specify per-gate rejection routing** rather than allowing a universal `pm_plan` send-back.

Evidence: `docs/changes/CHG-20260823-11.md:56`, `docs/changes/CHG-20260823-11.md:150`, `docs/changes/CHG-20260823-11.md:195`, `docs/changes/CHG-20260823-11.md:198`, `docs/changes/CHG-20260823-11.md:200`, `docs/changes/CHG-20260823-11.md:202`

ROUND 2: fail

1. Resolve task 1 to one control-flow model and specify its durable, atomic state-transition protocol.
2. Add the missing task-12 execution-mode invariants.
3. Replace self-asserted decision identity with a trusted server identity mechanism.
4. Correct task 17 to cover both target and prose scanning without weakening genuine red-line detection.
5. Give tasks 14, 18, and 19 concrete schemas, routes, limits, and failure outcomes.
6. Require the backend and console to expose all 23 graph nodes and their real failure/rework edges before task 1 starts.
