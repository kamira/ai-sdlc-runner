## Headcount & cross-validation (when subagents can be dispatched)

- **No fewer than 3 independent verifiers** for a verification (the decision-stage panel takes no fewer than 5 — see review-panel). Split scenarios across them or overlap deliberately; each is read-only and none is from the implementation chain.
- **Two-phase cross-validation**: phase 1 — each verifier concludes **independently** (no peeking; anti-anchoring). Phase 2 — verifiers **cross-read** each other's findings and flag disagreements (`[cross] A→B | agree / disagree | reason`); disagreements are reconciled or escalated, **never averaged**.
- **Models need not be the same**: spread verifiers across models when the platform offers several (same-model verifiers share blind spots); the ACC records **the verifier set and each verifier's model**. Single-model platform → note the limitation.
- Quotas bind only when spawning is available; otherwise fall back to the per-risk rules above (single independent verifier / full tests / self-verify) and say so in the ACC.

