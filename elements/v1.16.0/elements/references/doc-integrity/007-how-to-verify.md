## How to verify

- **Script what you can** (preferred — repeatable, unbiased):
  - This skill bundles **`scripts/doc_integrity_check.py`**: it checks "structural code changed but `docs/structure/` not synced" and "an implemented CHG has no matching ACC" (Paused CHGs are legitimate WIP and skipped), plus **template field lint** (required CHG/ACC header fields), a **secrets scan** over docs/, and `--commits-since <anchor>` (a commit whose message references no CHG id = ungoverned work). Exits non-zero on any hit. Wire it into pre-commit / CI to turn "by discipline" into "by machine": `python3 scripts/doc_integrity_check.py --staged`.
  - **Trend, not just point checks**: `scripts/governance_health.py` reports the governance health of a repo — CHG status distribution, hanging acceptances, paused/stale items, emergency-retroactive and doc-sync counts, ACC pass rates. Run it periodically (or in CI, non-blocking); retrospective findings go into knowledge.
  - An entity/module name mentioned in docs can't be grepped in the code → flag (docs may be stale or names drifted).
  - Every FR appears in structure/ACC.
- **Independent review for the rest**: whether the meaning is still correct and the rationale still holds — give it to a non-author agent (see independent-acceptance).

