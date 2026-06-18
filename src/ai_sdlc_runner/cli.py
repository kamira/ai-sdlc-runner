"""cli.py — entry point: ``run`` / ``migrate`` / ``status`` subcommands.

Loads ``config/runner.yaml`` (PyYAML if available, else a tiny built-in reader so the runner has
zero hard dependencies), then dispatches to the orchestrator / contract layer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from . import contract, dashboard, orchestrator, state, tui

DEFAULT_CONFIG = "config/runner.yaml"


# --------------------------------------------------------------------------------------
# Config loading (no hard YAML dependency)
# --------------------------------------------------------------------------------------

def load_config(path: str | Path) -> dict:
    """Load runner.yaml. Use PyYAML if installed; otherwise parse the flat key: value file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"config not found: {p}")
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return _mini_yaml(text)


def _mini_yaml(text: str) -> dict:
    """Minimal parser for the flat ``key: value`` shape of runner.yaml (no nesting)."""
    out: dict = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip().strip("'\"")
        if val.lstrip("-").isdigit():
            out[key] = int(val)
        else:
            out[key] = val
    return out


def _resolve_skill_path(config: dict, override: Optional[str]) -> str:
    return override or config.get("skill_path", "./ai-skills/skills/ai-sdlc")


# --------------------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    skill_path = _resolve_skill_path(config, args.skill_path)
    requested = args.contract_version or config.get("contract_version")

    # In a real run the executor/approver are platform-bound; --dry-run uses stubs and
    # an approver that never auto-approves, so red-line gates correctly stop.
    # With --dashboard, collect events into a model and stream a one-line feed as they arrive.
    use_dash = getattr(args, "dashboard", False)
    model = dashboard.DashboardModel(project_dir=str(args.project)) if use_dash else None

    def on_event(ev: dict) -> None:
        model.add(ev)
        # Lightweight live feed (the full panel view is rendered after the run / at halt).
        t = ev.get("type")
        if t == "stage":
            print(f"▶ {ev.get('stage')}")
        elif t == "gate":
            print(f"  gate {ev.get('gate')} -> {ev.get('result')}")
        elif t == "agent":
            if ev.get("phase") == "dispatch":
                print(f"    · agent {ev.get('role')} dispatched")

    report = orchestrator.run(
        args.project,
        skill_path=skill_path,
        config=config,
        requested_version=requested,
        risk=args.risk,
        resume=args.resume,
        agent_executor=None,           # stub executor (dry-run friendly)
        approver=None,                 # no auto-approval; HALT gates stop the run
        on_event=on_event if use_dash else None,
    )

    if model is not None:
        print()
        dashboard.view(model, getattr(args, "agent_view", dashboard.AGENT_VIEW_MERGED))
        print()

    print(f"status: {report.status}")
    print(f"contract: {report.contract_version}")
    if report.caps:
        print(f"caps: concurrency<={report.caps.concurrency_max}, nesting<={report.caps.nesting_depth_max}")
    print(f"stages run: {', '.join(report.stages_run) or '(none)'}")
    for d in report.decisions:
        print(f"  gate {d.gate} [{d.risk}] -> {d.result}: {d.reason}")
    if report.status == "halted_for_approval":
        print(f"HALTED at gate '{report.halted_at}' — awaiting human approval.\n  {report.detail}")
        return 10
    if report.status == "migrate_required":
        print(report.detail)
        return 20
    return 0


def cmd_migrate(args: argparse.Namespace) -> int:
    result = contract.migrate(args.project, args.to)
    print(f"migrate -> {result.to_version}")
    print(f"checked {len(result.checked)} doc(s)")
    if result.ok:
        print("OK: all docs re-parsed under the new contract; lock raised.")
        return 0
    print("BLOCKED: the following did not parse under the new contract (lock left unchanged):")
    for item in result.incompatibilities:
        print(f"  - {item}")
    return 1


def cmd_menu(args: argparse.Namespace) -> int:
    """Interactive menu (arrow-key when on a TTY, numbered fallback otherwise).

    The menu only *collects inputs* and dispatches to the existing commands, so every halt gate and
    red-line stop still applies — a "Run" launched here goes through the same orchestrator.
    """
    actions = [
        ("Run four-stage loop", "drive a project through requirement→structure→implement→acceptance"),
        ("Dashboard", "open the multi-panel dashboard for a project (status/log/verify/agents)"),
        ("Check skill updates", "detect whether the local skill location is newer than the lock"),
        ("Migrate contract", "validating contract upgrade (re-read all docs first)"),
        ("Status", "show the per-project lock + run state"),
        ("Help", "show command-line help"),
        ("Exit", "quit"),
    ]
    while True:
        idx = tui.select("ai-sdlc-runner — what would you like to do?", actions)
        if idx is None:
            return 0
        choice = actions[idx][0]
        if choice == "Exit":
            return 0
        if choice == "Help":
            build_parser().print_help()
            continue
        if choice == "Status":
            project = tui.prompt("Project path")
            if project:
                cmd_status(argparse.Namespace(project=project))
            continue
        if choice == "Migrate contract":
            project = tui.prompt("Project path")
            to = tui.prompt("Target contract version", "")
            if project and to:
                cmd_migrate(argparse.Namespace(project=project, to=to))
            continue
        if choice == "Dashboard":
            project = tui.prompt("Project path")
            if project:
                view = _ask_agent_view()
                cmd_dashboard(argparse.Namespace(project=project, agent_view=view,
                                                 config=args.config, skill_path=args.skill_path))
            continue
        if choice == "Check skill updates":
            project = tui.prompt("Project path (blank = compare to config-expected)", "")
            cmd_check(argparse.Namespace(project=project or None, config=args.config,
                                         skill_path=args.skill_path))
            continue
        if choice == "Run four-stage loop":
            project = tui.prompt("Project path")
            if not project:
                continue
            risk = tui.prompt("Risk (low/medium/high)", "medium") or "medium"
            want_dash = (tui.prompt("Show dashboard? (y/N)", "N") or "N").lower().startswith("y")
            view = _ask_agent_view() if want_dash else dashboard.AGENT_VIEW_MERGED
            cmd_run(argparse.Namespace(
                project=project,
                config=args.config,
                skill_path=args.skill_path,
                contract_version=None,
                risk=risk if risk in ("low", "medium", "high") else "medium",
                resume=False,
                dashboard=want_dash,
                agent_view=view,
            ))
            continue
    return 0


def _ask_agent_view() -> str:
    """Menu choice: consolidate agent logs in one panel (default) or tabbed per agent."""
    options = [
        ("Consolidated (one panel)", "all agents interleaved in one chronological log"),
        ("Tabbed (per agent)", "group the log by agent (A1/I1/I1.x/V1)"),
    ]
    idx = tui.select("Agent log layout?", options)
    return dashboard.AGENT_VIEW_TABBED if idx == 1 else dashboard.AGENT_VIEW_MERGED


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Render the multi-panel dashboard for a project from its saved state/ACC/git."""
    skill_path = None
    try:
        config = load_config(args.config)
        skill_path = _resolve_skill_path(config, getattr(args, "skill_path", None))
        expected = config.get("contract_version")
    except (FileNotFoundError, OSError):
        expected = None
    model = dashboard.DashboardModel.from_saved(args.project, skill_path=skill_path, expected=expected)
    dashboard.view(model, getattr(args, "agent_view", dashboard.AGENT_VIEW_MERGED))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Detect whether the local skill location has an update relative to the project lock / expected."""
    config = load_config(args.config)
    skill_path = _resolve_skill_path(config, args.skill_path)
    expected = config.get("contract_version")
    info = contract.detect_update(skill_path, expected=expected, project_dir=args.project)
    print(f"local skill:   {info.local}")
    print(f"baseline:      {info.baseline or '(none)'}"
          + (f"   [project lock]" if args.project else "   [config expected]"))
    if info.latest_tag:
        print(f"newest tag:    v{info.latest_tag}")
    print(f"status:        {info.kind} — {info.message}")
    return 20 if info.needs_migrate else 0


def cmd_status(args: argparse.Namespace) -> int:
    lock = contract.read_lock(args.project)
    st = state.load(args.project)
    if lock is None:
        print(f"{args.project}: no contract lock (never run).")
    else:
        print(f"{args.project}: locked at {lock['contract_major']}.{lock['contract_minor']}.x "
              f"(recorded {lock['contract_version']}, first run {lock['first_run']})")
    if st is None:
        print("  no run state.")
    else:
        print(f"  stage: {st.stage}; completed: {', '.join(st.completed) or '(none)'}")
    # Best-effort skill-update line (skipped silently if the skill location can't be read).
    try:
        config = load_config(getattr(args, "config", DEFAULT_CONFIG))
        skill_path = _resolve_skill_path(config, getattr(args, "skill_path", None))
        info = contract.detect_update(skill_path, expected=config.get("contract_version"),
                                      project_dir=args.project)
        print(f"  skill: local {info.local} vs baseline {info.baseline or '?'} → {info.kind}"
              + ("  (run migrate)" if info.needs_migrate else ""))
    except Exception:
        pass
    return 0


# --------------------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="runner", description="External orchestrator for the ai-sdlc skill.")
    p.add_argument("--config", default=DEFAULT_CONFIG, help=f"path to runner.yaml (default {DEFAULT_CONFIG})")
    # Not required: bare `runner` (no subcommand) opens the interactive menu.
    sub = p.add_subparsers(dest="command", required=False)

    pmenu = sub.add_parser("menu", help="interactive menu (arrow-key selectable list)")
    pmenu.add_argument("--skill-path", default=None, help="override skill_path (e.g. a local skill cache)")
    pmenu.set_defaults(func=cmd_menu)

    pr = sub.add_parser("run", help="drive the four-stage loop for a project")
    pr.add_argument("project", help="path to the governed project directory")
    pr.add_argument("--contract-version", default=None, help="expected contract version (defaults to config)")
    pr.add_argument("--skill-path", default=None, help="override skill_path (e.g. a local skill cache)")
    pr.add_argument("--risk", default="medium", choices=["low", "medium", "high"], help="overall change risk")
    pr.add_argument("--resume", action="store_true", help="continue from the last checkpoint")
    pr.add_argument("--dashboard", action="store_true", help="show the multi-panel dashboard while running")
    pr.add_argument("--agent-view", default=dashboard.AGENT_VIEW_MERGED,
                    choices=[dashboard.AGENT_VIEW_MERGED, dashboard.AGENT_VIEW_TABBED],
                    help="agent log layout: merged (default) or tabbed per agent")
    pr.set_defaults(func=cmd_run)

    pd = sub.add_parser("dashboard", help="open the multi-panel dashboard for a project")
    pd.add_argument("project", help="path to the governed project directory")
    pd.add_argument("--skill-path", default=None, help="override skill_path (enables the skill-update line)")
    pd.add_argument("--agent-view", default=dashboard.AGENT_VIEW_MERGED,
                    choices=[dashboard.AGENT_VIEW_MERGED, dashboard.AGENT_VIEW_TABBED],
                    help="agent log layout: merged (default) or tabbed per agent")
    pd.set_defaults(func=cmd_dashboard)

    pm = sub.add_parser("migrate", help="validating contract upgrade for a project")
    pm.add_argument("project", help="path to the governed project directory")
    pm.add_argument("--to", required=True, help="target contract version")
    pm.set_defaults(func=cmd_migrate)

    ps = sub.add_parser("status", help="show lock + run state for a project")
    ps.add_argument("project", help="path to the governed project directory")
    ps.add_argument("--skill-path", default=None, help="override skill_path")
    ps.set_defaults(func=cmd_status)

    pc = sub.add_parser("check", help="detect whether the local skill has an update for a project")
    pc.add_argument("project", nargs="?", default=None, help="project dir (compare to its lock); omit to compare to config-expected")
    pc.add_argument("--skill-path", default=None, help="override skill_path (the local skill location to check)")
    pc.set_defaults(func=cmd_check)
    return p


def main(argv: Optional["list[str]"] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        # Bare `runner` → interactive menu (with config; skill_path defaults to config's value).
        return cmd_menu(argparse.Namespace(config=args.config, skill_path=None))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
