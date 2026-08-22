## Standing sentinels & scheduled re-entry

"Requirement-confirmation as standing polling" without stalling on parallel fan-out: a one-shot orchestrator installs deterministic sentinels + scheduled re-entry, then **exits** (dormant = exited, not a resident agent; a re-entry spawns a fresh one-shot run). Governance semantics are anchored in ai-sdlc `references/autonomy.md` — this layer only drives, never forks the taxonomy.

- **Sentinels** (`scripts/autopilot_sentinels.py poll`): deterministic, no-LLM checks over requirement / structure / change / acceptance (`assets/sentinel_policy.json`). Two-tier escape:
  - **Tier A — cannot evaluate** (check unavailable / crashes / unparseable): fail-open to the baseline linear flow (exit 0, logged) — degradation, never a silent swallow of a real halt.
  - **Tier B — real halt** (a check ran and flagged: always-halt action / risk×gate HALT / unknown=halt): exit 3, escalate to a human — never fall through.
- **Scheduled tail-recursion**: cron / scheduled-task re-invokes the poll each interval; ticked checkboxes are the state accumulator between fires. Base case (`plan complete / no progress / max_reentry`) stops re-entry.
<!-- claim: sentinel-install-always-halts -->
- **Install = halt** (`scripts/sentinel_install.py install`): creating cron/CI is a persistent-config action → **always halts for human authorization** (`--i-authorize-cron`); even authorized it emits a reviewable crontab line + CI snippet rather than mutating system cron.

```
runner sentinels --repo . [--chg CHG] [--reentry-count N]   # exit 0 = baseline / 3 = escalate
```
