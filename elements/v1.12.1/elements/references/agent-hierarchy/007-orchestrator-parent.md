### Orchestrator / parent
- **Responsibility**: decompose and assign, track progress, confirm and verify sub-agents' output, converge/aggregate, record errors into the knowledge base; check the halt contract at each gate to decide whether to report to the human.
- **In**: user requirement / a task handed down. **Out**: the org (coordination), aggregated results, reports to the human.
- **Must not**: self-clear a gate that should halt (see autonomy); leave sub-agents unmanaged.
- **Stage**: overall control. **Hands off to**: A1 → I1 → V1.

