## Relation to the rest of the flow

- "Write before executing" echoes doc-integrity and "don't rely on memory, rely on the docs": state lives in files, not in the head — resilient to interruption / compaction / handoff.
- The error knowledge base is a third kind of trail beyond "decisions (CHG) / acceptance (ACC)": it records not just "what was decided" but "what pitfalls were hit and how to avoid them".
- Consolidation is the parent agent's job; **it applies solo too** — there, you are the parent.
