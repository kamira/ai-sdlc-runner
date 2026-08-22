## Format (inside the CHG's modification-guide section)

```markdown
### Global Constraints (every task must obey)
- <testable constraint — "always X", never "prefer X">

### Tasks (checkboxes = resume points)
- [ ] T1. <title>
  - interfaces: consumes <inputs/preconditions> / produces <outputs/deliverables>
  - test: <how to verify — a command or an assertable condition>
- [ ] T2. ...

### Acceptance operation (the end-stage operational test — required for code-bearing changes)
- operate: <how to run/exercise the change for real — a command or steps>
- observe: <what observable behavior confirms it works>
- pass: <pass criteria>
```

For a **pure-doc CHG** with nothing to run, replace the whole section with a one-line header field: `Acceptance-operation: n/a (docs-only)`.

