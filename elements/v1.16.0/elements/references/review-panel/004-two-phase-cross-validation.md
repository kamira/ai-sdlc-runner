## Two-phase cross-validation

Verdicts are not just collected — they cross-check each other, in two phases:

- **Phase 1 — independent**: every seat produces its verdict **without seeing the others'** (anti-anchoring; a seat that reads first agrees first).
- **Phase 2 — cross-read**: each seat then reads the other verdicts and flags disagreements: `[cross] <seatA>→<seatB> | agree / disagree | <one-line reason>`. A disagreement is **reconciled or escalated — never averaged**; unresolved cross-flags go to the user via the confirm gate.

The dispatcher adjudicates on the **post-cross** set; cross lines are appended to the CHG alongside the verdicts.

