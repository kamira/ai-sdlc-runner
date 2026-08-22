## Per-CHG override

A single change may override via an `Autonomy:` field in the CHG header:
- `Autonomy: halt` (tighten) → halt immediately; always allowed.
- `Autonomy: auto` (loosen) → **only effective for non-"always-halt" items, and loosening a high-risk halt requires prior human approval**; the contract won't auto-loosen high risk (still returns HALT for a human to confirm).
Principle: **overrides may only tighten; loosening needs a human's nod.**

