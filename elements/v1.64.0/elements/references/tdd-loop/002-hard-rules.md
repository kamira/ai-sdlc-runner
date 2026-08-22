## Hard rules

- **No production code before a failing test.** If the task has no testable surface (docs-only), its `test:` line must state a reproducible check (a grep, a lint run, a build) and that check plays the RED/GREEN role.
- **Never delete, skip, or loosen a test to go green** — that is drift wearing a green shirt. If a test is genuinely wrong, fixing it is its own auditable step (say so in the commit).
- **Two consecutive failures on the same task → stop and switch to systematic-debugging.** Blind retries burn the budget and teach nothing.

