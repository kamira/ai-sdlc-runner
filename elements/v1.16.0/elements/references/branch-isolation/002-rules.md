## Rules

- **Tag the branch**: the Guideline / CHG / ACC header has a "Branch" field. When referencing requirements or acceptance criteria, take only those on the **same branch as current**.
- **Only current-branch sources**: in detection/acceptance/impact analysis, filter out other branches' CHGs/requirements. Current branch = the one confirmed in the entry handshake.
- **No cross-branch reference**: branch A's acceptance may not use branch B's requirements as the baseline; branch A's CHG may not cite branch B's requirement as its basis.
- **Brought in only at merge**: another branch's requirements/changes enter the current branch only when **merged in**, via the normal flow (modification-guide + acceptance); before the merge they are "out of this branch's scope".
- **IDs are unique per branch only**: two branches can independently open `CHG-20260702-01` — branches don't reserve numbers for each other (each has its own coordination view). Resolve collisions **at merge**: keep the target branch's numbering, renumber or suffix the imported records (e.g. `CHG-20260702-01-feat-x`) and fix links. When heavy parallel branching is expected, include the branch in the ID from the start (`CHG-<branch>-YYYYMMDD-NN`).
- **A merge is itself a change (merge-CHG)**: merging branch B in goes through modification-guide **on the target branch** — open a merge-CHG listing what's imported; **re-tag imported CHG/ACC Branch fields to the target branch** (keep the original branch in "Related"/history); resolve structure-doc conflicts **semantically** (reconcile module/boundary meaning, not just merge the text); then run acceptance on the merged result.
- **Cherry-pick / partial ports**: cherry-picking code without its docs is an **ungoverned change on the target branch** — open a CHG on the target branch that links the source branch's CHG (or state there is none), and sync structure docs there too.
- **Shared baseline**: genuinely cross-branch requirements/rules belong in a shared baseline (e.g. the main branch, or knowledge tagged "all branches"), not laterally referenced from a feature branch.

