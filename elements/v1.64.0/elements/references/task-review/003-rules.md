## Rules

- **Read-only**: the reviewer never edits the working tree. Findings go into the verdict line; fixing is the builder's job.
- **One fix pass**: any `fail` → the builder gets the verdict line and fixes once → re-review. A second `fail` halts the run (exit 3) — a task that can't clear review in two attempts needs a human or a better plan, not a third guess.
- **End-of-run whole-branch review**: after the last task, one review of the full branch diff (same verdict format, `T<n>` → `branch`), on the most capable model available — per-task reviews can't see cross-task drift. Its verdict is an ACC input. **Then comes the operational verify stage** (run the change for real, per the plan's `### Acceptance operation`) — review reads the diff, operational verify runs the result; both precede acceptance (see autopilot-loop).
- All verdict lines land in the **ACC evidence column** — the review trail is part of the ledger, not chat history.
