You are an INDEPENDENT REVIEW SEAT on the repository at:
C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df

Another seat is reviewing the same code at the same time. You will not see their verdict and they
will not see yours. A split does not pass. Do not soften.

THE SUBJECT: CHG-20260823-25 — the assignment store. **The first change in this sequence with real
durable state behind it**, and nobody independent has read it.

The user ruled that 「模型配置」 includes the assignment, not just the registry. So two tables and two
routes were added, in a real SQLite store.

READ FIRST (open them, do not assume):
- src/ai_sdlc_runner/store.py            <- THE NEW MODULE
- tests/test_store.py                    <- what it claims to have tested
- src/ai_sdlc_runner/server.py           <- make_handler, _assign_node, _assign_seat, /config/nodes
- src/ai_sdlc_runner/cli.py              <- cmd_serve: opening the store, the models.json migration
- src/ai_sdlc_runner/models.py           <- Registry, validate, reach (computed, never stored)
- docs/changes/CHG-20260823-25.md        <- what the change claims
- docs/DATABASE.md, docs/MODELS.md, docs/API.md   <- the three pages that must now be true
- docs/defect-log.md                     <- how defects get found here

WHAT TO JUDGE:

1. DURABILITY AND CORRUPTION. This writes a file an operator will keep. What happens on a crash
   mid-write, a disk-full, a killed process, a corrupt database, a store from a future schema, a
   read-only file? Which of those are handled and which merely have not happened yet?
2. CONCURRENCY. `check_same_thread=False` with an RLock on a Connection subclass. Is that actually
   correct for a ThreadingHTTPServer? Find a sequence of requests that breaks it. Two runners on
   one store file: what happens, and does anything say so honestly?
3. THE MIGRATION. cmd_serve imports models.json into the store on first open. Read that code
   carefully — what happens on a second start, on a models.json that changed, on a store that has
   models and a file that has different ones? Can it lose or silently override an operator's data?
4. THE PRECEDENCE. plan wins, store fills, `resolve()` reports `source`. Is that implemented the way
   it is described? Is there a case where an assignment is used that `source` does not describe, or
   where the console shows one thing and the next run uses another?
5. THE REFUSALS. Four are claimed. Are they complete, are they in the right place, and can any be
   bypassed — e.g. by a route, by the plan file, by a direct store call?
6. THE TESTS. Are they driving behaviour or asserting on source text? Name the weak ones. The change
   record admits one test was too weak and passed on a false page — find the next one.

Check by running things (python3, PYTHONPATH=src, PYTHONUTF8=1, pytest all work; the server can be
driven over real HTTP — see tests/test_store.py for how). Prove claims.

The house standard for a finding:
- checkable. Quote the file and line, or give a command that shows it.
- "a name standing in for a constraint" and "a coarse check answering safe about something it had
  not examined" are this repository's two most frequent defects. Hunt for both.
- Do NOT average or split a difference. Say which is right.

OUTPUT, in markdown:
1. VERDICT: exactly one of `sound`, `sound with changes`, `not sound`
2. The single worst thing in the change, quoted, and why
3. Findings, each with evidence and a severity
4. What the change record CLAIMS that is not true
5. The tests: which are real, which are weak
6. What you could not check, and what you would need

Vague approval is worse than nothing.
