## Expedited path (emergency)

When production is down or data is actively at risk, "governance first" would block the fix — that's when people abandon the whole flow. So there is a **legitimate emergency lane**:

- **Trigger**: a human explicitly declares an emergency (production incident, active data loss/security exposure). Not for "I'm in a hurry".
- **During**: fix first. Keep a minimal trace as you go — one worklog line ("emergency: what broke, what I'm changing").
- **After (within 24h)**: backfill a **retroactive CHG** (`Type: emergency / retroactive`, linking the incident and commits) + its ACC, and sync structure docs. The emergency lane defers the paperwork; it never waives it.
- **Audit**: retroactive CHGs are explicitly marked, so health metrics and reviews can see how often the lane is used — frequent use means the normal flow is too slow, which is its own finding.
- **Violation is defined as not backfilling**, not as using the lane.

Relation to autonomy: an explicit human emergency declaration counts as the human approval that halt gates await (see autonomy); always-halt actions are still executed by/with the human, never silently.

