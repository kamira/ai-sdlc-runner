## Halt gates

The forward-progress transitions in the flow are potential halt points:

| gate | location |
|------|----------|
| `requirement_confirmed` | after requirement analysis produces the Guideline, before structure design |
| `structure_confirmed` | after structure design, before implementation |
| `before_implement` | after modification governance produces the CHG, before editing code |
| `acceptance_failed` | acceptance failed, before entering the re-fix loop |
| `before_merge_or_release` | after acceptance passes, before merge / release / delivery |

