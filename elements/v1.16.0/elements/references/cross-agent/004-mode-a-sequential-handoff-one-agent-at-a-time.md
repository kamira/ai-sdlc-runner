## Mode A: sequential handoff (one agent at a time)

The validated common case (matches the cross-session scenario in the loop test).

- **On entry**: run the Session startup check — scan `docs/changes/` for any status ≠ Accepted and `docs/acceptance/` for missing ACC; close those acceptances first, then start new work.
- **On exit (before handoff)**: close acceptance in the same round, set CHG status to Accepted, sync the structure docs — leave a clean, continuable state for the next agent.
- **Handoff checklist** — before leaving, confirm:
  - [ ] docs and code are consistent (structure docs reflect the latest truth)
  - [ ] no dangling stage (every CHG has a matching ACC)
  - [ ] latest decisions and open items are written into CHG / Guideline
  - [ ] the next step is stated in the record (the next agent can pick up just by reading docs)

  > Under last-act discipline (see handshake), a graceful exit and a crash leave the **same** state — this checklist *verifies* that the invariant held; it is not a rescue procedure.

