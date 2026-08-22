## Purpose

With parallel branches, different branches often open different requirements and changes. **When working or verifying on a branch, all requirements/CHG/ACC/verification may reference only that branch's sources, never requirements opened on other branches** — otherwise you'd verify branch A's code against branch B's requirements, causing wrong gating and scope contamination.

> Distinction from `cross-repo`: cross-repo coordinates a contract across multiple repos; branch-isolation is about multiple branches within one repo not referencing each other's requirements. Both can coexist.

