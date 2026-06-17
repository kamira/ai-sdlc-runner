# Data Structure

Answers: FR-3, FR-4, FR-5, FR-10. The runner persists two small JSON objects; it owns no database.

## Entities / objects

### .sdlc-lock.json (per governed project)
| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| contract_major | int | required | Locked major; compared at the gate |
| contract_minor | int | required | Locked minor; compared at the gate |
| contract_version | str | required | Full version at lock time; record-only (not compared) |
| first_run | str (ISO-8601) | required | Timestamp of first run that wrote the lock |
| runner | str | required | Runner version/identity that wrote the lock |

Lives in the **governed project's** working dir and travels with that project's git. Not to be
confused with the project's own product version.

### state.json (per governed project run)
| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| stage | str (enum) | required | Current stage (see enum below) |
| completed | list[str] | required | Completed stage ids, for `--resume` |
| artifacts | object | optional | Per-agent product metrics/paths (e.g. produced doc paths) |
| updated | str (ISO-8601) | required | Last checkpoint time |

### config/runner.yaml (static, repo-level)
| Field | Type | Constraint | Description |
|-------|------|------------|-------------|
| contract_version | str | required | Expected contract version |
| skill_path | str | required | Path to the skill (inside the submodule, or a local cache) |
| concurrency_max | int | 1..n | Fan-out concurrency cap (default 4) |
| nesting_depth_max | int | 1..n | Fan-out nesting cap (default 3) |

## Relations
- One `.sdlc-lock.json` and one `state.json` per governed project (1:1 with a project directory).
- `config/runner.yaml` is global to the runner; one per runner install.
- No foreign keys / relational DB — flat JSON files keyed by project directory.

## Indexes / constraints
- Lock comparison key = `(contract_major, contract_minor)`; uniqueness is the project directory itself.
- `state.completed` is append-only within a run; `--resume` skips stages already in it.
- Deletion strategy: lock/state files are plain files; removing them resets governance for that project (a human action, never automated).

## States / enums
- **stage**: `requirement_analysis` → `structure_design` → `implement` → `acceptance` → `done`.
- **halt gate**: `requirement_confirmed | structure_confirmed | before_implement | acceptance_failed | before_merge_or_release`.
- **risk**: `low | medium | high`.
- **halt decision**: `AUTO (exit 0) | HALT (exit 10)`.
- **role**: `A1 | I1 | I1.x | V1`.
