## Orchestrator rules (parent agent)

- **Assign role and read/write permission before dispatching**: every subagent has an explicit role and readable/writable scope (see cross-agent, independent-acceptance); verifier-type subagents are read-only.
- **Collect and consolidate errors**: aggregate every subagent's reported errors into the **knowledge base** `docs/knowledge/errors.md` — dedupe, generalize common patterns, write "error → root cause → fix → prevention".
- **The knowledge base is a cumulative asset**: every agent, on entry (alongside the Session startup check), **reads the knowledge base first** to avoid repeating known errors.

