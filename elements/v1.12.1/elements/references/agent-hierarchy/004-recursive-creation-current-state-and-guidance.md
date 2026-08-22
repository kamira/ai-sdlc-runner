## Recursive creation: current state and guidance

- **Nested sub-agents are supported** (where the platform allows): a sub-agent may spawn its own sub-agents; the depth cap is **platform-dependent** (e.g. 5 on some platforms). The recursive-delegation path is usable — no need to fall back to flat.
- **But keep it shallow (2–3 levels)**: the deeper the nesting, the higher the coordination/tracking/traceback cost and the harder it is for parents to manage. Needing more depth usually means the task should be split or redesigned, not stacked deeper.
- **Use a tools allowlist to control "who can spawn"**: whether an agent can spawn sub-agents is governed by its **tool grant** — only roles that need to dispatch (e.g. lead implementer I1) get the spawn capability (`Agent` tool on Claude; **map to your platform's equivalent — this suite is not Claude-specific**); roles that don't (verifier V1, pure sub-implementers I1.x) are **not given it**, mechanically preventing them from spawning. This turns "permission narrows only" into something enforced by the tool list, not just discipline.
- **Governance principles hold at any depth**: IDs, fixed scope, no exceeding the remit, org registry, active parent management, implementer-doesn't-self-verify.

In practice: before going past 2–3 levels, ask "should this task be split finer or its boundaries redrawn?"; approaching depth 5 is a warning sign.

