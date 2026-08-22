## Risk grading and matching rigor

Grade each change's risk first so **governance rigor matches risk** (don't over-govern low risk, don't under-govern high risk):

| Level | Typical cases | Required rigor |
|-------|---------------|----------------|
| **High** | data model / migration, auth, payments, deletion / irreversible, cross-module interfaces, security | **independent acceptance** (verifier ≠ implementer) + **multi-scenario**; CI **identity check**; full pipeline; rollback plan required |
| **Medium** | behavior change to existing features, new non-breaking endpoint/field | at least independent acceptance or full tests; structure sync; pipeline gate |
| **Low** | copy, comments, styling, pure internal refactor with test coverage | self-verify + tests green; pre-commit is enough |

When in doubt, grade up. Put the risk in the CHG header; it drives the acceptance and CI gates that follow.

