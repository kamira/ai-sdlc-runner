## When you find drift

**Don't silently edit the doc** — return to `modification-guide` and add a "doc sync" change (or note it in the current CHG), stating the drift and the fix, to keep the trail. Drift itself is a signal worth recording: it means some earlier change failed to bring the docs along.

**Adjudication — which side is right**: docs record **intent**, code is **current reality**; "docs win" applies to *memory vs docs*, not to *reality vs docs*. Trace the CHG trail to decide the fix direction:
- The code state is explained by an accepted CHG whose doc sync was missed → **update the docs** to match (doc-sync change).
- No CHG explains the code state → an **ungoverned change**: reconstruct a CHG for it (if the change should stand) or revert it (a revert is also a CHG); when the intent is unclear, **ask the user** — don't pick a side silently.

