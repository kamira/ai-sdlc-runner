---
name: task-review
description: >
  Read-only per-task review with a single reviewer returning a dual verdict — spec compliance
  (does the diff satisfy the task's interfaces and test?) and quality — plus a legitimate
  "cannot-verify" outcome for requirements outside this diff. One fix pass, then halt. An
  end-of-run whole-branch review precedes acceptance. Read this when judging any task's diff.
---

# task-review — one reviewer, two verdicts, read-only

> 語言 / Language: [繁體中文](task-review.zh-tw.md) · **English**

## Inputs (and the anchoring rule)

The reviewer receives the **task brief** (Global Constraints + the task's entry) and the **task's diff** — and nothing else. No implementer narrative, no conversation transcript: narratives replicate anchoring, which is the same reason ai-sdlc's independent acceptance never lets the implementer brief the verifier.

## The dual verdict (one read, one pass)

Judge both in a single reading of the diff:

- **spec** — does the diff deliver the task's `interfaces:` and satisfy its `test:` line? (`pass` / `fail` / `cannot-verify` — the requirement lives outside this diff; a legitimate outcome, not a failure)
- **quality** — idioms of the surrounding code, no drift beyond the task's scope, no weakened tests, no secrets. (`pass` / `fail`)

Output exactly one verdict line (the runner parses it):

```
[task-review] T<n> | spec: pass|fail|cannot-verify | quality: pass|fail | <one-line reason>
```

## Rules

- **Read-only**: the reviewer never edits the working tree. Findings go into the verdict line; fixing is the builder's job.
- **One fix pass**: any `fail` → the builder gets the verdict line and fixes once → re-review. A second `fail` halts the run (exit 3) — a task that can't clear review in two attempts needs a human or a better plan, not a third guess.
- **End-of-run whole-branch review**: after the last task, one review of the full branch diff (same verdict format, `T<n>` → `branch`), on the most capable model available — per-task reviews can't see cross-task drift. Its verdict is an ACC input. **Then comes the operational verify stage** (run the change for real, per the plan's `### Acceptance operation`) — review reads the diff, operational verify runs the result; both precede acceptance (see autopilot-loop).
- All verdict lines land in the **ACC evidence column** — the review trail is part of the ledger, not chat history.
