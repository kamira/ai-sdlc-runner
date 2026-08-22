## Four-state routing

```
find a ledger (do not assume docs/)
├─ found ──────────────────────► governed: go to handshake
└─ not found
   ├─ no existing code ────────► init
   ├─ existing code ───────────► adopt
   └─ docs/ exists but is theirs ► decide the location first (below), then take one of the two
```

"Existing code" means: any source, tests, or build configuration beyond docs and settings.
**When you cannot tell, fall toward `adopt`** — treating an empty repo as brownfield costs a few
extra questions; treating a brownfield repo as empty costs someone else's files (KN-004: follow
where the cost of being wrong falls).

