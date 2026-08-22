## State machine

```
ai-sdlc entry handshake (governance layer — mandatory, includes knowledge INDEX + pending CHG scan)
  → CHG exists & confirmed?  no → requirement/modification governance first (ai-sdlc)
  → plan-check gate (exit 2 on failure — a bad plan never starts)
  → confirm gate            (per policy: auto / confirm / halt)
  → [ per unticked task T_i:
        TDD build → task tests → read-only task review
        → pass: tick + commit "CHG-<id>: T<i> <title>" + update live handshake
        → fail: one fix pass → re-review → second fail = halt ]
  → whole-branch review
  → operational verify (run it for real: operate → observe → pass; per policy)
  → acceptance (ACC; per policy self-verify / independent)
  → PR → merge (per policy) → close-out: CHG status + Commit/PR + recurrence check + knowledge
```

