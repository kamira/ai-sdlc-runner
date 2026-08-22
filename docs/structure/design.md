# Design Structure

Answers: FR-1 … FR-17. Key components, their contracts, and the decisions behind them.

**CHG-20260823-01 rewrote this file rather than amending it.** Two-thirds of the previous component
table described modules that no longer exist, and most of the decision table argued about how to read
a skill. What survives is what is still true, and it is repeated here rather than cited, because a
design doc that points at deleted files is worse than no design doc.

## Key components

| Component | Responsibility | Contract |
|-----------|----------------|----------|
| `policy.verdict` | Resolve one gate at one risk | `(gate, risk, autonomy=None) -> {gate, risk, verdict, source, tightened}`. Autonomy is **tighten-only**: a request to loosen is refused and the refusal is appended to `source`, so the attempt is visible |
| `policy.adjudicate` | Turn seat verdicts into one outcome | `({seat: verdict}) -> {outcome, reason, ...}`. Veto first, then majority, and a tie does **not** pass |
| `policy.resolve_seats` | How many seats open | `(requested, high_risk_mode) -> int`. Below the floor without the mode → the floor |
| `policy.permanent_halt` | Does this operation cross a red line | `(operation) -> Optional[str]`, the halt's own description. Matching is deliberately generous: a false stop costs one question, a missed one costs the thing that cannot be undone |
| `graph.validate` | The flow agrees with itself and with `policy` | Raises `GraphError` naming the node. Every edge lands, everything is reachable, every gate and role exists, no gate phase without a gate, no `answer_decides` without a role |
| `engine.walk` | Drive one change through the flow | `(RunConfig, dispatcher, enabled=True) -> RunReport`. Opt-in: it **refuses** rather than quietly doing nothing, so "flag off" cannot be mistaken for "ran and found nothing" |
| `engine.AskJournal` | The question outlives the session | `pending` written before the session opens; `answered` after. `pending()` returns what a resumed run must re-ask |
| `workorder.render` | One node's order | `(node, node_spec, verdict, seat=None) -> dict`. **Exactly** the sixteen keys, asserted on every render |
| `effects.run` | Bring a sequence to completion from wherever it is | Nothing already true is applied — before the frontier or after it. Everything applied is re-probed. Anything true out of causal order is **surfaced**, not redone and not waved through |
| `cli.session_factory` | Where an ask goes | `(config, seat_models) -> factory(seat=None) -> Session`. One process per ask; `--seat-model` routes a named seat elsewhere |
| `cli._Process` | One ask, one process | The order in as JSON on stdin, the JSON printed back **parsed** as the answer. A non-zero exit raises: a failed backend answered nothing, and the journal keeps the question pending |
| `tools/ledger_check.check` | The ledger lint | `(repo) -> list[str]` of problems. Reads the Status **section**, and only the **head** of its line |

## Interface contracts

- **Work order** — the closed field set a dispatched node receives, and the only thing it receives:
  `node_id, node_label, role, role_label, seat, scope, objective, instructions, done_criteria,
  acceptance_predicate, input_artifacts, expected_outputs, policy_verdict, capabilities,
  permanent_halts, idempotence_probes, workdir`. What is **excluded** is the load-bearing part:
  concrete tools, allowlists, a bootstrap line, session or prior-turn context, model and dispatch
  settings. An order carrying any of them runs on one harness only, however short it is.
- **Answer** — a decision node's answer must name its branch, as `branch`, `verdict` or `outcome`.
  An answer naming none is an error that names the node and lists the branches; an answer naming a
  branch that does not exist is refused. Neither is defaulted.
- **Effect** — `{name, probe, apply, postcondition}`. **Constructing one without a probe raises**:
  probeability is the admission criterion for being an effect at all, not a property to add later.
- **Probe** — `() -> bool`, reading the world. Unanswerable **raises** rather than returning `False`:
  "I could not reach the remote" and "the branch is not there" are different facts, and merging them
  makes a resume push twice.
- **Error behaviour** — no silent fallback anywhere. An unknown gate, an untemplated node, a branch
  the plan did not supply, a seat nobody defined, a status word neither list knows: each raises and
  names what is missing.

## Design decisions

| Decision | Options | Rationale |
|----------|---------|-----------|
| Where the governance lives | read an installed skill **vs** own it | Own it. The user rejected reading explicitly (*不是讀 skill*): a runtime dependency on somebody else's file is the thing being removed, and the flowchart's value was the design, which is finished |
| The flow as data | code **vs** a data table | Data. `runner flow` prints what will happen before it does, and `validate()` can check it against `policy` — neither is available if the flow is control flow |
| Node boundaries | phases **vs** one kind of work each | One kind of work each, from the requirement's own sentence (*一個項目只做單一類型的工作*). Sub-steps inside a node are **effects** with probes, not nodes |
| Where a gate is consulted | always before **vs** per node | Per node, `gate_when`. Before, where the work is the risk (merge, dispatch); after, where the point is to hold the result (review, QA, acceptance). Always-before made three gates unreachable — a review that halts before it runs is a review a high-risk change never gets |
| A stopping verdict | ends the run **vs** may be confirmed | May be confirmed, per gate, and recorded. A halt that cannot be continued past makes most of the gate matrix dead: every medium-risk run ended at the same node forever |
| `merge` at low risk | auto **vs** confirm | Confirm. A one-way door is a door whatever the change's grade; "low risk" grades the change, not the door |
| Permanent halts | text in the order **vs** a check | A check, against what each node says it is about to do, before dispatch, relaxed by nothing. A list nothing reads is a paragraph — the first version printed all six into every order and never looked at them again |
| Who decides a branch at an asked node | the plan **vs** the answer | The answer. A decision node whose branch comes from the plan while somebody is being asked is a question whose answer changes nothing, and it is possible to answer every ask `fail` and still reach the end |
| Seat verdicts | averaged **vs** adjudicated | Adjudicated, in `policy`, so the rule lives in one place. Veto first, then majority, tie does not pass. Averaging turns a factual objection into a fraction |
| Seat count below the floor | a config value **vs** an explicit mode | An explicit mode, surfaced in the GUI with the cost written into the option, and recorded in the run when used. Relaxing a gate is the user's call, but a relaxation nobody can see themselves making is not one they made |
| Session lifetime | one per run **vs** one per ask | One per ask, opened and closed around it, and a factory that hands back a session it already returned is refused. Continuity breeds bias — a reviewer who has already seen the answer is not a second opinion |
| Where the question is written | after the answer **vs** before the ask | Before. A dropped session then costs the answer and not the question; reconstructing a question later risks asking a subtly different one, and a subtly different question is how a rerun quietly stops being a rerun |
| Resume | a checkpoint file **vs** probes | Probes. Resume asks the world what is already true rather than consulting a record of what we did; a record can be stale, and a stale record makes a resume push twice |
| Seat identity in the order | prose only **vs** a field | A field. Adjudication counts verdicts by seat, so an answer nobody can attribute cannot be counted towards a majority |
| The backend's reply | captured **vs** parsed | Parsed. The engine routes on what a review actually said; an answer left as a blob of stdout decides nothing, which made every real agent's verdict unroutable while the stub-backed tests stayed green |
| The ledger's status vocabulary | open **vs** closed | Closed. Treating an unrecognised word as "not finished" let `accepted`, `merged`, `completed` and `完成` all pass with no acceptance record. An unknown status is now a failure that names its own fix |
| Reading a document's status | the whole document **vs** the Status section **vs** its head | The head of the Status section's first line. Prose about status changed a document's classification three times in one session — once inside the sentence explaining the first time. `draft — all 9 tasks built` is a draft |
| Stdlib only | a TUI/YAML dependency **vs** stdlib + fallbacks | Stdlib. Nothing is fetched before the governance can be read, and `curses`/PyYAML both degrade to a working fallback |

## Patterns

- **A mechanism is not built until something calls it.** This repo's recurring failure: an engine
  that ignored its own policy verdict, an `adjudicate` no caller reached, a `PERMANENT_HALTS` list
  printed and never checked, three modules tested and imported by nobody. Each passed its own tests.
  The pattern is the fix: wire it, and write the test that fails when it is unwired.
- **One ask, one session**, closed in a `finally`.
- **Write the question down before asking it.**
- **Postconditions, not receipts.** Resume asks the world, not a record of what we did.
- **Least privilege as capability flags**, not tool names — a role's authority is about what it may
  do, and tool names belong to a harness.
- **Name what you interpreted.** Where the runner chose between readings, the choice is written down
  next to the code, with what it was chosen over.
