## Change record template

One record per change; suggested filename `docs/changes/CHG-YYYYMMDD-NN.md`:

```markdown
# CHG-YYYYMMDD-NN — <change title>

- Project: <project id / name>   ← required across projects; when several projects are in play, prefix the change id (e.g. PROJ-CHG-…)
- Date: YYYY-MM-DD
- Type: new feature / fix / refactor / adjustment
- Proposed by: <user>
- Implemented by: <person / agent id>   ← used for the "verifier ≠ implementer" identity check
- Risk: high / medium / low (see grading below; drives acceptance rigor, CI gates, and autonomy halts)
- Autonomy: (optional) auto / halt   ← override the autonomous-run halt point (tighten only; see autonomy)
- Related: <requirement ID / prior change / acceptance report>

## Motivation
<why this change is needed>

## Decisions & trade-offs
| Decision | Options | Why this choice |
|----------|---------|-----------------|
| ... | A vs B | ... |

## Modification guide
<see modification guide template above>

## Structure change summary
<which structure docs were updated, and the key points>

## Status
Draft / Implemented / Accepted (link acceptance report)
```

