### pre-commit example (platform-neutral pseudo)

```yaml
# concept: .pre-commit-config.yaml or .git/hooks/pre-commit
pre-commit:
  - run: <lint / format>
  - run: <quick unit tests>
  - run: python3 scripts/doc_integrity_check.py --staged   # structure drift + CHG↔ACC link; blocks the commit  <!-- claim: doc-integrity-staged-blocks-commit -->
  - check: commit message or staged diff contains a "CHG-" reference
```

> **Turn "by discipline" into "by machine"**: `scripts/doc_integrity_check.py --staged` checks, before commit, "structural code changed but docs/structure not synced" and "an implemented CHG has no matching ACC (acceptance hanging)", failing the commit otherwise. Semantic content still needs a human/agent, but *whether it's synced* is machine-enforced — no longer discipline-only.

