## Anti-drift trigger points

Not one-off, but embedded in the flow and checked repeatedly:
- **Change close-out**: when closing a CHG, also confirm structure docs are synced (per modification-guide's "documents are the truth").
- **On entry**: during the Session startup check, sweep doc consistency; fix drift before doing new work.
- **CI (optional)**: automate it as a PR gate via ci-cd's "structure-sync check".

