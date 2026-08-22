## Lightweight record for low risk (CHG-lite)

Record-keeping cost must scale with risk too — demanding the full template for a typo fix is how people learn to bypass the flow. For **low-risk** changes a one-screen CHG suffices, same id and anchoring rules:

```markdown
# CHG-YYYYMMDD-NN — <title>
- Date: YYYY-MM-DD (UTC+0) | Branch: <branch> | Risk: low | Implemented by: <id>
- Motivation: <one sentence>
- Commit/PR: <hash / PR>
- Recurrence check: <no repeat / repeats CHG-… → KN-…>
## Status
Accepted — self-verified (low risk): <one-line reproducible evidence, e.g. `pytest tests/x -q` green>
```

- **Eligibility is a whitelist, not a feeling**: copy/comments, styling, docs-only edits, pure internal refactors with test coverage. Anything touching structure, data, or interfaces is out; outside the whitelist → full template, no matter how small it feels.
- The inline self-acceptance line replaces a separate ACC **only at low risk** (the grading table already allows self-verify there) — it must contain the evidence, and the lint accepts it (a low-risk CHG marked self-verified is exempt from the ACC-file requirement).
- **Misfire = forced upgrade**: if a lite change is later caught breaking something (regression / acceptance), backfill a **full CHG** with the root cause into knowledge, and any pre-authorization covering that class is **auto-revoked** until the user re-grants it.
- Medium / high risk always use the full template + a separate ACC (+ review panel per risk, see review-panel).

