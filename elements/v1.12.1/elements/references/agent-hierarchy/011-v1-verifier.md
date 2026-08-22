### V1 verifier
- **Responsibility**: independent, multi-scenario acceptance of the result, producing the ACC; align to source docs not the implementer's self-report; prefer cross-model.
- **In**: the source of criteria (Guideline §7 / the CHG) + the result. **Out**: `docs/acceptance/ACC-*`.
- **May**: read code and criteria, run tests/scripts/CLI/GUI to verify, write its own ACC. **Must not**: edit the code/structure under review, spawn sub-agents.
- **Stage**: acceptance. **Hands off to**: pass → close out and backfill the CHG; fail → back to `modification-guide` for I1 to fix.

