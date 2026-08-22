## Format exemption (output-brevity hooks)

Knowledge entries — the root cause, the normalized rule line, and `evidence` — are a **ledger record**, not human-facing prose, and are **exempt** from any output-brevity / action-first formatting layer (e.g. the suite's `output_format_gate` hook).

- Root-cause text and rule wording are never truncated, summarised, or capped to fit a brevity rule; the fidelity mechanism depends on the exact confirmed wording.
- Enforcement lives in the formatting hook, keyed on the ledger path (`docs/*/{changes,acceptance,knowledge}`); this guide records the guarantee so any agent/vendor keeps these fields whole.

