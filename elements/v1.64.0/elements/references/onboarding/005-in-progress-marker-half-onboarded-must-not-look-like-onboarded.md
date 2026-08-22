## In-progress marker: "half onboarded" must not look like "onboarded"

The routing predicate is "a ledger was found" — and **the ledger becomes findable partway
through onboarding**. If `init` / `adopt` is interrupted after creating the first `CHG-*.md`
(or even the first `changes/` directory), the next entry finds a ledger, concludes "governed",
and **skips whatever was left undone**. A half-built skeleton walks straight into the change
flow, and nothing complains.

So onboarding's **first** action is to write a marker, and its **last** action is to remove it:

```
<root>/.onboarding        # contents: INIT|ADOPT + which step it reached + time (UTC+0)
```

- **Marker still present on entry** → the previous onboarding never finished. **Do not proceed
  into the change flow**; resume from the recorded step (see "Never overwrite, always resumable"
  above), and remove the marker only on completion.
- Relationship to handshake: step 5's reconciliation reads it and treats it as an unclosed stage.
- This is the last-act discipline applied to onboarding: intent lands on disk before acting, the
  outcome immediately after. Hold that, and an interruption leaves a state distinguishable from a
  clean finish — and **distinguishable** is the only thing wanted here (KN-003: "half done" and
  "done" must not look alike).

