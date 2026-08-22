"""cli.py — the runner's command line.

CHG-20260823-01. What is left after the skill dependency went is small on purpose: this runner drives
one flow, and the flow is `graph.py`. The subcommands that existed to manage a vendored skill —
`migrate`, `check`, the store resolution, the multi-project workspace and its structure scan — went
with the thing they managed. Nothing here resolves a skill path, because there is no skill.

## Dispatch: one process per ask

A command backend gets **one process per ask**. That is the session boundary made physical: there is
no handle to keep alive, so "closed after the ask" is not a promise a backend has to keep. The work
order goes in as JSON on stdin and nothing else does — no tool list, no role prompt, nothing a
harness owns.

`--seat-model` routes a named seat to a different command, which is what makes cross-model review
real: **the same question, different answerers.** The routing lives here and never in the order.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from . import engine, graph, policy, tui

DEFAULT_CONFIG = "config/runner.yaml"


def load_config(path: str) -> dict:
    """Read runner.yaml. PyYAML if present, else a small reader for the flat keys we use."""
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        config: Dict[str, object] = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line and not line.startswith("-"):
                key, _, value = line.partition(":")
                value = value.strip().strip('"').strip("'")
                if value:
                    config[key.strip()] = value
        return config


# --------------------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------------------

class _Stub(engine.Session):
    """Answers nothing, records that it was asked. The default, so a dry run costs nothing."""

    def ask(self, order):
        return {"backend": "stub", "node_id": order["node_id"], "role": order["role"]}

    def close(self):
        pass


class _Process(engine.Session):
    """One process per ask: the work order on stdin, whatever it prints back as the answer."""

    def __init__(self, argv: List[str], timeout: int):
        self.argv, self.timeout = argv, timeout

    def ask(self, order):
        proc = subprocess.run(self.argv, input=json.dumps(order, ensure_ascii=False),
                              capture_output=True, text=True, timeout=self.timeout)
        return {"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

    def close(self):
        pass


def session_factory(config: dict, seat_models: Optional[Dict[str, List[str]]] = None):
    """Build the factory the engine opens a session from, routing by seat where asked."""
    seat_models = seat_models or {}
    default = config.get("agent_command")
    timeout = int(config.get("agent_timeout", 600))

    def factory(seat: Optional[str] = None):
        argv = seat_models.get(seat) or default
        if not argv:
            return _Stub()
        return _Process(list(argv) if isinstance(argv, list) else str(argv).split(), timeout)

    return factory


# --------------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------------

def cmd_flow(args: argparse.Namespace) -> int:
    """Print the flow this runner drives — the fastest way to see what it will actually do."""
    graph.validate()
    for node in graph.NODES:
        who = f"[{node.role}]" if node.role else "[runner]"
        gate = f"  gate:{node.gate}" if node.gate else ""
        print(f"{node.id:22s} {who:11s} {node.label}{gate}")
        for label, target in sorted(node.branches.items()):
            print(f"{'':22s} {'':11s}   {label} → {target}")
    print(f"\n{len(graph.NODES)} nodes, {len(graph.asking_nodes())} of them ask someone; "
          f"{len(set(graph.gates_used()))} gates")
    return 0


def cmd_policy(args: argparse.Namespace) -> int:
    """Print the governance: roles, gates, seats. Ours, not read from anywhere."""
    print("roles")
    for role in policy.ROLES:
        caps = "".join(c for c, on in
                       (("s", role.can_spawn), ("w", role.can_write), ("x", role.can_execute)) if on)
        print(f"  {role.name:10s} {caps:3s} {role.label}")
    print("\ngates (risk → verdict)")
    for gate, grades in policy.GATES.items():
        print(f"  {gate:22s} " + "  ".join(f"{r}:{grades[r]}" for r in policy.RISKS))
    print(f"\nseats (floor {policy.SEAT_FLOOR})")
    for seat in policy.SEATS:
        print(f"  {seat.name:12s} {'veto' if seat.veto else '    '}  {seat.label}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Walk the flow for one change."""
    config = load_config(args.config)
    if not args.plan:
        print("error: run needs --plan <file>: the objective, instructions, done-criteria and "
              "branch choices for this change. The governance is ours; the work is not.")
        return 2
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))

    seats = args.review_seats
    high_risk = bool(args.high_risk_mode)
    if seats is not None and seats < policy.SEAT_FLOOR and not high_risk:
        high_risk = tui.confirm_high_risk(seats, policy.SEAT_FLOOR)
        if not high_risk:
            seats = None

    cfg = engine.RunConfig(
        node_specs=plan.get("node_specs", {}),
        decisions=plan.get("decisions", {}),
        risk=plan.get("risk", "high"),
        autonomy=plan.get("autonomy"),
        review_seats=seats,
        high_risk_mode=high_risk,
        journal=engine.AskJournal(args.ask_journal) if args.ask_journal else None,
    )
    seat_models = plan.get("seat_models") or {}
    try:
        report = engine.walk(cfg, session_factory(config, seat_models), enabled=True)
    except (engine.EngineError, policy.PolicyError) as exc:
        print(f"halted: {exc}")
        return 10

    for relaxation in report.relaxations:
        print(f"relaxation:    {relaxation}")
    print(f"visited:       {len(report.visited)} node(s)")
    print(f"asks:          {len(report.asks)}")
    print(f"stopped at:    {report.halted_at} — {report.halt_reason}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runner",
                                description="A governed development flow, driven end to end.")
    p.add_argument("--config", default=DEFAULT_CONFIG, help=f"path to runner.yaml (default {DEFAULT_CONFIG})")
    sub = p.add_subparsers(dest="command", required=False)

    pf = sub.add_parser("flow", help="print the flow this runner drives")
    pf.set_defaults(func=cmd_flow)

    pp = sub.add_parser("policy", help="print the roles, gates and seats")
    pp.set_defaults(func=cmd_policy)

    pr = sub.add_parser("run", help="walk the flow for one change")
    pr.add_argument("--plan", default=None, help="JSON plan: node_specs, decisions, risk")
    pr.add_argument("--review-seats", type=int, default=None,
                    help=f"how many review seats to open (default: the floor, {policy.SEAT_FLOOR})")
    pr.add_argument("--high-risk-mode", action="store_true",
                    help="allow fewer seats than the floor; the run records that it did")
    pr.add_argument("--ask-journal", default=None,
                    help="directory to journal each question in before asking it")
    pr.set_defaults(func=cmd_run)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    if not getattr(args, "func", None):
        return cmd_flow(args)
    return args.func(args)


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main())
