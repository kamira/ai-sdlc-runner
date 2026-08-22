## How to verify

- **Script what you can** (preferred — repeatable, unbiased):
  - This skill bundles **`scripts/doc_integrity_check.py`**: it checks "structural code changed but `docs/structure/` not synced" and "an implemented CHG has no matching ACC", exiting non-zero otherwise. Wire it into pre-commit / CI to turn "by discipline" into "by machine": `python3 scripts/doc_integrity_check.py --staged`.
  - An entity/module name mentioned in docs can't be grepped in the code → flag (docs may be stale or names drifted).
  - Every FR appears in structure/ACC.
- **Independent review for the rest**: whether the meaning is still correct and the rationale still holds — give it to a non-author agent (see independent-acceptance).

