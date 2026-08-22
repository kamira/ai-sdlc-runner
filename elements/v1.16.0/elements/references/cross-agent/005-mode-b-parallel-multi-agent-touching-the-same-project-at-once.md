## Mode B: parallel multi-agent (touching the same project at once)

Risks: overwriting each other, conflicting structure docs, duplicate/conflicting changes, CHG number clashes. Mechanism:

- **Claim**: before starting, declare in the coordination file (below) "my **role**, I'm doing X, locking scope Y, my **read/write permission**", with owner + start/**last-updated** time (UTC+0) + status (in progress). Claim first, then work.
- **Claim lease & stale takeover (anti-deadlock)**: a claim is a **lease, not permanent ownership** — refresh its last-updated time whenever you update the worklog/coordination file. A claim past its lease (suggest 24h, judged on the UTC+0 clock; team-adjustable) with **no worklog/coordination update and no matching git activity** is **stale** (the owner likely died mid-run): don't wait forever — mark it `stale, taken over by <id> at <time>` in the coordination file (don't delete the original), reconcile its worklog + working tree (see handshake) to determine how far it got, then take over or release the scope.
- **Role and read/write permission**: every agent has an explicit role (implementer / verifier / integrator / reviewer…) and a **readable/writable scope**. Least privilege: grant only the write scope that role needs. E.g. the verifier is **read-only** (must not edit the code under review); the implementer may write only its claimed scope; structure docs are written by whoever owns that module. This both prevents accidental edits in parallel and is the precondition for independent acceptance.
- **Scope boundary**: claim **non-overlapping** module/file scopes. On overlap, the later agent waits or coordinates — never barges in.
- **Single-writer rule**: the same structure doc / same module is written by only one agent at a time, to avoid races.
- **Physical isolation (worktrees)**: a claim is only a **logical** lock — two agents in the **same working tree** still see and trample each other's uncommitted changes. Under real parallelism, give each agent its own `git worktree` (or clone); merging back goes through the normal merge flow + integration acceptance. Claim = who may do it; worktree = where they do it.
- **Reserve CHG numbers**: CHG uses date+sequence; reserve the number at claim time (e.g. CHG-YYYYMMDD-03) so two agents don't collide.
- **Release on completion**: after finishing your CHG + ACC, update the coordination file to mark the claim done and release the scope.
- **Integration acceptance**: if two parallel changes touch the same structure or depend on each other, run one "integration acceptance" to confirm mutual compatibility (by one of the agents or a dedicated integration session) — two independent green lights aren't enough.
- **Conflict handling**: if your assumption conflicts with someone's already-committed CHG → **stop**, read their CHG's decisions/trade-offs, reconcile; return to `modification-guide` for a fresh impact analysis if needed.

