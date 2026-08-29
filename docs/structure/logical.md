# Logical Structure

Answers: FR-1 … FR-17. Layers, responsibilities, and one-way dependencies.

**CHG-20260823-01 rewrote this file rather than amending it.** The previous version described
nineteen modules, twelve of which no longer exist: they were there to read a skill, call its scripts,
lock a version against it, or derive artifacts from it. What is left is what the runner is.

## Modules

| Module | Responsibility | Depends on |
|--------|----------------|------------|
| `policy` | **The governance.** Six roles with capability flags; 10 gates × three risk grades; the six permanent halts and the words that recognise them; the review seats and the rule that adjudicates their verdicts. Every value has its reason written beside it | — |
| `graph` | **The flow.** 31 nodes, one kind of work each, with the module loop, the bounded retry and the feedback edge back to PM. `validate()` asserts it against `policy` | `policy` |
| `engine` | Walks the flow: consults the gate, opens one session per ask and closes it, journals the question before asking, adjudicates the seats, routes on the answers, runs each node's effects | `graph`, `policy`, `workorder`, `effects` |
| `workorder` | Renders one node's order — the closed schema, capabilities from `policy`, and nothing about the harness | `policy` |
| `effects` | Ordered effects, each admitted only if probeable. Resume at the first unmet postcondition; nothing already true is re-applied; everything applied is re-probed | — |
| `probes` | Postconditions read out of the world — git, the forge, the ledger. Unanswerable **raises** rather than returning "not done" | `git`, a forge command, `docs/` |
| `ship` | The ordered ship sequence: intent → branch → commit → push → PR, each effect paired with its probe | `effects`, `probes` |
| `cli` | `flow` / `policy` / `run`; loads the config; builds the session factory (one process per ask) and routes named seats to different commands | `engine`, `graph`, `policy`, `ship`, `tui` |
| `tui` | The interactive selector, and the high-risk-mode confirmation that fronts the seat-floor bypass | stdlib only |
| `tools/ledger_check` | This repo's own ledger lint: required fields, and a closed vocabulary of status words | stdlib only |

Two modules were the whole of the previous design and are gone with the dependency: `contract`
(version locking) and `gates` (subprocess to a skill script). Their responsibilities are now inside
`policy`, which is a much shorter answer than either.

## Main flows

### `runner flow` and `runner policy`

Print the flow and the governance without running anything. Read before doing — the fastest check
that what the runner will do is what you meant.

### `runner run --plan <file>`

The one flow the runner drives, and the loop the whole design is about:

1. **intake** — the user's instruction arrives. Nobody is asked anything yet.
2. **PM plans, PM confirms.** The confirmation node *asks* PM and branches on their answer, then
   consults `plan_confirmed`. Two nodes, because planning and confirming are two kinds of work, and
   the second is the cheapest place a person can still say no.
3. **The lead judges feasibility and risk** — before anyone is dispatched, which is why the lead is
   asked first. Its gate is consulted **before** the work: at high risk the lead is never asked,
   because that is the point of stopping there.
4. **PM signs off**, and the module loop opens.
5. **Per module**: an engineer builds one small module → verifies its own work → the lead reviews
   work it did not write. Pass records the module and returns to the loop; fail takes **one** fix
   pass and **one** re-review, and a second failure halts. Never repeat-until-green.
6. **The panel cross-checks the whole change.** One or many seats, each in its own session, each
   blind to the others. `policy.adjudicate` turns their verdicts into one branch: veto first, then
   majority, and a tie does not pass. Failing returns to the module loop with the panel's reasons.
7. **QA tests and verifies** the whole change, then **acceptance**. Both gate *after* the work — a
   review that halts before it runs is a review a high-risk change can never get.
8. **PR, then merge.** Merge is gated **before**: a one-way door has to be stopped in front of, not
   behind, so it asks at every risk grade.
9. **Close out, then feedback returns to PM.** The flow closes rather than ends.

Cutting across all of it:

- **The gate**, resolved from `policy` and either stopping or not. A stop is a pause with a way back:
  `--confirm <gate>` continues past it and the confirmation is recorded.
- **The permanent halts**, checked against what each node says it is about to do, before dispatch,
  and relaxed by nothing.
- **The ask journal**, written before each session opens.
- **The effects**, run at the nodes that have them, probed before and after.

## Dependency direction

```
cli → engine → {graph, workorder, effects} → policy
ship → {effects, probes}
```

One way, and the ends are worth naming:

- **`policy` depends on nothing.** It is the bottom of the stack, and it has to be: a governance
  module that imports the thing it governs can be argued into agreeing with it.
- **Nothing downstream writes back.** A work order never carries a prior answer; a probe never reads
  a record the runner wrote for its own benefit. That is what lets any node be re-asked from a cold
  start.
- **Nothing points outside this repository.** The previous version of this section ended "the runner
  depends on the skill; the skill never depends on the runner". There is no skill, so the sentence
  has no second half — the dependency graph closes inside `src/`.
