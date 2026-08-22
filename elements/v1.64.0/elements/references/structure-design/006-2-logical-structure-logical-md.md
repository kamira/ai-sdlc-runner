### 2. Logical structure (logical.md)

The system's layers and module responsibilities, dependencies between modules, and data flow (focused on "what it does and how it's divided", not implementation details).

```markdown
# Logical Structure

## Layers / modules
| Layer/Module | Responsibility | Depends on |
|--------------|----------------|------------|
| ... | ... | ... |

## Architecture diagram   ← required; prose cannot show "what connects to what"
<Mermaid `flowchart` or an ASCII diagram: layers/modules as nodes, dependencies as
directed edges. A table can state "A depends on B"; it cannot show "three modules form
a cycle" — and that is exactly what a diagram makes obvious at a glance>

## Main flows
<1-3 key flows, e.g. "user places an order" from entry to completion.
**Each flow gets its own diagram** (Mermaid `flowchart` / `sequenceDiagram`, or ASCII);
put the prose below the diagram to cover branches and error paths>

## Dependency direction
<who depends on whom; should be one-directional, avoid cycles — the arrows in the
architecture diagram above are authoritative, the prose only adds the reasoning>
```

