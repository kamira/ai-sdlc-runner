## Org principles

1. **ID + fixed role + fixed scope**: every agent has a unique ID, a fixed role, a fixed task scope, and read/write permission. Name them to reflect the hierarchy: `A1` (analysis), `I1` (lead implementer), `I1.1`/`I1.2` (I1's implementation sub-agents), `V1` (verifier).
2. **No exceeding the remit**: an agent does only its assigned task and reads/writes only its granted scope. **Need to do something out of scope → report to the parent**, who decides (reassign / widen the grant); **never self-expand.**
3. **Recursive delegation, permission only narrows**: a sub-agent may spawn its own sub-agents within its own granted scope, but:
   - the scope it grants downward **must be a subset of its own** (permission cannot widen);
   - the whole chain (ID, role, scope, parent-child) is registered in the coordination file;
   - **the parent actively manages**: assign, track, converge — don't let them run loose.
4. **Parent's duties**: assign tasks → track progress → confirm and verify sub-agents' output → converge/aggregate → record errors into the knowledge base (see agent-worklog). Dispatching includes **composing each subagent's dispatch briefing** (the scoped-handshake reading package: branch + structural location + requirement slice + locked location, plus relevant contracts/knowledge) and **auditing its scoped ack** — the four keys must match the dispatch before the subagent acts (see handshake "tiered handshake"). For medium/high-risk decisions the dispatcher also **convenes the review panel and adjudicates its verdicts**; every layer rolls a one-line verdict summary up, and **hard fails escalate uncompressed — no layer may swallow one** (see review-panel).

> Applicability: **solo or team**. A solo user with an AI that spawns sub-agents can use this org too (analysis/implementation/acceptance are all AI sub-agents); you are the top-level manager.

