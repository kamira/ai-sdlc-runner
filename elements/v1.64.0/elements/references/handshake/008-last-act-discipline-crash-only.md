## Last-act discipline (crash-only)

Conduct **every action as if the session dies right after it**. The entry handshake above assumes the previous session got no warning — this discipline is what makes that assumption permanently safe:

- **One step, one durable write**: intent lands on disk *before* acting (the CHG step, a worklog line); the outcome lands *immediately after* (tick the box, bump the counter, flip the status). Never batch record-keeping for "when I'm done" — "done" may never come.
- **Nothing lives only in the conversation**: a decision made but not written is, to the next session, a decision never made.
- **A graceful exit is just a crash that happened to be convenient**: when the invariant holds, planned handoffs and sudden deaths leave identical states — the exit checklist (cross-agent) *verifies* the invariant rather than rescuing the state.

