## Purpose

Give "running the flow autonomously" clear boundaries: **which gates may proceed on their own (auto) and which must halt and await human approval (halt)**. This is a contract for an agent that auto-runs several stages, or an orchestrator (Python, etc.) driving this flow — express the halt points as **machine-readable rules** the orchestrator reads, rather than inferring from Risk by feel.

> Note: this differs from `ci-cd`'s pre-commit / pipeline — those gate "commit/merge"; this gates "should we pause mid-autonomous-run and wait for a human". They are complementary.

