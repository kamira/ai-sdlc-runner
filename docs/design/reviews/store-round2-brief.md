You are an INDEPENDENT REVIEW SEAT on the repository at:
C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df

Another seat is reviewing the same code at the same time. You will not see their verdict and they
will not see yours. A split does not pass. Do not soften.

ROUND 2. Round 1 (CHG-20260823-25) was reviewed by both seats and both returned `not sound`, with
two CRITICAL findings. CHG-20260823-26 is the corrections. **This round reviews the corrections.**

Round 1's findings, all eight:
  1. CRITICAL — make_config read plan.get("node_models"), so a stored assignment governed no run:
     nodes never, seats only after restart, cmd_run never opened the store at all.
  2. CRITICAL — save_registry did DELETE FROM models, which the FK refuses once anything is
     assigned; POST /models had already written memory and models.json, so three copies disagreed
     and the model silently vanished on restart.
  3. HIGH — `version` on the config routes was presence-checked, never compared.
  4. MEDIUM — a crash between the tables and PRAGMA user_version bricked the store permanently.
  5. MEDIUM — a corrupt file raised a raw sqlite3.DatabaseError past a handler catching StoreError.
  6. MEDIUM — `held` was an unlocked read-modify-write across request threads.
  7. LOW — a test skipped a mode silently (`if node is None: continue`).
  8. LOW — the pragma test checked three of the five pragmas.

READ FIRST (open them):
- docs/changes/CHG-20260823-26.md         <- what the corrections claim
- docs/design/reviews/assignment-store-codex-seat.md   <- round 1, one seat
- docs/design/reviews/assignment-store-fable-seat.md   <- round 1, the other seat
- src/ai_sdlc_runner/store.py             <- connect, _migrate, save_registry, resolve
- src/ai_sdlc_runner/server.py            <- make_handler, _assign_node, _assign_seat, POST /models
- src/ai_sdlc_runner/cli.py               <- cmd_run AND cmd_serve: current_assignments, build_factory
- tests/test_store.py                     <- the new tests
- docs/DATABASE.md, docs/MODELS.md, docs/API.md

YOUR JOB: decide whether the corrections actually answer round 1, or only appear to.

1. Go finding by finding. For each of the eight: is it answered in BEHAVIOUR, or in prose? Prove it.
2. Did any fix introduce a NEW defect? Fix 1 changed what a run dispatches to; fix 3 changes when a
   version is refused; fix 6 added a second lock. Look at each for what it broke.
3. TWO LOCKS NOW EXIST — `held_lock` in server.py and the connection's `runner_lock` in store.py.
   Can they deadlock? Find an ordering. Is either held across a call that takes the other?
4. Are the new tests real, or do they assert on source text? Two of them deliberately read source —
   say whether that is justified there.
5. The change record for the corrections makes its own claims. Which are false?
6. What is STILL wrong that neither round has found?

Check by running things (python3, PYTHONPATH=src, PYTHONUTF8=1, pytest; drive the real server over
HTTP — see tests/test_store.py). Prove claims. Assume there is still a defect; find it.

The house standard: checkable findings, quoting file and line. "A name standing in for a constraint"
and "a coarse check answering safe about something it had not examined" are this repository's two
most frequent defects. Do NOT average or split a difference.

OUTPUT, in markdown:
1. VERDICT: exactly one of `sound`, `sound with changes`, `not sound`
2. Round-1 findings: a table of each -> answered / partial / prose only, with evidence
3. New defects introduced by the fixes, if any
4. The single worst thing still in the code
5. What the corrections' change record claims that is not true
6. What you could not check
