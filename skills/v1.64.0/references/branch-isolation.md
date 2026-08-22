---
name: branch-isolation
description: >
  Branch isolation: when multiple git branches run in parallel, each branch's requirements, change
  records, acceptance, and verification apply only to THAT branch and must not reference
  requirements opened on other branches. Read this when the project has multiple branches, or when
  you work/verify on a branch. Covers branch tagging, using only the current branch's sources, the
  "brought in only at merge" rule, and the distinction from cross-repo.
---

# branch-isolation — branch isolation

> 語言 / Language: [繁體中文](branch-isolation.zh-tw.md) · **English**

## Purpose

With parallel branches, different branches often open different requirements and changes. **When working or verifying on a branch, all requirements/CHG/ACC/verification may reference only that branch's sources, never requirements opened on other branches** — otherwise you'd verify branch A's code against branch B's requirements, causing wrong gating and scope contamination.

> Distinction from `cross-repo`: cross-repo coordinates a contract across multiple repos; branch-isolation is about multiple branches within one repo not referencing each other's requirements. Both can coexist.

## Rules

- **Tag the branch**: the Guideline / CHG / ACC header has a "Branch" field. When referencing requirements or acceptance criteria, take only those on the **same branch as current**.
- **Only current-branch sources**: in detection/acceptance/impact analysis, filter out other branches' CHGs/requirements. Current branch = the one confirmed in the entry handshake.
- **No cross-branch reference**: branch A's acceptance may not use branch B's requirements as the baseline; branch A's CHG may not cite branch B's requirement as its basis.
- **Brought in only at merge**: another branch's requirements/changes enter the current branch only when **merged in**, via the normal flow (modification-guide + acceptance); before the merge they are "out of this branch's scope".
- **IDs are unique per branch only**: two branches can independently open `CHG-20260702-01` — branches don't reserve numbers for each other (each has its own coordination view). Resolve collisions **at merge**: keep the target branch's numbering, renumber or suffix the imported records (e.g. `CHG-20260702-01-feat-x`) and fix links. When heavy parallel branching is expected, include the branch in the ID from the start (`CHG-<branch>-YYYYMMDD-NN`).
- **A merge is itself a change (merge-CHG)**: merging branch B in goes through modification-guide **on the target branch** — open a merge-CHG listing what's imported; **re-tag imported CHG/ACC Branch fields to the target branch** (keep the original branch in "Related"/history); resolve structure-doc conflicts **semantically** (reconcile module/boundary meaning, not just merge the text); then run acceptance on the merged result.
- **Cherry-pick / partial ports**: cherry-picking code without its docs is an **ungoverned change on the target branch** — open a CHG on the target branch that links the source branch's CHG (or state there is none), and sync structure docs there too.
- **Shared baseline**: genuinely cross-branch requirements/rules belong in a shared baseline (e.g. the main branch, or knowledge tagged "all branches"), not laterally referenced from a feature branch.

## When to read

- The project has multiple branches (feature / release / hotfix…)
- You implement or verify on a branch
- You need to judge which branch a requirement/criterion belongs to

## Template field

Add to the Guideline / CHG / ACC header:

```
- Branch: <branch name>   ← the branch this doc belongs to; reference/acceptance use same-branch sources only
```

## Relation to the rest of the flow

- handshake: the first step on entry is to confirm the current branch; all references afterwards are limited to it. **Switching branches mid-session counts as a new entry — redo the handshake** (branch, unclosed stages, working tree all differ per branch).
- modification-guide / acceptance-verification: CHG/ACC carry a branch; the acceptance baseline takes only the same branch's Guideline/CHG.
- doc-integrity: can add a "CHG/ACC branch field = current git branch" check (mismatch → flag).
- knowledge: directives default to the current branch; general ones are tagged "all branches".
