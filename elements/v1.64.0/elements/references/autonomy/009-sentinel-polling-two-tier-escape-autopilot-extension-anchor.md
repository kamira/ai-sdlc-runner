## Sentinel polling & two-tier escape (autopilot extension anchor)

ai-sdlc-autopilot is a **drive-layer extension** of this governance layer. When autopilot runs "standing requirement-confirmation" via deterministic sentinels + scheduled re-entry, the **governance semantics are anchored here — autopilot must not fork its own taxonomy.**

**Sentinel-callable check registry** — a sentinel is a *deterministic* check (no LLM); the canonical set it may poll:

| stage polled | check | tool |
|--------------|-------|------|
| requirement | plan ↔ CHG consistency | `scripts/plan_check` (autopilot `plan-check`) |
| structure | four-structure ↔ code drift | `scripts/doc_integrity_check` |
| change | scope / halt decision | `scripts/halt_gate.py`, scope check |
| acceptance | overall governance health | `scripts/governance_health.py` |

**Two-tier escape** — a sentinel/re-entry outcome resolves to exactly one tier:

- **Tier A — cannot evaluate** (check unavailable / unparseable / mechanism failure): **fail-open to the baseline linear flow** — do not block (exit 0, log). Degradation, never a silent swallow of a real halt.
- **Tier B — a real halt** (an always-halt action above, a risk×gate `HALT`, or `unknown = halt`): **halt and escalate to a human** — never fall through to baseline. Tier B is defined **only** by this document's always-halt actions + risk×gate matrix + the unknown=halt default; autopilot reads it, does not redefine it.

Base case for re-entry (plan complete / max re-entries / no progress) is a drive concern (autopilot), but "what counts as a real halt" is a governance concern (here).

