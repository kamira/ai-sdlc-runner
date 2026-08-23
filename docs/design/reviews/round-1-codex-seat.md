Q1 — FAIL

The front/back boundary is breached in two places.

First, `PUT /config/nodes`: the mock-up decides whether multiple configured models form a pool or an adjudicated panel from its browser-local `NODES[].kind`. The backend graph contains no equivalent authoritative field. If the server accepts only the selected model IDs, it must trust the browser’s classification or independently infer it—both contradict “the node decides which.” The browser labels and executes the distinction itself, including random pool selection and panel dispatch. Evidence: `docs/changes/CHG-20260823-11.md:57`, `docs/changes/CHG-20260823-11.md:132`, `docs/design/console-mockup.html:704`, `docs/design/console-mockup.html:715`, `docs/design/console-mockup.html:740`, `docs/design/console-mockup.html:782`, `docs/design/console-mockup.html:990`, `docs/design/console-mockup.html:1002`; contrast `src/ai_sdlc_runner/graph.py:50`.

Second, `POST /run/gate`: `halt_independent` is governance, but the mock-up merely presents an “Accept (as verifier)” button. The endpoint has no specified authenticated actor or server-side independence check, so the backend would have to trust the browser’s assertion that the clicker is an eligible verifier. Evidence: `docs/changes/CHG-20260823-11.md:134`, `docs/design/console-mockup.html:1215`, `docs/design/console-mockup.html:1222`; the actual policy requires independence at `src/ai_sdlc_runner/policy.py:114`.

`POST /run/decide` is not itself a boundary violation: the human is supposed to make that decision. It still needs authenticated attribution because the design promises to record who decided. Evidence: `docs/changes/CHG-20260823-11.md:80`, `docs/changes/CHG-20260823-11.md:135`.

Q2 — UNSAFE

A synchronous callable `Approver` is the wrong primary state shape.

Strictly, `walk` currently returns a halted `RunReport`; it does not itself end the process. The CLI may exit afterward, but the engine’s guarantee is a returned terminal result. At a stopping gate, `_gate` sets `halted_at` and `halt_reason`, calls `_finish`, and the walk returns. Evidence: `src/ai_sdlc_runner/engine.py:660`, `src/ai_sdlc_runner/engine.py:674`, `src/ai_sdlc_runner/engine.py:678`, `src/ai_sdlc_runner/engine.py:680`.

Blocking inside that call makes a previously unreachable engine state reachable: the walk has visited the node and, for an after-gate, may already have journalled an answer, but it has neither returned a stopped report nor selected the next branch. The live call stack becomes the only representation of suspension. Evidence: asks complete at `src/ai_sdlc_runner/engine.py:684`; the after-gate runs at `src/ai_sdlc_runner/engine.py:711`; branching happens only later at `src/ai_sdlc_runner/engine.py:724`.

That state can be mistaken for continuation because process liveness no longer distinguishes running from suspended. It also makes restart recovery dependent on reconstructing an implicit Python stack. `_finish` currently describes every walk exit as finalized, not resumable. Evidence: `src/ai_sdlc_runner/engine.py:575`, `src/ai_sdlc_runner/engine.py:582`.

The safer shape is:

- `walk` returns an explicit suspended result containing run ID, node, gate, phase, policy verdict, pending continuation, and durable state.
- The caller records the decision.
- A separate resume operation atomically consumes that decision and continues from the suspension.
- Duplicate, stale, wrong-run, and wrong-gate approvals are rejected.

That shape makes “running,” “waiting,” “rejected,” and “finished” explicit states rather than interpretations of a live thread.

Q3 — POLICY OWNS IT

`undecided` belongs in `policy.adjudicate`, because whether a tie is a failure or no decision is itself the adjudication rule. Keeping `fail` in policy while having a caller reinterpret it as undecided would make the policy result false.

There is one production caller: `engine._adjudicate`. Tests call the function directly, but they do not drive production flow. Evidence: `src/ai_sdlc_runner/engine.py:570`; direct tests are at `tests/test_policy.py:142`, `tests/test_policy.py:148`, `tests/test_policy.py:154`.

No existing caller treats the result as falsy and continues. The result is a nonempty dictionary and therefore truthy. The real compatibility defect is that `_adjudicate` currently maps every outcome other than `"pass"` to `"fail"`, so merely adding `"undecided"` to policy would silently preserve the old failure branch instead of stopping for a person. Evidence: `src/ai_sdlc_runner/engine.py:570`, `src/ai_sdlc_runner/engine.py:572`.

Task 2 must therefore change and test the policy result and every exhaustive consumer together. Unknown outcomes should raise or suspend, never fall through to failure or success.

Q4 — NOT DECIDABLE

The conceptual distinction is sound; the current data model cannot decide it.

`Node` records `id`, structural kind, role, gate, gate phase, successors, branches, and `answer_decides`. It has no execution multiplicity or model-selection semantics. Evidence: `src/ai_sdlc_runner/graph.py:50`, `src/ai_sdlc_runner/graph.py:59`, `src/ai_sdlc_runner/graph.py:74`.

Role cannot safely supply the missing distinction:

- `lead` occurs on ordinary work, individual verdicts, PR, and merge.
- `qa` occurs on work-producing verification and acceptance.
- `engineer` occurs on build, self-verification, and fix work.

Evidence: `src/ai_sdlc_runner/graph.py:97`, `src/ai_sdlc_runner/graph.py:102`, `src/ai_sdlc_runner/graph.py:108`, `src/ai_sdlc_runner/graph.py:121`, `src/ai_sdlc_runner/graph.py:124`, `src/ai_sdlc_runner/graph.py:127`.

The mock-up fills this hole with its own `kind` values, but those are not runner data. Therefore yes: a node can be configured with three models and silently ask one if a backend path treats the selection as ordinary dispatch. Conversely, it could wrongly adjudicate three candidate work products. The current engine only knows that role `"seat"` means panel; every other role is asked once. Evidence: `src/ai_sdlc_runner/engine.py:685`, `src/ai_sdlc_runner/engine.py:686`, `src/ai_sdlc_runner/engine.py:701`.

`graph.Node` needs an explicit, closed execution mode such as `single`, `panel`, `pool`, and `follows`, plus validated relationships for pool main and follower source. No inference from role, node ID, branch shape, or UI data is acceptable.

Q5 — UNSOUND

The record accepts anchoring but then draws an unsupported conclusion: a repeated tie is not necessarily evidence that the panel lacks information. It can represent a genuine value disagreement, ambiguous evidence, correlated blind spots, or a stable 2–2 split. “Short of information, not independence” is not substantiated by the repo. Evidence: `docs/changes/CHG-20260823-11.md:92`.

Round-two voices are not independent in the relevant sense. Fresh sessions prevent hidden conversational continuity, but explicitly supplying every prior answer—with model attribution—creates common context and authority anchoring. The mock-up even says this is intended to make convergence more likely. Evidence: `docs/changes/CHG-20260823-11.md:85`, `docs/design/console-mockup.html:1025`, `docs/design/console-mockup.html:1037`, `docs/design/console-mockup.html:1075`.

The record partially conflates two mechanisms:

- Seat independence is existing governance for the special `seat` role and includes separate sessions plus panel-diversity disclosure. Evidence: `src/ai_sdlc_runner/engine.py:533`, `src/ai_sdlc_runner/engine.py:542`; `src/ai_sdlc_runner/policy.py:90`.
- A proposed panel on an ordinary node is not a governance seat panel. It has no veto-seat definitions, seat floor, or independence rule in `graph.py` or `policy.py`.

If reruns remain, the design must state that round one is the independent panel and later rounds are a deliberative panel. Attribution should be omitted unless there is a concrete need for it. A tie after deliberation should not be described as proof that another round cannot help.

Q6 — INCOMPLETE

At least these explicit tasks are missing:

1. Add authoritative, closed node execution-mode metadata to `graph.Node`, validate every mode and relationship, and reject invalid multi-model configurations server-side. Tasks 4 and 5 currently describe behavior without adding the data that decides it. Evidence: `docs/changes/CHG-20260823-11.md:144`; `src/ai_sdlc_runner/graph.py:50`.

2. Define and implement a durable run-state machine and suspension checkpoint. It must distinguish running, waiting, rejected, completed, and crashed; survive process restart; and atomically consume a gate answer. “Approver waits” and “reload rebuilds the view” do not specify this. Evidence: `docs/changes/CHG-20260823-11.md:141`, `docs/changes/CHG-20260823-11.md:150`.

3. Authenticate and authorize gate/decision actors, including enforcing `halt_independent` and recording a stable identity. A button labelled “as verifier” is not enforcement. Evidence: `docs/design/console-mockup.html:1215`, `docs/design/console-mockup.html:1222`; `src/ai_sdlc_runner/policy.py:114`.

4. Specify and test idempotency and race handling for `POST /run/gate`, `POST /run/decide`, and `POST /run/resume`: duplicate clicks, stale tabs, wrong run/node/gate, and simultaneous decisions must not advance twice. The admitted two-browser issue makes this required even before its display policy is settled. Evidence: `docs/changes/CHG-20260823-11.md:134`, `docs/changes/CHG-20260823-11.md:186`.

5. Define server-side rejection routing. The mock-up sends a rejected gate to `pm_plan`, but the endpoint/design record does not establish that as graph governance, and not every gate has that branch. Evidence: `docs/design/console-mockup.html:1230`; branch data at `src/ai_sdlc_runner/graph.py:78`.

6. Add backend validation for attachments: project-contained storage, filename/path handling, size/type limits, immutable identity, and behavior when an attachment changes or disappears during a run. Task 9 currently states only storage and propagation. Evidence: `docs/changes/CHG-20260823-11.md:149`.

Q7 — PARTLY TRUE

The main design-only claim is presently verifiable: the design commit adds documentation/mock-up files and no `src/` file. The current engine also lacks the proposed behavior. But several record assertions are not verifiable from the repository:

- That the user corrected the design four times. Evidence: `docs/changes/CHG-20260823-11.md:7`.
- That the described hand-run occurred with 19 nodes, 14 asks, resume behavior, and the refused command. No journal, report, command transcript, test, or other evidence is cited. This is **not substantiated**. Evidence: `docs/changes/CHG-20260823-11.md:30`.
- That all four decisions are “settled” by the user. The repository records the claim, not the confirmation event. Evidence: `docs/changes/CHG-20260823-11.md:173`.
- That implementation has a separate confirm gate. The prose declares one, but no durable confirmation artifact is identified. Evidence: `docs/changes/CHG-20260823-11.md:10`, `docs/changes/CHG-20260823-11.md:191`.

The record also understates its own added files: commit `19e34ea` adds `docs/design/README.md` as well as the CHG and mock-up. That does not invalidate the design, but a claim that only the two named files were added is false in the repository.

The first stale point will again be the duplicated manual status: the Type field, task table, and large Status declaration independently claim that nothing has started. The first implementation commit can invalidate all three at once. Evidence: `docs/changes/CHG-20260823-11.md:6`, `docs/changes/CHG-20260823-11.md:137`, `docs/changes/CHG-20260823-11.md:165`.

DESIGN: not sound

Before Task 1 may start:

1. Replace the blocking mid-walk `Approver` design with an explicit, durable suspend/decide/resume state machine, including idempotency and stale-decision rejection.
2. Add authoritative `single` / `panel` / `pool` / `follows` semantics to backend graph data and validate all node-model configurations there.
3. Specify authenticated actor identity and enforce `halt_independent` server-side.
4. Make `undecided` an exhaustive policy outcome and require the engine to suspend on it rather than collapse it to fail.
5. Separate independent first-round review from attributed deliberative reruns; remove the unsupported claim that a tie necessarily means missing information.
6. Add explicit tasks for rejection routing, concurrent browser actions, durable event/run recovery, and attachment validation.
7. Replace unverifiable historical claims with cited artifacts or mark them “not substantiated,” and make status derive from one authoritative task/status location.
