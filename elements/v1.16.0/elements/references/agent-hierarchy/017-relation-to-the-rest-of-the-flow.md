## Relation to the rest of the flow

- Extends `cross-agent` (roles/permissions/claim): adds **ID + hierarchy + recursive delegation (narrow-only) + active parent management**.
- Extends `agent-worklog`: each numbered agent writes a worklog on entry; reports errors up; the parent consolidates them into the knowledge base.
- Extends `independent-acceptance`: when the implementation chain (I1 and its children) is done → hand off to an independent V1; the implementer never self-verifies.
- Maps to ai-sdlc stages: A1 ≈ requirement analysis / structure design; the I1 chain ≈ modification governance + implementation; V1 ≈ acceptance.
