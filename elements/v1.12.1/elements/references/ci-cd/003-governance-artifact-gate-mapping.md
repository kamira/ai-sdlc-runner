## Governance artifact → gate mapping

| ai-sdlc artifact | CI/CD counterpart |
|------------------|-------------------|
| Acceptance criteria (Guideline §7 / ACC) | automated tests; CI runs them as a gate |
| Change record CHG | required PR template field; PR must link the CHG |
| Structure docs `docs/structure/` | structure-drift check (below) |
| Acceptance report ACC | merge gate: no matching, passing ACC → no merge |

