## Core: authority source + local view + pointer

- **Designate an authority source**: one repo (or a dedicated governance/contract repo) holds the **cross-repo contract + shared Guideline** = the single source of truth.
- Each participating repo keeps a **local view** (its own part of `docs/`) + a **pointer to the authority**: authority location (repo/path) + a **pinned version** (commit / tag / version).
- **Don't copy a drift-prone contract into multiple repos**; the contract exists once at the authority, and other repos reference its version.

```
authority-repo/docs/contracts/   ← single truth: cross-repo contract + shared Guideline
repoA/docs/authority.md          ← pointer: authority @ v3 (commit abc123)
repoB/docs/authority.md          ← pointer: authority @ v3 (commit abc123)
```

