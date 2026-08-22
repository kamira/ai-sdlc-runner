## Role startup spec (tools allowlist)

Each agent is **granted a tools allowlist at startup, by role** (least privilege). This spec is the authorization basis when an **outer tool (python, etc.) invokes/runs an AI** to act as a role; it **also applies to traditional pure CLI / GUI operation** — "can execute" covers running commands, running tests, and driving a GUI, not just AI calls.

| Role | Can spawn (`Agent` tool) | Can write code/structure | Can execute (CLI / script / GUI) | Notes |
|------|--------------------------|--------------------------|----------------------------------|-------|
| A1 analysis | ✗ | ✗ (writes docs/ only) | ✓ (read code, run analysis tools) | analysis only |
| I1 lead impl | ✓ (dispatch I1.x) | ✓ own scope | ✓ | gets `Agent` because it dispatches |
| I1.x sub-impl | ✗ | ✓ own module | ✓ | no further dispatch → no `Agent` |
| **V1 verifier** | **✗ (tools exclude `Agent`)** | **✗ (read-only on the code/structure under review)** | **✓ may run tests/scripts/CLI/GUI to verify** | reads code & criteria, writes only its ACC; **cannot spawn sub-agents or edit the code under review**, but **may execute** for multi-scenario verification |

> **"Read-only" ≠ "cannot execute"**: V1's read-only means "cannot modify the code/structure under review and cannot spawn sub-agents"; it **may still** run tests via python/CLI or drive a GUI to verify (acceptance needs this). Putting "no `Agent` tool" in V1's startup spec mechanically guarantees it won't "fix while verifying" or spawn agents — more reliable than discipline alone.

