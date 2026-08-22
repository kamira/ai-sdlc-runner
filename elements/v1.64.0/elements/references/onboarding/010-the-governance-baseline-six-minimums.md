### The governance baseline: six minimums

Declaring one commit as the baseline is not enough to prevent a forged history. These six are
the minimum:

1. **The baseline can only be the full SHA seen at adopt time** — not a date, not a tag (tags
   move), not an abbreviation.
2. **Create a separate adopt commit** and record its **parent SHA**. The baseline is the state
   before adoption; the adopt commit is the adoption itself. Merged into one, "what was already
   there" and "what was fixed during adoption" become indistinguishable.
   **This rule is machine-enforced** (CHG-20260811-02). Declare it in the Guideline header:

   ```markdown
   - Governance-baseline: <full 40-hex SHA>   # the state before adoption
   - Adopt-commit: <full 40-hex SHA>          # the adoption itself
   ```

   `doc_integrity_check` verifies each part against git: the commit exists, it has **exactly one
   parent** (a merge blurs the boundary; a root commit has no "before"), that **parent equals the
   declared baseline**, and the adopt commit **touches only governance files**. Both fields are
   required **together** — a baseline alone is no anchor, an adopt commit alone has no starting
   point. **And once the declaration has appeared in history it may not vanish**: deleting it
   makes this check report "not applicable", and not-applicable looks exactly like a pass.
   Projects that never declared it (most of them — they weren't adopted) are reported as **not
   applicable**, which is not the same as passing.
3. **Record the working-tree state**: uncommitted changes, untracked files, submodules, LFS
   pointers. The declared commit is not the same as what was actually inventoried.
4. **Never backfill a CHG before the baseline.** There was no governance, and that fact *is* the
   record. Writing it up as though there had been replaces "no record" with "a false record",
   and the second is harder to detect.
5. **The first governed change starts after the adopt commit**, never before it.
6. **"Inventoried" is not "accepted".** Existing defects, coverage holes, and security debt are
   not ratified by adoption; acceptance goes through acceptance-verification and cannot be a side
   effect of adopting.

The sixth is the one that gives way first: after adoption the repo looks tidy, and tidy reads as
healthy.

