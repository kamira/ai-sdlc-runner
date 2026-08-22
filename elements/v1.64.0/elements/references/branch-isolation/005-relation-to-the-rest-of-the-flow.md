## Relation to the rest of the flow

- handshake: the first step on entry is to confirm the current branch; all references afterwards are limited to it. **Switching branches mid-session counts as a new entry — redo the handshake** (branch, unclosed stages, working tree all differ per branch).
- modification-guide / acceptance-verification: CHG/ACC carry a branch; the acceptance baseline takes only the same branch's Guideline/CHG.
- doc-integrity: can add a "CHG/ACC branch field = current git branch" check (mismatch → flag).
- knowledge: directives default to the current branch; general ones are tagged "all branches".
