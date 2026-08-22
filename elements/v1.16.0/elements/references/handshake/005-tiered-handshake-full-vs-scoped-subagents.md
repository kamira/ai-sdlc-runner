## Tiered handshake: full vs scoped (subagents)

Reading everything doesn't scale, and a dispatched subagent doesn't need the whole picture. Two tiers:

**Full handshake** — solo entry, the orchestrator / main agent, taking over a whole project, and **peer parallel agents with no dispatching parent** (no one composes a briefing for you → you carry the full duty yourself): read the full list above.

**Scoped handshake** — a **dispatched subagent**. Its context is keyed by four things: **branch + structural location (module) + requirement (its task's FR/CHG slice) + location (locked file scope)**.

- **Reads**: the **dispatch briefing** its parent composed from the full view (task, locked scope, R/W permission, relevant contract/interface excerpts, relevant structure-doc sections, knowledge entries that are global or tagged for its scope) + its own scope's structure docs and worklog.
- **Does not read**: other branches; other modules' claims / worklogs / handshakes. The branch is inherited from the dispatch — never reference another branch's sources.
- **Global knowledge pierces scope**: directives tagged "all branches / global" are mandatory for every tier — the one thing that crosses scope boundaries.
- **Scoped ack goes to the parent** (not broadcast): `[handshake:scoped] branch | structure | requirement | locked location | next: <one line>`.
- **The parent audits**: it alone has the full view — it composes the briefing before dispatch, and on receiving the ack checks the **four keys match the dispatch**; a mismatch is intercepted before the subagent acts. Cross-scope consistency stays the parent's job (impact analysis, integration acceptance). A subagent that discovers an out-of-scope dependency **reports up** — it does not read sideways or self-expand (see agent-hierarchy).

**The cost, stated plainly**: a scoped subagent cannot catch what the briefing missed. Compensating controls: the parent's impact analysis (CHG), integration acceptance for parallel work, and V1's wider-view acceptance. The trade is deliberate — cheap, parallel, bounded workers + one accountable full-view reviewer.

