## Two checkpoints: pre-commit (preliminary) and pipeline (full)

Gates can live at two levels; use either or both:

- **pre-commit (local, fast, preliminary)**: before a commit, run "cheap, sub-second" checks to stop obvious problems before they enter version control — e.g. lint/format, quick unit tests, a `CHG-` reference check, a "changed structural files but didn't touch docs/structure" reminder. Use the `pre-commit` framework or a git hook (`.git/hooks/pre-commit`). **Preliminary and bypassable (`--no-verify`), so not the final line of defense.**
- **pipeline (CI, full, authoritative)**: on PR / merge, run the full tests, structure-sync, and ACC gates — **not bypassable, the final line of defense**.

Suggested split: **put the fast and cheap in pre-commit for instant feedback; put the slow and authoritative (full tests, ACC gate) in the pipeline.** The same check can live in both (pre-commit warns early, pipeline enforces). A solo project may use pre-commit only; a team should have at least the pipeline.

