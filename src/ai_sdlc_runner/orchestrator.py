"""orchestrator.py — the main loop (build-guide §4).

Drives the four ai-sdlc stages **sequentially**, each passing its halt gate; inside the implement
stage it fans out **shallowly** (depth ≤ nesting cap, concurrency ≤ concurrency cap). A checkpoint
is written at every stage boundary, so a crash can ``--resume`` and a human can gate at boundaries.

> This loop is the runner's *runtime behavior spec* — what the runner does when it drives **another**
> project. (Building the first runner itself went through the ai-sdlc four stages by hand; see
> docs/changes/CHG-20260617-01.md.)

Halt-point decisions and role definitions are **not** re-implemented here — they come from
``gates`` (which calls the skill's ``halt_gate.py``) and ``agents`` (which parses the skill's role
table). Agent execution and human approval are injected, so the loop is dry-runnable with stubs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import agents, contract, gates, state

# Injected callables -------------------------------------------------------------------
# agent_executor(spec) -> dict : actually run an agent (platform-bound at runtime).
# approver(decision)    -> bool: a human decision at a HALT gate (True = approved to continue).
# on_event(event: dict)        : optional observer for the dashboard; never affects control flow.
AgentExecutor = Callable[[agents.AgentSpec], dict]
Approver = Callable[[gates.Decision], bool]
EventSink = Callable[[dict], None]


@dataclass
class RuntimeCaps:
    concurrency_max: int
    nesting_depth_max: int


@dataclass
class RunReport:
    status: str = "completed"          # completed | halted_for_approval | migrate_required
    contract_version: str = ""
    caps: Optional[RuntimeCaps] = None
    decisions: "list[gates.Decision]" = field(default_factory=list)
    stages_run: "list[str]" = field(default_factory=list)
    halted_at: Optional[str] = None
    detail: str = ""


def _stub_executor(spec: agents.AgentSpec) -> dict:
    """Default no-op executor for dry-runs: records the spec without launching a real agent."""
    return {"role": spec.role, "tools": spec.tools, "scope": spec.scope, "stub": True}


def _emit(sink: Optional[EventSink], **event) -> None:
    """Emit a dashboard event if a sink is attached (best-effort; never breaks the run)."""
    if sink is None:
        return
    try:
        sink(event)
    except Exception:
        pass


def probe_runtime_caps(config: dict) -> RuntimeCaps:
    """Confirm the configured fan-out caps at startup (build-guide §1.7, §4).

    The contract targets the skill's stable output, not Claude Code's current nesting/concurrency
    behavior — so these limits live in ``runner.yaml`` and are validated here. A real platform probe
    would attempt a nested spawn; we at least enforce sane bounds and never silently exceed config.
    """
    cc = int(config.get("concurrency_max", 4))
    nd = int(config.get("nesting_depth_max", 3))
    if cc < 1 or nd < 1:
        raise ValueError(f"invalid runtime caps in config: concurrency={cc}, nesting={nd}")
    return RuntimeCaps(concurrency_max=cc, nesting_depth_max=nd)


def _gate(
    report: RunReport,
    skill_path: str,
    gate: str,
    risk: str,
    approver: Optional[Approver],
    action: Optional[str] = None,
    autonomy: Optional[str] = None,
    sink: Optional[EventSink] = None,
) -> bool:
    """Run one halt gate by calling the skill. Returns True to continue, False to stop.

    On HALT: if an approver is supplied and approves, continue; otherwise stop and mark the report
    ``halted_for_approval`` (the autonomous run never self-approves a red line).
    """
    decision = gates.check_halt(skill_path, gate, risk, action=action, autonomy=autonomy)
    report.decisions.append(decision)
    _emit(sink, type="gate", gate=gate, risk=risk, result=decision.result, reason=decision.reason)
    if not decision.is_halt:
        return True
    if approver is not None and approver(decision):
        return True
    report.status = "halted_for_approval"
    report.halted_at = gate
    report.detail = decision.reason
    _emit(sink, type="halt", gate=gate, reason=decision.reason)
    return False


def run(
    project_dir: str | Path,
    *,
    skill_path: str,
    config: dict,
    requested_version: Optional[str],
    risk: str = "medium",
    resume: bool = False,
    agent_executor: Optional[AgentExecutor] = None,
    approver: Optional[Approver] = None,
    chg_autonomy: Optional[str] = None,
    delivery_action: str = "release",
    on_event: Optional[EventSink] = None,
) -> RunReport:
    """Drive the four stages for ``project_dir``.

    Order (each stage gated; checkpoint at each boundary):
      0. resolve contract lock (mismatch → ``migrate_required``); probe runtime caps; load state.
      1. requirement analysis (A1)        → gate ``requirement_confirmed``
      2. structure design (A1)            → gate ``structure_confirmed``
      3. implement (I1 + shallow I1.x)    → gate ``before_implement`` (with CHG autonomy)
      4. acceptance (independent V1)       → gate ``acceptance_failed`` only if it fails
      delivery                            → gate ``before_merge_or_release`` (red lines always halt)
    """
    report = RunReport()
    sink = on_event
    base_execu = agent_executor or _stub_executor

    def execu(spec: agents.AgentSpec) -> dict:
        """Run an agent, emitting dispatch + result events for the dashboard's agent log."""
        _emit(sink, type="agent", role=spec.role, phase="dispatch", scope=spec.scope)
        result = base_execu(spec)
        ev = {"type": "agent", "role": spec.role, "phase": "result", "scope": spec.scope}
        if isinstance(result, dict) and "passed" in result:
            ev["passed"] = bool(result["passed"])
        _emit(sink, **ev)
        return result

    # 0. Contract lock gate ------------------------------------------------------------
    try:
        version = contract.resolve_contract(project_dir, requested_version)
    except contract.MigrateRequired as exc:
        report.status = "migrate_required"
        report.detail = str(exc)
        return report
    report.contract_version = version

    report.caps = probe_runtime_caps(config)
    st = state.load(project_dir) if resume else None
    if st is None:
        st = state.RunState()
        state.save(project_dir, st)
    todo = state.remaining_stages(st)

    # 1. Requirement analysis ----------------------------------------------------------
    if "requirement_analysis" in todo:
        _emit(sink, type="stage", stage="requirement_analysis")
        spec = agents.spawn(skill_path, "A1", scope="docs/ only", task="produce docs/ai-guideline.md")
        out = execu(spec)
        if not _gate(report, skill_path, "requirement_confirmed", risk, approver, sink=sink):
            return report
        state.checkpoint(project_dir, st, "requirement_analysis", {"A1": out})
        _emit(sink, type="checkpoint", stage="requirement_analysis")
        report.stages_run.append("requirement_analysis")

    # 2. Structure design --------------------------------------------------------------
    if "structure_design" in todo:
        _emit(sink, type="stage", stage="structure_design")
        spec = agents.spawn(skill_path, "A1", scope="docs/structure", task="produce docs/structure/*.md")
        out = execu(spec)
        if not _gate(report, skill_path, "structure_confirmed", risk, approver, sink=sink):
            return report
        state.checkpoint(project_dir, st, "structure_design", {"A1_structure": out})
        _emit(sink, type="checkpoint", stage="structure_design")
        report.stages_run.append("structure_design")

    # 3. Implement (lead implementer + shallow fan-out) --------------------------------
    if "implement" in todo:
        _emit(sink, type="stage", stage="implement")
        # before_implement gate, honoring an optional CHG autonomy override (tighten-only).
        if not _gate(report, skill_path, "before_implement", risk, approver, autonomy=chg_autonomy, sink=sink):
            return report
        lead = agents.spawn(skill_path, "I1", scope="src/", task="implement per the modification guide")
        execu(lead)
        caps = report.caps
        # Shallow fan-out: at most `concurrency_max` sub-implementers, depth capped by nesting_max.
        sub_results = []
        for i in range(1, caps.concurrency_max + 1):
            sub = agents.spawn(skill_path, f"I1.{i}", scope=f"src/ module {i}", task=f"implement module {i}")
            sub_results.append(execu(sub))
            if i >= caps.nesting_depth_max:
                break  # respect the conservative depth cap
        state.checkpoint(project_dir, st, "implement", {"I1": lead.role, "subs": len(sub_results)})
        _emit(sink, type="checkpoint", stage="implement")
        report.stages_run.append("implement")

    # 4. Acceptance (independent V1; read-only; no Agent) ------------------------------
    if "acceptance" in todo:
        _emit(sink, type="stage", stage="acceptance")
        v1 = agents.spawn(skill_path, "V1", scope="read-only on code; write docs/acceptance",
                          task="multi-scenario acceptance; produce docs/acceptance/ACC-*.md")
        # Invariant re-checked here as defense in depth (agents.spawn also enforces it).
        if "Agent" in v1.tools:
            raise agents.RoleError("V1 spawned with Agent tool — invariant violated")
        result = execu(v1)
        passed = bool(result.get("passed", True))  # stub passes by default
        if not passed:
            # Failure routes back through modification governance via the acceptance_failed gate.
            if not _gate(report, skill_path, "acceptance_failed", risk, approver, sink=sink):
                return report
        state.checkpoint(project_dir, st, "acceptance", {"V1": result})
        _emit(sink, type="checkpoint", stage="acceptance")
        report.stages_run.append("acceptance")

    # Delivery: red lines always halt (deploy/release/migration/...) -------------------
    if not _gate(report, skill_path, "before_merge_or_release", "high", approver,
                 action=delivery_action, sink=sink):
        return report

    report.status = "completed"
    _emit(sink, type="done")
    return report
