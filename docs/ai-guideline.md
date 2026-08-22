# AI Guideline — ai-sdlc-runner

- Project: ai-sdlc-runner
- Version: v1.0
- Date: 2026-06-17, rewritten 2026-08-23 (CHG-20260823-01)
- Status: Confirmed
- Source requirement: the user's statement of what the runner is, restated across CHG-20260823-01. The original `ai-sdlc-runner-build-guide.md` described an external driver for a skill, which is not what this is any more.

## 1. Background & Goals

**Superseded positioning (CHG-20260823-01).** This project began as an *external driver for the
ai-sdlc skill*: it read the skill's governance, called the skill's scripts, and was forbidden to hold
any of it. Everything below §1 through §8 was written for that. It is no longer what this is.

`ai-sdlc-runner` is **a governed development agent in its own right**. It drives the full development
flow — the user's instruction, PM's plan, the lead's feasibility and risk call, engineers building one
small module each and verifying their own work, the lead's review, QA's testing and verification, and
user feedback returning to PM — from **its own governance**, designed from the ai-sdlc-autopilot
flowchart. The flowchart is a **design input**, not a runtime dependency.

It exists so that running this flow does not require somebody else's agent.

**No skill is stored, referenced, or read.** Not vendored, not installed-and-read. `policy.py` holds
the roles, capabilities, gates and seats; `graph.py` holds the flow. A test asserts that no module
reaches for a skill path, because a quiet "if it's there, use it" branch is exactly how a removed
dependency comes back.

Success = a runner that (a) **holds its own governance**, complete by construction — every role the
flow names has capabilities and every gate it consults is defined; (b) **consults its gates before
dispatching**, since halting after the work was done is not halting; (c) gives **every asking node its
own session**, opened per ask and closed after, because continuity breeds bias; (d) **cross-checks
through several review seats**, count set by the user above a floor only an explicit high-risk mode
lowers; and (e) **survives interruption** — the question is written down before it is asked, so a
dropped session costs the answer and not the question. This repo is itself governed by ai-sdlc's
discipline, now implemented here rather than borrowed.

## 2. Scope

### In scope
- `policy.py` (governance), `graph.py` (the flow), `engine.py` (walking it), `workorder.py`,
  `effects.py`, `probes.py`, `ship.py`, `cli.py`, `tui.py`.
- `tools/ledger_check.py` — this repo's own ledger lint, replacing one that lived in the skill.
- Governance docs for this repo: `docs/ai-guideline.md`, `docs/structure/*.md`, `docs/changes/`,
  `docs/acceptance/`.

### Out of scope (explicitly excluded)
- **Storing any skill content**, vendored or derived. There is nothing to copy from and nothing to
  keep in step with.
- **Reading a skill at runtime.** Not an installed one either — that was considered and rejected by
  the user: the flowchart informs the design, the code is ours.
- Re-implementing anything *because* the skill did it that way. Each governance value here has a
  reason written next to it, and "the skill did this" is not one of them.
- Driving real deployment / migration / deletion / money / secret / publish actions automatically —
  `policy.PERMANENT_HALTS`, never automated at any risk grade.
- Any browser storage / frontend concern (pure backend Python tool).

## 3. Stakeholders

| Role | Concern |
|------|---------|
| The user | Gives the instruction the flow starts from, answers the gates that stop for a person, sets the review seat count, and receives the feedback that returns to PM |
| Runner author (human-in-the-loop) | Builds and changes the runner under this repo's own governance; approves at halt points |
| Independent verifier | Accepts a change against §7; never the person who implemented it on a high-risk change |
| Governed-project teams | Future consumers whose work the runner drives through the §4 flow |

The upstream skill maintainer is **no longer a stakeholder** (CHG-20260823-01). Nothing here reads,
stores, or keeps step with a published skill; the flowchart informed the design and the design is
finished.

## 4. Functional Requirements

The FR set was rewritten by CHG-20260823-01. The previous FR-1 … FR-13 described reading a skill's
version, locking a contract against it, parsing its role table and subprocess-calling its
`halt` script. All of that is gone with the dependency, and is left in git history rather than kept
here as a list of strikethroughs — a requirements section made mostly of superseded rows is one
nobody reads to the bottom of.

| ID | Requirement | Priority | Where |
|----|-------------|----------|-------|
| FR-1 | The governance is this repo's own and complete by construction: every role the flow names has capabilities, and every gate it consults has a verdict at each of the three risk grades | P0 | `policy.py`, asserted by `graph.validate()` |
| FR-2 | The flow is data, validated for internal consistency: every edge lands, every node is reachable, no terminal has an outgoing edge | P0 | `graph.py` |
| FR-3 | One node, one kind of work. Sub-steps inside a node are **effects** with probes, not nodes | P0 | `graph.py`, `effects.py` |
| FR-4 | The gate stops the run — *before* the work where the work is the risk, *after* it where the point is to stop holding the result | P0 | `Node.gate_when`, `engine.walk` |
| FR-5 | A halt is a pause with a way back: a named gate may be confirmed and the run continues, and the confirmation is recorded | P0 | `RunConfig.confirmed`, `RunReport.confirmations` |
| FR-6 | Every asking node is its own session, opened per ask and closed after; a factory returning a session it already returned is refused | P0 | `engine._ask`, `_as_factory` |
| FR-7 | The question is journalled as `pending` **before** its session opens and marked `answered` after, so a dropped session costs the answer and not the question — for every asking role, not only the seats | P0 | `engine.AskJournal` |
| FR-8 | A work order carries the work and nothing about the harness: no tool list, no model, no allowlist, no prior answer. The schema is closed and a field outside it is refused | P0 | `workorder.WORK_ORDER_FIELDS` |
| FR-9 | The review panel is one or many seats, each asked separately and blind to the others; the seat count is the user's, above a floor | P0 | `policy.SEATS`, `resolve_seats` |
| FR-10 | The seats' verdicts are **adjudicated, not averaged**: a veto seat cannot be outvoted, a majority is needed to pass, and a tie does not pass. The engine routes on the result | P0 | `policy.adjudicate`, `engine._adjudicate` |
| FR-11 | At a decision node where somebody is asked, **the answer decides the branch**. A branch taken from the plan while a model is being asked is a question whose answer changes nothing | P0 | `Node.answer_decides`, `engine._answered_branch` |
| FR-12 | Six actions are never automated at any risk grade, and no confirmation or mode relaxes them. They are matched against what each node says it is about to do, and stop the run before dispatch | P0 | `policy.PERMANENT_HALTS`, `permanent_halt`, `engine._permanent_halt` |
| FR-13 | The seat floor may be lowered only through an explicit high-risk mode, and the run records that it was | P0 | `policy.resolve_seats`, `RunReport.relaxations` |
| FR-14 | Different seats may be answered by different models — the same question, different answerers. The routing lives in the CLI and never in the order | P0 | `cli.session_factory`, `--seat-model` |
| FR-15 | Resume is probe-driven: nothing whose postcondition is already true is re-applied, everything applied is re-probed, and anything found true out of causal order is surfaced rather than redone or waved through | P0 | `effects.run` |
| FR-16 | `runner flow` / `runner policy` print the flow and the governance without running anything, so what will happen can be read before it does | P1 | `cli.py` |
| FR-17 | The ledger lint is this repo's own: required fields, and a **closed** vocabulary of status words so an unrecognised status is a failure rather than a silent pass | P0 | `tools/ledger_check.py` |

## 5. Non-Functional Requirements

| Category | Requirement |
|----------|-------------|
| Independence | No external agent, service, or published contract is required to run the flow. Nothing is fetched at build time or at run time; the governance is readable in two source files |
| Correctness | Judged against the requirement, not against a file. There is no upstream table to match, so every governance value has its reason written beside it |
| Honesty | No silent fallback anywhere. Missing configuration is a hard error naming what is missing; an unanswerable probe raises rather than returning False; an unrecognised status fails the lint |
| Auditability | Every verdict, confirmation, relaxation, panel decision and effect outcome is in the run report. An approval that leaves no trace is one nobody can check afterwards |
| Security | Least privilege per role as capability flags; the seats are read-only; the six permanent halts never auto-run |
| Compatibility | Standard library only (PyYAML optional); Python ≥ 3.9; CI on `{ubuntu, windows} × py{3.9, 3.13}` |

## 6. Constraints & Assumptions

- **No skill content in this repo, and no skill read at runtime.** Not vendored, not derived, not
  installed-and-read. Asserted by a test that scans source, tools, tests, packaging, the README and
  CI — docstrings and comments included — and that is written so it scans itself.
- **The flowchart is a design input.** "The published skill does it this way" is not a reason for a
  value here; each has its own.
- **Never auto-run a red line.** Deploy or release, data migration, hard delete, money, secrets or
  permissions, publish. No risk grade, confirmation, or mode relaxes them.
- **Session continuity is a hazard, not a convenience.** A model that can see the previous exchange
  can coast on it; a reviewer who has already seen the answer is not a second opinion.
- **CI baseline (CHG-20260817-10).** This repo had no CI at all until 2026-08-17 — every prior change
  merged on locally-run, self-reported evidence, which is how five Windows-only failures survived
  four changes unnoticed. The **OS matrix is the load-bearing part**; a single-OS pipeline would have
  stayed green through all of it. The version axis has since caught its own defect: an identity check
  written as `id(...)` passed on 3.9 and 3.11 by allocation luck and failed on 3.13.
- CI is deliberately **not** gated on a coverage percentage: measuring the CHG-20260817-09 fix showed
  `executors.py` at 86% before and 85% after, because the broken tests were executing the code and
  dying inside it — coverage counted the lines while no assertion ever ran.
- **Superseded history (CHG-20260823-01).** Everything the previous §6 recorded — the submodule, the
  vendored `skills/` store, the four contract-version baselines, the derived `elements/` artifacts
  and the eight runner-authored fork points that governed their generation — described a dependency
  that no longer exists. It is in git history and in the changes that made it: CHG-20260617-05,
  CHG-20260703-01/06, CHG-20260822-02/03/04.

## 7. Acceptance Criteria

- [ ] `policy.py`: every role in the flow has capabilities; every gate has a verdict at each risk
      grade; the two status-word lists do not overlap; `adjudicate` refuses a tie.
- [ ] `graph.py`: `validate()` passes — edges land, everything is reachable, every gate and role
      exists in the policy, no node claims a gate phase without a gate.
- [ ] `engine.py`: a stopping verdict halts; confirming that gate continues and is recorded; the
      next gate still stops. Every ask opens and closes its own session. A dropped session leaves
      exactly one `pending` question, for any asking role.
- [ ] The seats' verdicts route the branch through `policy.adjudicate`: a majority against does not
      pass, and one veto seat alone does not pass.
- [ ] An answered decision node branches on **its answer** — answering `fail` reaches the failure
      branch, and an answer naming no branch is an error naming the node.
- [ ] An operation that trips a permanent halt stops the run even with every gate confirmed and
      high-risk mode on.
- [ ] `cli.py`: `--confirm`, `--review-seats`, `--high-risk-mode` and the plan's `operations` all
      reach the engine; a seat model routes that seat elsewhere; a backend's JSON reply becomes the
      answer; a failed backend leaves the question pending.
- [ ] `tools/ledger_check.py` exits 0 on this repo, and fails on a status word neither list knows.
- [ ] Suite green on `{ubuntu, windows} × py{3.9, 3.13}`, with every job reporting non-empty steps.
- [ ] Governance docs present and current: this file, `docs/structure/*.md`, the round's `CHG-*.md`
      and `ACC-*.md`.

## 8. AI Development Conventions

- **Own the governance.** The runner holds its policy and its flow. "Read, don't re-implement" was
  this project's founding convention and it is now obsolete: there is nothing to read.
- **A mechanism that nothing calls is not built.** This repo's recurring failure is building a
  correct piece in isolation and never wiring it into what it governs — the engine that ignored its
  own policy verdict, the `adjudicate` no caller reached, the `PERMANENT_HALTS` printed into an order
  and never checked. Wiring is part of the task, and a test that exercises the wiring is the proof.
- **A test that asserts the current behaviour proves nothing.** Two rounds passed their own suites
  while deciding nothing. Write the test that fails when the mechanism is disconnected.
- **Name what you interpreted.** Where the runner chose between readings, the choice is written down
  where the code is, with what it was chosen over.
- **Red lines always halt**, and the check is code, not a paragraph.
- **This repo is governed by its own rules**: every change leaves a `CHG-*.md`, and acceptance closes
  the same round with an `ACC-*.md` carrying evidence. On a high-risk change the verifier is not the
  implementer.
- **Never report green you did not see.** A job with no steps is not a pass; a document saying a task
  is done is not the task being done. Both have happened here.
