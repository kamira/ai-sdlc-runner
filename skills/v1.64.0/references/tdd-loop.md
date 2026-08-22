---
name: tdd-loop
description: >
  Test-first build discipline for each autopilot task: RED (write a failing test and watch it
  fail) → GREEN (minimal code to pass) → REFACTOR (clean up while green). No production code
  before a failing test; never weaken or delete a test to go green. Read this when building any
  task; the evidence line it produces feeds the ACC.
---

# tdd-loop — red, green, refactor, per task

> 語言 / Language: [繁體中文](tdd-loop.zh-tw.md) · **English**

## The cycle

1. **RED** — from the task's `test:` line, write the smallest failing test first and **run it to see it fail**. A test you never saw fail proves nothing (it may be testing nothing).
2. **GREEN** — write the **minimum** production code that makes it pass. Resist building ahead of the test; the next task has its own tests.
3. **REFACTOR** — with everything green, clean names/duplication/structure. Tests stay green throughout; behavior changes belong to a new RED, not to refactoring.

## Hard rules

- **No production code before a failing test.** If the task has no testable surface (docs-only), its `test:` line must state a reproducible check (a grep, a lint run, a build) and that check plays the RED/GREEN role.
- **Never delete, skip, or loosen a test to go green** — that is drift wearing a green shirt. If a test is genuinely wrong, fixing it is its own auditable step (say so in the commit).
- **Two consecutive failures on the same task → stop and switch to systematic-debugging.** Blind retries burn the budget and teach nothing.

## Evidence for the ACC

Each task ends with one reproducible evidence line — `<test command> → green (N passed)` — which the autopilot collects into the ACC's evidence column. Low-risk CHG-lite self-verification uses the same line inline.

## This is unit/build level — not the operational test

The task `test:` line proves **the part is correct** (RED-GREEN). It is **not** the operational acceptance test — that runs the whole change for real and lives in the plan's `### Acceptance operation` section, gated at the end of the run (see autopilot-loop's operational verify). All tasks green is necessary, not sufficient; a code CHG still can't reach ACC without an operational test on record.
