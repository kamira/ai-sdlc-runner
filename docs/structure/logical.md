# Logical Structure

Answers: FR-1..FR-14. Describes layers, responsibilities, and one-way dependencies.

## Layers / modules
| Layer/Module | Responsibility | Depends on |
|--------------|----------------|------------|
| `cli` | Parse `run`/`migrate`/`status`/`menu`; bare `runner` opens the menu; load config; dispatch | `contract`, `orchestrator`, `state`, `tui` |
| `tui` | Interactive menu helper: arrow-key list (stdlib curses) with numbered fallback; collects a choice only | (stdlib only) |
| `dashboard` | Multi-panel view (狀態/執行日誌/檢驗結果/agent log); consumes orchestrator events + reads state/ACC/git; curses viewer + text snapshot | `contract`, `state` (read), git (stdlib only) |
| `orchestrator` | Drive the four stages sequentially; per-stage halt gate; shallow fan-out in implement; checkpoint at each boundary | `contract`, `gates`, `agents`, `state` |
| `contract` | Read skill version (from file), compute major.minor key, resolve/write per-project lock, validating migrate | (reads skill SKILL.md) |
| `agents` | Parse the skill's role table; spawn agents with role-scoped tool allowlists | (reads skill agent-hierarchy.md) |
| `gates` | Subprocess-call the skill's `halt_gate.py` / `cross_repo_check.py`; branch on exit code | (calls skill scripts) |
| `state` | Load/save `state.json`; support `--resume` | — |
| `config (runner.yaml)` | Hold runtime-variable limits & skill path | — |

## Main flows
1. **`runner run <project>`**: load config → `contract.resolve_contract` (lock gate; mismatch → tell user to migrate) → probe runtime caps → `state` load (`--resume`) → orchestrator runs stage 1..4, each calling `gates.check_halt`; implement stage spawns shallow I1.x; acceptance spawns independent V1 → checkpoint per stage → `before_merge_or_release` gate before delivery.
2. **`runner migrate <project> --to <ver>`**: `contract.migrate` re-reads ALL docs/CHG/ACC/structure under the new contract; all parse → write new lock; any fail → print incompatibility list, keep old lock.
3. **`runner status <project>`**: read `.sdlc-lock.json` + `state.json`; report locked contract, current stage, completed items.

4. **`runner` (no subcommand) or `runner menu`**: `tui.select` shows an arrow-key list (curses) or a
   numbered fallback; the chosen action prompts for project/version/risk and dispatches to the
   existing `run`/`migrate`/`status` handlers. The menu adds no governance behavior — a "Run" from it
   goes through the same orchestrator and still halts at `before_merge_or_release`.
5. **`runner dashboard <project>` / `run --dashboard`**: the orchestrator emits events (stage, gate,
   agent dispatch/result, checkpoint, halt) to an optional `on_event` sink; `dashboard.DashboardModel`
   accumulates them and also reads `state.json`/`.sdlc-lock.json`/`docs/acceptance/`/git to render four
   panels (狀態 = branch + progress + status; 執行日誌; 檢驗結果; agent log, merged or tabbed). Read-only:
   the dashboard cannot alter the run; a dashboard-driven run still halts at the red-line gate.

## Dependency direction
One-directional: `cli → {orchestrator, tui, dashboard}`; `orchestrator → {contract, gates, agents, state}`;
`dashboard → {contract, state}` (read-only) + git. `tui`/`dashboard` add no third-party dependency. The
orchestrator emits events to `dashboard` via an optional callback — `dashboard` never calls back into the
orchestrator's control flow. The runner depends on the skill; **the skill never depends on the runner**.
No module re-implements another's logic; governance truth flows from the skill outward (read/call),
never duplicated inward.
