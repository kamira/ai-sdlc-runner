---
name: structure-design
description: >
  Based on a confirmed AI Guideline, produce the system's four structure documents: directory
  structure, logical structure, design structure, and data structure. When the requirements/
  Guideline are settled and you need to plan "what the system looks like", "how to layer it",
  "how data is stored", "how files are arranged", "architecture design", "database design", or
  "how to split modules", be sure to use this skill to commit the structure to documents before
  implementation begins. This is stage two of the ai-sdlc process; its input is docs/ai-guideline.md.
---

# structure-design — produce four structure documents

> 語言 / Language: [繁體中文](structure-design.zh-tw.md) · **English**

## Purpose

Turn a confirmed AI Guideline into an implementable system structure, captured as four documents: **directory, logical, design, and data structure**. These are the blueprint for implementation and modification, and the baseline `modification-guide` uses to assess change impact and `acceptance-verification` uses to verify.

## When to use

- `docs/ai-guideline.md` is confirmed and you're starting to plan the system
- The user asks to "design the architecture", "plan the directories", "design the database/data model", or "how to layer and split modules"
- Before a major refactor that needs a target structure first

## Prerequisite

Read `docs/ai-guideline.md` first. The structure must answer the Guideline's functional and non-functional requirements; if the Guideline is missing or stale, go back to `requirement-analysis`.

## The four structures

From abstract to concrete, they echo each other. Produce them under `docs/structure/`, one file each.

### 1. Directory structure (directory.md)

How the project's physical folders and files are organized.

```markdown
# Directory Structure

## Tree
\`\`\`
project/
├── src/
│   ├── <module-A>/
│   └── <module-B>/
├── tests/
└── docs/
\`\`\`

## Responsibility per directory
| Path | Responsibility | Notes |
|------|----------------|-------|
| src/<module-A> | ... | ... |

## Naming & placement rules
- <file/module naming conventions, what goes where>
```

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

### 4. Data structure (data.md)

Data entities, fields, relations, and constraints (database schema, key data objects).

```markdown
# Data Structure

## Entities / tables
### <entity name>
| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| id | ... | PK | ... |

## Relations
<relationships between entities: one-to-many, many-to-many, foreign keys>

## Indexes / constraints
<important indexes, uniqueness, deletion strategy>

## States / enums
<key state machines or enum values>
```

## Workflow

1. Read the Guideline and list the requirements the structure must answer (especially P0 and non-functional ones).
2. Produce abstract→concrete: logical → design → data → directory (order can flex per project, but all four must exist).
3. Verify the four are mutually consistent: logical modules should map to directory folders, design components, and data entities.
4. In each document, note which requirement IDs it answers (traceable back to the Guideline's FR/NFR).
5. **Hand back to the user with the diagrams, for review and correction, before any implementation.** Of the four structure documents, the diagrams are the part that most needs a human pass — they are the only thing that lets someone see at a glance that "you wired that module to the wrong side", and that is the mistake this stage catches cheapest and every later stage pays most for. Show them, correct them as directed, and keep correcting until the user confirms; **do not proceed before they do**. The user may decide not to look (note it in the Guideline's "AI development conventions"), but **the default is to draw** — nothing said means draw.

## Writing tips

- **Generic, not tied to a specific tech stack**: unless the Guideline already specifies the language/framework/DB, use generic terms (layer, module, entity, interface), and leave implementation choices to the design-decisions table with rationale.
- **Traceable**: tie structure elements to the Guideline's requirement IDs so acceptance and changes connect later.
- **Stay consistent**: the four documents describe different views of the same system — names and boundaries must line up.
- **Record trade-offs**: the design-decisions table is the most valuable part — write down why A over B, so future changes know what can move.

## After delivery

Once the structure is confirmed, implementation can begin. Any later change goes to `modification-guide`, which loops back to update these four documents.
