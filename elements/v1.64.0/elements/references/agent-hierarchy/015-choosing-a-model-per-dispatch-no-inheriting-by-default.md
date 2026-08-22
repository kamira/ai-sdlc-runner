## Choosing a model per dispatch (no inheriting by default)

**A dispatched agent's model is not inherited from the Master/parent by default — the dispatcher picks it per role.** Reusing the parent's model is a decision, not a default; treating it as the default lets "builder and reviewer on the same model" happen unnoticed, which is exactly the failure mode `independent-acceptance` warns about (one model carries one set of training biases and blind spots, so certain errors are missed *systematically, together*).

Three axes for the choice:

| Axis | Ask | Leaning |
|------|-----|---------|
| **Judgment density** | How much judgment does this role exercise — mechanical execution, or weighing trade-offs? | Judgment-heavy (analysis, review, adjudication) → stronger model; mechanical (filling templates, format conversion, collating lists) → a smaller one suffices |
| **Independence need** | Is this role meant to catch another role's mistakes? | Review / acceptance / panel roles should **differ from the model being reviewed** where possible; the higher the risk, the more this matters |
| **Cost** | How many times will this role be invoked? | For roles called once per task, the price of always using the strongest model is multiplied by the task count |

Rules:

- **Reviewing roles should differ from the builder** (cross-model) where the platform allows; especially for high-risk changes.
- **Record the model each role actually used**: the worklog notes the model at dispatch time; on the acceptance side, reuse the ACC's existing "implementer model / verifier model" field. Without that record, the independence of a round can't be judged afterwards.
- **Single-model platforms**: fall back to "clean context + a different role/system prompt" to reduce correlation, and **state the limitation explicitly** — never silently treat it as cross-model.
- Platform-neutral: this section names no vendor or model; "stronger/smaller" is relative to what that platform offers at the time.

> Relation to existing rules: `independent-acceptance` (cross-model verifiers), `review-panel` (cross-model seats), and `acceptance-verification` (ACC records both models) are **unchanged** — this section generalizes the same principle from "acceptance/review" to **dispatch in general**, and states the default that was previously left implicit.

