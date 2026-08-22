### 3. Design structure (design.md)

Key components/interfaces/contracts and the design patterns adopted (focused on "how it's done and what the interfaces look like").

```markdown
# Design Structure

## Key components
| Component | Responsibility | External interface/contract |
|-----------|----------------|------------------------------|
| ... | ... | ... |

## Component relationship diagram   ← required
<Mermaid `flowchart` / `classDiagram`, or ASCII: components as nodes, calls or contracts
as edges. This is a different altitude from the logical structure's architecture diagram —
that one shows how modules divide the work, this one shows how components call each other>

## Interface / API contracts
<inputs, outputs, error behavior of important interfaces>

## Design decisions & trade-offs
| Decision | Options | Rationale |
|----------|---------|-----------|
| ... | A vs B | ... |

## Patterns adopted
<patterns used and why, e.g. why repository / event-driven>
```

