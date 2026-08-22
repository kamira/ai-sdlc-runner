## Platform-neutral example (pipeline, pseudo)

Conceptual sketch; translate to any CI platform (GitHub Actions / GitLab CI / Jenkins...):

```yaml
on: pull_request
jobs:
  governance:
    steps:
      - run: <run tests>                    # gate 1: tests green
      - check: PR body contains "CHG-"      # gate 2: traceability
      - check: if changed_files match structural paths (src/models|schema),
               then docs/structure/ must also have changes        # gate 3: structure sync
      - check: docs/acceptance has an ACC for this CHG concluding "pass"  # gate 4: acceptance gate
      - check: if CHG risk=high, the ACC's "Verifier" ≠ the CHG's "Implemented by"  # gate 5: identity check
```

GitHub Actions example: trigger on `on: pull_request`; `gate 1` runs the test step; `gate 2/3/4` use a script that reads the PR body and `git diff --name-only`, compares paths, and greps `docs/acceptance/` for the matching file — any failing check exits non-zero to block the merge. Other platforms (GitLab CI `rules`, Jenkins stages) work the same way.

