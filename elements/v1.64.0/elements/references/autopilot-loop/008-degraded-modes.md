## Degraded modes

- **No headless agent** (`--agent-cmd` unset, not dry-run): the runner prints each task brief and halts (exit 3) — human-in-the-loop mode; ticks still drive resume.
- **No `--verify-cmd`** (and not dry-run): the runner prints the `### Acceptance operation` brief and halts (exit 3) — human performs the operational test and records evidence in the ACC.
- **No gh CLI**: PR/merge stages print the exact commands to run and halt (exit 3) instead of merging.
- **No spawn for reviews**: the same agent builds and reviews serially — note the degradation in the ACC (same rule as ai-sdlc's degraded panel).

