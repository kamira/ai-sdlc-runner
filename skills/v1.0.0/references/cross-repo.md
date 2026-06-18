---
name: cross-repo
description: >
  Cross-repo coordination and consistency: when one requirement or change spans multiple git repos
  (e.g. frontend + backend + shared lib), governance docs are scattered across repos, leading to
  contract mismatches, "which repo is the source of truth?", and half-done changes (changed repo A,
  forgot repo B). Read this when a requirement touches multiple repos, repos share a contract
  (API / data format / events), or you take over a multi-repo system. Covers authority source +
  local view + pointer, cross-repo coordinated change (XCHG), cross-repo anti-drift, and integration
  acceptance. Applies to solo and teams.
---

# cross-repo — cross-repo coordination & consistency

> 語言 / Language: [繁體中文](cross-repo.zh-tw.md) · **English**

## Purpose

When one requirement/change spans multiple git repos (frontend + backend + shared lib, microservices…), governance docs are scattered across repos, and three problems are common: **contract mismatch** (one side changed the API, the other didn't follow), **"which repo is the source of truth?"**, and **half-done changes** (changed repo A, forgot repo B). This file defines a single cross-repo source of truth, coordinated changes, and consistency checks. **It happens solo (several of your own repos) or in a team.**

## When to read

- A requirement/feature needs **changes in multiple repos at once**
- Multiple repos **share a contract** (REST/GraphQL API, data format, event schema, shared types)
- You take over a system made of multiple repos

## Core: authority source + local view + pointer

- **Designate an authority source**: one repo (or a dedicated governance/contract repo) holds the **cross-repo contract + shared Guideline** = the single source of truth.
- Each participating repo keeps a **local view** (its own part of `docs/`) + a **pointer to the authority**: authority location (repo/path) + a **pinned version** (commit / tag / version).
- **Don't copy a drift-prone contract into multiple repos**; the contract exists once at the authority, and other repos reference its version.

```
authority-repo/docs/contracts/   ← single truth: cross-repo contract + shared Guideline
repoA/docs/authority.md          ← pointer: authority @ v3 (commit abc123)
repoB/docs/authority.md          ← pointer: authority @ v3 (commit abc123)
```

## Cross-repo coordinated change (XCHG)

- A logical change spanning repos → open a **coordinated change `XCHG-YYYYMMDD-NN`** at the authority, describing the overall intent, which repos are involved, and how the contract version changes.
- Each repo's **local CHG** links back to that XCHG in its "Related" field; the XCHG lists each repo's child CHG → **two-way traceability**.
- **Order of contract changes**: the authority changes the contract first (version +1) → each consuming repo opens a CHG to follow and updates its local pointer to the new version. Change the contract first, then the consumers, so consumers don't build against a stale contract.

## Cross-repo anti-drift (extends doc-integrity)

Each repo's doc verification additionally compares: **does the local "authority pointer version" equal the authority's current contract version?** Behind = cross-repo drift (that repo is still on an old contract) and must catch up.

**Executable check**: this skill bundles `scripts/cross_repo_check.py`, which reads each repo's pinned version in `docs/authority.md` vs the authority's `docs/contracts/VERSION`; on mismatch it reports and exits non-zero (wire it into pre-commit / CI). Usage:

```bash
python3 scripts/cross_repo_check.py manifest.json
# manifest.json: { "authority": "authority-repo", "repos": ["repoA","repoB"] }
```

See the `examples/cross-repo/` template project in the repo (authority + two consumer repos + an XCHG example).

## Cross-repo acceptance (integration acceptance)

A change spanning repos is **not done just because each repo's own ACC passes**. There must be one **integration acceptance**: confirm the repos work together (contract compatible, end-to-end flow passes). On XCHG close-out, link each repo's ACC + one integration ACC; any repo failing or integration failing = overall fail.

## Coordinated change template (XCHG)

At the authority `docs/changes/XCHG-YYYYMMDD-NN.md`:

```markdown
# XCHG-YYYYMMDD-NN — <cross-repo change title>

- Authority: <authority repo / contract path>
- Repos involved: <repoA, repoB, ...>
- Risk: high / medium / low
- Contract version: vN → vN+1 (what contract changed)
- Per-repo child changes: repoA → CHG-...; repoB → CHG-...
- Integration acceptance: <integration ACC link>
- Status: draft / implementing across repos / integration accepted

## Motivation / overall intent
...
## Per-repo impact and order
<who changes first; contract compatibility and migration>
```

## Local pointer template

In each participating repo, `docs/authority.md`:

```markdown
# Authority pointer
- Authority source: <authority repo URL / contract path>
- Pinned version: vN (commit / tag)
- This repo's role: contract provider / consumer
- Last synced: YYYY-MM-DD
```

## Relation to the rest of the flow

- Extends the "Project" concept: one project may = multiple repos; **XCHG is the cross-repo version of a CHG**.
- Extends doc-integrity: adds a "cross-repo pointer version consistency" check.
- Extends acceptance: adds an "integration acceptance" layer across repos.
- Compatible with cross-agent / agent-worklog: different repos can be owned by different agents, each claiming that repo's scope.
