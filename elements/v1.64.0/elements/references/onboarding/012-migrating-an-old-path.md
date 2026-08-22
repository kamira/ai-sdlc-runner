## Migrating an old path

When a ledger already exists somewhere but the location must change (for example `docs/` later
becomes a site generator's root):

- **Move only our files**: `CHG-*.md`, `ACC-*.md`, `structure/`, `knowledge/`,
  `ai-guideline.md`. The test is **what a file is, not which directory it sits in** — nothing of
  theirs moves.
- **`git mv`**, so history follows. Non-git projects degrade to copy-then-delete, declared in the
  ack.
- **Dry run by default**: print the full move list first, act only after confirmation. Moving
  files inside someone else's repo runs in the irreversible direction.
- **Resumable**: a re-run moves only what is left, leaving no half-set.
- The migration itself gets a CHG, and the Guideline header's location is updated.

Machine assist: `scripts/ledger_migrate.py` (dry run by default).

