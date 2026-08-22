## Risk grading and matching rigor

Grade each change's risk first so **governance rigor matches risk** (don't over-govern low risk, don't under-govern high risk):

| Level | Typical cases | Required rigor |
|-------|---------------|----------------|
| **High** | data model / migration, auth, payments, deletion / irreversible, cross-module interfaces, security | **full review panel** (see review-panel) + **independent acceptance** (verifier ≠ implementer) + **multi-scenario** + **regression run (affected scope)**; CI **identity check**; full pipeline; rollback plan required |
| **Medium** | behavior change to existing features, new non-breaking endpoint/field | three-seat review (risk/impact/drift); at least independent acceptance or full tests; **regression run (affected scope)**; structure sync; pipeline gate |
| **Low** | copy, comments, styling, pure internal refactor with test coverage | self-verify + tests green; pre-commit is enough |

When in doubt, grade up. Put the risk in the CHG header; it drives the acceptance and CI gates that follow.

**Grading is not solely self-assessed**: a hit on the high-risk list (data model/migration, auth/permissions, payments, deletion/irreversible, cross-module interfaces, security) is **high regardless of the AI's own grading** — no self-downgrade; and the user reviews the grade at the confirm gate. An unconsidered situation must not slip through every gate just because the AI graded itself "low".

