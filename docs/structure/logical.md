# Logical Structure

Answers: FR-1..FR-14. Describes layers, responsibilities, and one-way dependencies.

## Layers / modules
| Layer/Module | Responsibility | Depends on |
|--------------|----------------|------------|
| `cli` | Parse `run`/`migrate`/`status`; load config; dispatch to orchestrator/contract | `contract`, `orchestrator`, `state` |
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

## Dependency direction
One-directional: `cli → orchestrator → {contract, gates, agents, state}`. The runner depends on the
skill; **the skill never depends on the runner**. No module re-implements another's logic; governance
truth flows from the skill outward (read/call), never duplicated inward.
