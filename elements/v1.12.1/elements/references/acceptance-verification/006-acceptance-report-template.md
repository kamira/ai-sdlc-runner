## Acceptance report template

```markdown
# ACC-YYYYMMDD-NN — <acceptance target>

- Project: <project id / name>   ← required across projects, matching the CHG / Guideline of the same project
- Branch: <branch>   ← required with multiple branches; take acceptance criteria only from the same branch's Guideline/CHG (see branch-isolation)
- Date: YYYY-MM-DD (UTC+0)
- Target: <feature / change ID CHG-...>
- Verifier: <person / agent id>   ← should be ≠ the CHG's implementer (must differ for high-risk; CI can identity-check on this)
- Implementer model / Verifier model: <model A> / <model B>   ← prefer cross-model for high-risk (record if different; note the limitation if same)
- Risk: high / medium / low (inherit from the CHG; decides how many scenarios to verify)
- Baseline source: <ai-guideline §7 / CHG-... modification guide>
- Commit/PR: <hash / PR link>   ← same commit/PR as the CHG and code (commit anchoring; see modification-guide)
- Skill: ai-sdlc v<X.Y>   ← convention version this report was written under
- Conclusion: Pass / Partial pass / Fail

## Check details
| # | Acceptance criterion | Source | Result | Evidence / gap |
|---|----------------------|--------|--------|----------------|
| 1 | ... | FR-1 | Pass | <file/test/behavior> |
| 2 | ... | NFR-performance | Fail | <gap description> |

## Unmet items & handling
| Criterion | Gap | Suggested handling | Routed to |
|-----------|-----|--------------------|-----------|
| ... | ... | ... | modification-guide |

## Structure consistency check
- [ ] Implementation consistent with docs/structure/ (else route to modification-guide to sync)

## Regression (medium / high risk)
- [ ] Affected-scope items from docs/acceptance/regression.md were run: <all green / failures listed above>
- [ ] This ACC's scriptable criteria were deposited into the regression set

## Summary
<whether it's deliverable overall, what's still missing>
```

