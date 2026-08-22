## Mandatory-load rule (original requirement #5)

**This is a hard rule: whenever the user proposes a modification or new feature within a session, the AI must first load this skill and follow its process — it may not skip straight to changing code.**

Why mandatory: any change can touch existing structure and prior design decisions. If you skip governance and edit directly, you tend to get changes that conflict with the architecture, missed knock-on edits, and a "why was it changed this way" that nobody remembers. Running this process once is cheap, yet it preserves consistency and traceability.

How to tell it's triggered (any of these is a change and requires loading this skill):

- A request to adjust, fix, or extend an existing feature/file/table
- Adding a feature to an existing system
- Refactoring, renaming, moving, or deleting existing structure
- **Rolling back / reverting a previous change** (git revert included): a revert is itself a change — open a CHG linking the original CHG, and bring structure docs back in line with the reverted state
- Any change that would make the current structure documents inaccurate
- **Routed back from a failed acceptance**: when `acceptance-verification` reports fail/partial, return to this skill to produce a fix for the unmet items, then re-implement and re-verify

Exception: a brand-new project from scratch goes through `requirement-analysis` → `structure-design`, and this skill does not apply.

