## Format exemption (output-brevity hooks)

The ACC evidence column, per-item results, and any output-brevity / action-first formatting layer are **mutually exclusive**: acceptance evidence is a **ledger record**, not human-facing prose, and must stay complete and traceable.

- Evidence values, gap descriptions, and the check-details / unmet-items tables are **exempt** from any output-brevity formatting (e.g. the suite's `output_format_gate` hook). They are never truncated, summarised, or capped (no "≤5 items" cap) — a reviewer must be able to re-run every promise.
- Enforcement lives in the formatting hook itself, keyed on the ledger path (`docs/*/{changes,acceptance,knowledge}`); this guide records the guarantee so any agent/vendor knows these fields must remain whole.
- Only the *human-facing narration around* an acceptance run (progress, next step) may be formatted action-first; the *recorded evidence* may not.

