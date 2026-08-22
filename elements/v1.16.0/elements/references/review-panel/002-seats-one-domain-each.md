## Seats (one domain each)

| Seat | Loads | Verdict question |
|------|-------|------------------|
| risk | modification-guide (grading) | is the risk grade right? high-list hit? |
| impact | modification-guide (impact / assumptions) | knock-on effects? broken prior assumptions? |
| drift | doc-integrity | docs↔code consistent before and after? |
| compliance | knowledge | does this violate any directive? |
| security | autonomy (always-halt list) | does it touch an always-halt action? |
| consistency | branch-isolation / cross-repo | same-branch sources only? contract impact? |

Each seat gets a **scoped briefing**: the CHG draft + its one domain reference (+ global knowledge) + **only its own seat row — not this whole table** (the panel view belongs to the dispatcher). Seats are **read-only and spawn nothing** (no spawn capability — `Agent` tool on Claude, or your platform's equivalent). Machine loads: `role_refs.json` v3 `seat-*` roles.

