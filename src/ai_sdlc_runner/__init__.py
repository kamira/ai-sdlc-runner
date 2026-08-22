"""ai-sdlc-runner — a governed development agent.

It walks an ordinary development flow — PM plans, the lead judges feasibility, engineers build one
small module each, the lead reviews, a panel cross-checks, QA verifies, feedback returns to PM — and
decides at every step whether that step may proceed on its own or has to stop and ask a person.

The flow lives in `graph.py` and the governance in `policy.py`. Both are this project's own: nothing
here reads an external contract, and nothing here depends on another vendor's agent.
"""

__version__ = "0.1.0"
