---
name: acceptance-verification
description: >
  After implementation or modification is complete, systematically verify the result against the
  AI Guideline's acceptance criteria and the change's modification guide, producing an acceptance
  report. When the user says "it's done", "verify this", "check whether it meets the bar", "test
  if it matches the requirements", "is this right", or "confirm the result", or when a feature/
  change has just been completed and needs confirming against the original requirements, be sure
  to use this skill to check each item against its source. Produces a pass/fail acceptance report.
  This is stage four of the ai-sdlc process.
---

# acceptance-verification — verify the result

> 語言 / Language: [繁體中文](acceptance-verification.zh-tw.md) · **English**

## Purpose

After implementation or modification, take the result and check it item by item against "what was agreed up front", producing a clear acceptance report (pass / fail / partial), and point out unmet items and follow-up handling. The key: **acceptance criteria come from existing documents, not invented on the spot.**

## When to use

- A feature or modification was just completed and needs confirming against the bar
- The user says "done / verify / check this / is this right"
- A `modification-guide` change is implemented and needs wrapping up
- A gate before a milestone delivery

## Source of acceptance criteria

In priority order, criteria come from:

1. The relevant `docs/changes/CHG-*.md` modification guide and goal (when verifying a specific change)
2. `docs/ai-guideline.md` section 7 "Acceptance Criteria" and the functional/non-functional requirements
3. `docs/structure/*.md` (confirm the implementation is consistent with the structure)

If these documents are missing, return to the matching skill to fill in the baseline first, then verify; don't verify from impression.

## Workflow

1. **Gather the baseline**: list all criteria this round must satisfy (each tied to a requirement ID or modification-guide step).
2. **Check item by item**: for each, actually check whether the result conforms and record evidence (point to the file/behavior/test that proves it). For things checkable programmatically (e.g. whether a corresponding test exists, whether a field is present), write a script or run it — don't eyeball it.
3. **Judge**: mark each Pass / Fail / N/A, with evidence or the gap.
4. **Produce the report**: write `docs/acceptance/ACC-YYYYMMDD-NN.md` using the template below.
5. **Handle failures**: route failed items back to `modification-guide` to generate fixes, forming a loop, until all pass or the user accepts.

## Cumulative regression set (protecting old features)

Per-change acceptance verifies "did we build the new thing right"; on its own, nothing verifies "did we break old things". So acceptance promises accumulate:

- **Registry**: `docs/acceptance/regression.md` — one line per **programmatically checkable** criterion from past ACCs: criterion, how to run (test/script pointer), source ACC, scope tags (module/area). Wrap run pointers in backticks (e.g. `` `tests/test_x.py::test_y` ``) — the lint verifies the pointed file still exists; a deleted test is a silently void promise.
- **Deposit**: when closing an ACC, add its scriptable criteria to the registry (no duplicates; extend scope tags instead).
- **Run**: for **medium/high-risk** changes, run the registry items whose scope tags intersect this CHG's impact scope. **Breaking an old criterion = Fail**, even if every new criterion passes — route it back like any other failure. Low risk: run what the impact scope obviously touches.
- The registry points at tests/scripts rather than replacing the test suite — its job is to keep past acceptance promises executable and actually re-run.

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

## Writing tips

- **Every item needs evidence, and evidence must be re-runnable**: a "Pass" comes with a command + its key output, or a file/line pointer a reviewer can open — not a narrative claim. A "Pass" without a reproducible check is treated as unverified.
- **Run what's programmatically checkable**: for criteria checkable by script/test, actually run them, don't visually inspect.
- **Make failures actionable**: write the gap and suggested handling clearly, and point to `modification-guide` to form a fix loop.
- **Check structure consistency**: not only whether the feature works, but whether the implementation drifted from the structure docs; if so, route back to `modification-guide` to sync.
- **Align to source, don't expand**: only verify the criteria agreed up front; if you discover a new requirement, go through the requirement/modification flow — don't smuggle it into acceptance.

## After delivery

If everything passes, the stage is complete — set the corresponding change record's status to "Accepted" and link this report. If there are unmet items, route back to `modification-guide` for fixes and re-verify.
