## Recommended gates (loose → strict; pick per team needs)

1. **Tests must be green**: maps to acceptance criteria; the baseline.
2. **PR must link a CHG**: PR description must contain a `CHG-` reference (maps to "trace every change").
3. **Structure-sync check**: if this PR changed structural code (e.g. `src/models/**`, schema) but didn't update `docs/structure/`, warn or block (maps to "documents are the truth").
4. **Acceptance gate**: an ACC for this change exists and concludes "pass" before merge (maps to "close acceptance in the same round").
5. **Identity check (verifier ≠ implementer)**: compare the ACC's "Verifier" with the CHG's "Implemented by" (or commit author / agent id); **they must differ** — turning "player can't be referee" into a machine-enforceable gate. **Mandatory for high-risk changes**; low-risk may be exempt (self-verification allowed).

Adopt **loose → strict**: start with "tests green + PR links CHG", and once the team is used to it add structure-sync, the ACC gate, and the identity check, so you don't stall the flow by being too strict at once.

