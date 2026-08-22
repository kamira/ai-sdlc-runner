## Halt decision order (strict, tighten-only)

1. **Permanent halts** — task or CHG tagged `permanent-halt:<class>` (irreversible-delete / payments / prod-migration / security-boundary): unconditional halt; the runner refuses any config that relaxes these.
2. **CHG `Autonomy:` field** — may only tighten relative to policy.
3. **`assets/autopilot_policy.json`** — the risk × stage matrix.
4. **Unknown → halt.** A gate the contract doesn't recognize stops the run; guessing "auto" is how autopilots crash.

`confirm` stages may be pre-authorized via a knowledge directive (narrow class, auto-revoked on misfire) — ai-sdlc's pre-authorization rule, unchanged.

