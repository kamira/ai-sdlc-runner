## Machine-readable contract & query tool

- Contract: [`assets/halt_policy.json`](../assets/halt_policy.json) (editable; the gates matrix + always_halt_actions).
- Query: [`scripts/halt_gate.py`](../scripts/halt_gate.py) — the orchestrator calls it at each gate to read the contract and get a decision:

```bash
python3 scripts/halt_gate.py --gate before_merge_or_release --risk high
# prints AUTO or HALT; exit code 0=AUTO, 10=HALT. Example:
#   python3 scripts/halt_gate.py --gate "$G" --risk "$R" --action "$ACTION" || await_human_approval
```

So "where to stop" is decided by the contract — the orchestrator reads the rules rather than each inferring its own: reproducible, auditable, adjustable.

