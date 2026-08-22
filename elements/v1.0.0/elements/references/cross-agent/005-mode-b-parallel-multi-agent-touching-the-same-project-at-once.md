## Mode B: parallel multi-agent (touching the same project at once)

Risks: overwriting each other, conflicting structure docs, duplicate/conflicting changes, CHG number clashes. Mechanism:

- **Claim**: before starting, declare in the coordination file (below) "my **role**, I'm doing X, locking scope Y, my **read/write permission**", with owner + time + status (in progress). Claim first, then work.
- **Role and read/write permission**: every agent has an explicit role (implementer / verifier / integrator / reviewer…) and a **readable/writable scope**. Least privilege: grant only the write scope that role needs. E.g. the verifier is **read-only** (must not edit the code under review); the implementer may write only its claimed scope; structure docs are written by whoever owns that module. This both prevents accidental edits in parallel and is the precondition for independent acceptance.
- **Scope boundary**: claim **non-overlapping** module/file scopes. On overlap, the later agent waits or coordinates — never barges in.
- **Single-writer rule**: the same structure doc / same module is written by only one agent at a time, to avoid races.
- **Reserve CHG numbers**: CHG uses date+sequence; reserve the number at claim time (e.g. CHG-YYYYMMDD-03) so two agents don't collide.
- **Release on completion**: after finishing your CHG + ACC, update the coordination file to mark the claim done and release the scope.
- **Integration acceptance**: if two parallel changes touch the same structure or depend on each other, run one "integration acceptance" to confirm mutual compatibility (by one of the agents or a dedicated integration session) — two independent green lights aren't enough.
- **Conflict handling**: if your assumption conflicts with someone's already-committed CHG → **stop**, read their CHG's decisions/trade-offs, reconcile; return to `modification-guide` for a fresh impact analysis if needed.

