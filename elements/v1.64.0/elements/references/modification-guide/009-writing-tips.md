## Writing tips

- **Structure and records must keep up with code**: this skill's greatest value is keeping docs from lagging. Changing the structure without updating `docs/structure/` means the job isn't done.
- **Record the "why", not just the "what"**: decisions and trade-offs are the most valuable future information. Code shows what changed, not why it was chosen this way.
- **Look one layer outward in impact analysis**: not just the change point itself, but whether things depending on it might break.
- **Stay traceable**: link the change record back to requirement IDs and acceptance reports to form a complete chain.
- **User stories describe user-visible behavior**: one capability per line, in the form "As a <role>, I want <capability>, so that <benefit>"; cover the aspects, not just the happy path. **Stories are the first-choice source of acceptance criteria** — the ACC checks each one off rather than reverse-engineering from the modification steps. A story states **behavior**, not implementation (file paths and function names belong to "Decisions & trade-offs" and the modification guide). Required for medium/high-risk records (Skill >= v1.19, applied forward only — existing records are exempt); not required for CHG-lite.

