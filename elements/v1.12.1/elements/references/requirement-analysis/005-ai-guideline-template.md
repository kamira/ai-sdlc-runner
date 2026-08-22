## AI Guideline template

Produce `docs/ai-guideline.md` using this fixed structure:

```markdown
# AI Guideline — <project/feature name>

- Project: <project id / name>   ← required across projects, so this doc is clearly attributable
- Branch: <branch>   ← required with multiple branches; use same-branch sources only (see branch-isolation)
- Version: v1.0   ← after a structure change or requirement update, revise this doc and bump (see below)
- Date: YYYY-MM-DD
- Status: Draft / Confirmed

## 1. Background & Goals
<why we're doing this, the problem to solve, definition of success>

## 2. Scope
### In scope
- ...
### Out of scope (explicitly excluded)
- ...

## 3. Stakeholders
| Role | Concern |
|------|---------|
| ... | ... |

## 4. Functional Requirements
| ID | Requirement | Priority (P0/P1/P2) | Notes |
|----|-------------|---------------------|-------|
| FR-1 | ... | P0 | ... |

## 5. Non-Functional Requirements
| Category | Requirement |
|----------|-------------|
| Performance | ... |
| Security | ... |
| Maintainability | ... |
| Compatibility/Scale | ... |

## 6. Constraints & Assumptions
- Constraints: ...
- Assumptions: ...
- Open items: ...

## 7. Acceptance Criteria
- [ ] <measurable criterion tied to a specific requirement>

## 8. AI Development Conventions
<principles later AI work must follow: naming, tech-direction, where docs live,
which skills to pair with, etc.>
```

