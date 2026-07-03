# Design Structure

Answers: FR-1..FR-14. Key components, their contracts, and design trade-offs.

## Key components
| Component | Responsibility | External interface/contract |
|-----------|----------------|------------------------------|
| `contract.read_skill_version` | Read version from SKILL.md frontmatter | `(skill_path) -> str`; supports top-level `version:` and nested `metadata.version:` |
| `contract.contract_key` | Reduce to lock key | `("1.2.3") -> (1, 2)` (ignores patch) |
| `contract.resolve_contract` | Per-project lock resolution | `(project_dir, requested) -> str`; first run writes lock; mismatched (major,minor) → raise `MigrateRequired`; same/None → continue |
| `contract.migrate` | Validating upgrade | `(project_dir, to_version) -> MigrateResult`; re-read all docs; all parse → raise lock; else list incompatibilities, keep lock |
| `contract.detect_update` | Update detection | `(skill_path, expected=None, project_dir=None) -> UpdateInfo{local, baseline, kind, needs_migrate, latest_tag}`; baseline = project lock else expected; read-only |
| `contract.available_version_tags` | Newer-tag signal | `(skill_path) -> list[str]` newest first; parses `ai-sdlc-vX.Y.Z`/`vX.Y.Z` git tags; `[]` if not a repo |
| `skillstore.store_versions` / `resolve_path` | Offline store | list versions (newest first); resolve by exact version or major.minor (highest patch) or latest |
| `skillstore.detect` | Store update | compare newest store version to project lock/expected (reuses `contract.detect_update`) |
| `executors.from_config` | Backend factory | `(config, override_backend) -> Executor`; stub/command/api; defaults to stub |
| `executors.build_request` / `parse_response` | API adapters | pure `(provider, …) -> (url, headers, body)` / `(provider, raw) -> str` for anthropic/openai/generic |
| `Executor.run` | Agent call | `(AgentSpec) -> dict`; command via subprocess (in `spec.workdir`), api via urllib; key from env |
| `CommandExecutor.extra_args` / `.extra_env` | Generic passthrough (CHG-20260703-02) | `extra_args: list[str]` appended to `argv`; `extra_env: dict[str,str]` merged into the subprocess env on top of the inherited one; both default empty (no-op); read from `executor.command.{extra_args,extra_env}` in config; `api`/`stub` unaffected |
| `workspace.Workspace` | Multi-project model | `authority` + `consumers`; `save`/`load` (`.sdlc-workspace.json` at authority); `validate`; `manifest()` for cross_repo_check |
| `structure_scan.analyze_workspace` | Structure pass | scan + scaffold four structures; multi → authority `docs/contracts/VERSION` + consumer `docs/authority.md` (`Pinned version: vX`) |
| `agents.parse_role_table` | Parse role allowlist table | `(skill_path) -> {role: {tools, can_spawn, writable, scope}}` |
| `agents.spawn` | Start a role-scoped agent | `(role, scope, task) -> AgentSpec`; V1 tools exclude `Agent`; prompt loads skill + role/scope |
| `gates.check_halt` | Query halt contract | `(gate, risk, action=None, autonomy=None) -> Decision`; subprocess `halt_gate.py`; exit 0=AUTO,10=HALT,else error |
| `gates.check_cross_repo_drift` | Query cross-repo drift | subprocess `cross_repo_check.py`; branch on exit code |
| `state.save/load` | Checkpoint persistence | `state.json`: stage, completed items, per-agent product metrics |
| `orchestrator.run` | Four-stage loop | sequential stages; per-stage gate; shallow fan-out; checkpoint per boundary |
| `tui.select` | Interactive menu | `(title, options, input_fn=input) -> Optional[int]`; curses arrow-key menu, numbered fallback when non-TTY/`AI_SDLC_NO_CURSES` |
| `tui._parse_choice` | Parse a numbered answer | `(raw, n) -> Optional[int]`; 1-based → 0-based; `q`/empty/out-of-range → None (pure, unit-tested) |
| `cli.cmd_menu` | Menu loop | dispatches the chosen action to existing `cmd_run`/`cmd_migrate`/`cmd_status`; no governance logic of its own |
| `orchestrator.run(on_event=…)` | Event emission | optional `on_event(dict)` sink; emits `stage`/`gate`/`agent`/`checkpoint`/`halt`/`done`; never affects control flow |
| `dashboard.DashboardModel` | Panel data | `add(event)` / `from_saved(project)`; `status_panel`/`exec_log_panel`/`verify_panel`/`agent_panel(view)`; `status_panel`/`verify_panel` are memoized behind `_status_cache`/`_verify_cache` and only recompute on `refresh()` — `exec_log_panel`/`agent_panel` stay uncached (live in-memory events) (CHG-20260703-05) |
| `dashboard.DashboardModel.refresh` | Cache invalidation | `() -> None`; clears `_status_cache`/`_verify_cache` to `None`; called on app start, `ResidentState.open_project`, and after `ResidentApp._start_run`'s `orchestrator.run(...)` returns — never per keystroke (CHG-20260703-05) |
| `dashboard.render_snapshot` | Text render | `(model, agent_view, width) -> str`; CJK display-width aware borders; used off-TTY/tests; `view()` adds a curses viewer (t = toggle, q = quit) |
| `tui.cycle_index` | Pure option-cycle core | `(idx, n, key, key_up, key_down) -> int`; wraps; unrecognized key is a no-op; no curses import (CHG-20260703-03) |
| `tui._curses_select_on` | Embeddable arrow-key selector | `(stdscr, title, options) -> Optional[int]`; draws on a caller-owned `stdscr` (no nested `curses.wrapper`); `_curses_select`/`select()` now delegate to it (CHG-20260703-03) |
| `dashboard.parse_command` | Resident input-box parser | `(raw) -> Command{kind, arg, error}`; `open\|run\|status\|check\|menu\|help\|quit\|task\|unknown\|noop`; pure, no I/O (CHG-20260703-03) |
| `dashboard.render_layout` | 2-col bounded-height frame | `(model, width, height, agent_view, input_line, current_project) -> list[str]`; Status\|Verification top row always fully present; Execution log\|Agent log bottom row, each tail-truncated to fit `height`; pure (CHG-20260703-03) |
| `dashboard.approve_decision` | Halt-gate answer → bool | `(selection) -> Optional[bool]`; accepts an `APPROVE_OPTIONS` index, a bool, or a y/n-ish string; unresolved/cancelled → `None` (caller treats as reject, never implicit approve) (CHG-20260703-03) |
| `dashboard.ResidentApp` / `ResidentState` | Resident app glue | `ResidentApp.dispatch(raw, asker=...) -> bool` (False = quit); `_start_run` calls the unchanged `orchestrator.run(approver=..., on_event=model.add)`; `ResidentState.current_project`/`.model` track the open project (CHG-20260703-03) |
| `dashboard.run_resident` | Resident entry point | `(project=None, config=None) -> int`; TTY-only (mirrors `_want_curses`); drives the curses loop until `/quit` (CHG-20260703-03) |

## Interface / API contracts
- **Lock file** `<project>/.sdlc-lock.json`: `{contract_major, contract_minor, contract_version, first_run, runner}`. Gate compares `(major, minor)`; `contract_version` is record-only.
- **Halt decision**: `Decision{result: "AUTO"|"HALT", gate, risk, reason}`. HALT → `orchestrator.await_human_approval(...)`.
- **AgentSpec**: `{role, tools: list[str], can_spawn: bool, writable, scope, prompt}`. Invariant: `"Agent" not in tools` when `role == "V1"`.
- **Error behavior**: unknown gate/risk or exit codes other than 0/10 from the script → raise (conservative; never silently continue). Missing skill files → raise with a clear message.

## Design decisions & trade-offs
| Decision | Options | Rationale |
|----------|---------|-----------|
| Detect version from file vs git tag | file (SKILL.md) **vs** git tag | User chose file detection: a missing/wrong tag surfaces as a contract-version mismatch instead of silent drift; works without git plumbing |
| Offline local store, vendored into runner | submodule (online) **vs** local store | User override (CHG-05): run fully offline with v1.0.0 + v1.1.0 (+ v1.12.1, CHG-20260703-01, now the config default) on hand; submodule kept as optional fallback. **Deliberately relaxes §1.2/§7 (reference-not-copy)** — recorded in CHG-05 and the Guideline |
| Version selected by project lock | config-fixed **vs** lock-driven | Each project uses the store version matching its lock; migrate switches it automatically |
| Platform-agnostic execution backend | one vendor **vs** stub/command/api | Runtime concern (§1.7), config-driven; run via API or a subscription CLI without locking to a platform (CHG-06) |
| API client | requests/httpx **vs** stdlib urllib | Keeps zero-dependency; keys from env, never config |
| Reference skill via submodule | submodule **vs** copy/vendor | One-way dependency + no drift; copying is explicitly forbidden (§7) |
| Call scripts vs re-implement | subprocess **vs** re-code matrix | Skill is the single source of truth; re-coding causes divergence (§1.3, §7) |
| Lock major.minor, patch-permissive | lock full version **vs** major.minor | Patches (typo/bug/wording) shouldn't force migrate; interface changes (minor) should re-read (§5) |
| Migrate is validating, not forced | force-upgrade **vs** validate-then-upgrade | Upgrade only if everything re-parses; otherwise stop and list incompatibilities (§5) |
| Conservative fan-out (≤3/≤4) | use platform max (5) **vs** cap lower | Deliberately save tokens; runtime caps live in config, probed at startup (§1.5, §1.7) |
| V1 tools exclude `Agent` | discipline **vs** tool-layer lock | Mechanically prevents "fix-while-verifying" and re-spawning (§1.6) |
| Stdlib-only (PyYAML optional) | hard YAML dep **vs** tiny built-in reader | Keeps the runner a thin, low-dependency driver |
| Interactive menu via stdlib `curses` | third-party TUI **vs** stdlib curses + numbered fallback | Zero new dependency; degrades gracefully off-TTY (CHG-20260617-02) |
| Dashboard as terminal curses | HTML report **vs** curses TUI | Screenshot was a layout preview, not an HTML target; curses keeps it stdlib-only (CHG-20260617-03) |
| Dashboard coupling via `on_event` | dashboard reads orchestrator **vs** orchestrator pushes events | Optional callback keeps orchestrator decoupled & backward-compatible; dashboard is read-only (CHG-20260617-03) |
| Bare `runner` entry point | keep opening the menu **vs** default to the resident dashboard | User req 1: on a real TTY, bare `runner` (or `runner <project>`) opens the resident dashboard; off-TTY (pipes/CI) keeps the menu unchanged; every subcommand is unaffected either way (CHG-20260703-03) |
| Project targeting in the resident app | positional arg per command **vs** a "current project" set by `/open` | User-confirmed: `/open <path>` sets one current project that tasks/`/run`/approvals target, plus `runner <project>` as a pre-open convenience; simpler than re-specifying a path on every command (CHG-20260703-03) |
| v1 Q/A scope | task input + halt approval **vs** free-form agent Q&A | User-confirmed v1 scope is deliberately narrow (task/requirement input + HALT approve/reject only); a backend that surfaces agent questions is a later change (CHG-20260703-03) |
| Run integration threading | single-thread (blocking) **vs** background thread | Stdlib-only, stub/fast runs in v1: `on_event` redraws inline, `approver` blocks synchronously; a slow real backend blocking the UI is an accepted, documented v1 limitation (CHG-20260703-03) |
| Log growth in the resident view | unbounded scroll **vs** bounded tail | 2-col Execution log / Agent log each truncate to the last N lines (N scales with terminal height) so Status + Verification never get pushed off-screen (CHG-20260703-03) |
| Reuse the arrow-key selector for halt answers | new selector **vs** embed `tui`'s | Extracted `tui._curses_select_on` to draw on the resident app's own `stdscr`; the resident loop never calls `tui.select()` (that would open a second, nested `curses.wrapper`) (CHG-20260703-03) |
| Where to cache the resident panels' I/O | cache inside `DashboardModel` **vs** in the resident render loop | The snapshot path (`render_snapshot`/`from_saved`) calls panels once already; caching in the model with an explicit `refresh()` invalidator keeps that path's cold-cache-computes-once behavior identical while the resident loop reuses the warm cache across keystrokes (CHG-20260703-05) |
| When to refresh the cache | per keystroke **vs** event-driven (open/after-run) **vs** a timer | Event-driven: `refresh()` on app start, `/open` (`ResidentState.open_project`), and after each run (`ResidentApp._start_run`); git dirty-state/ACC files only change on real actions, not on typing. A live timer refresh is a possible follow-up, not needed to remove the typing lag (CHG-20260703-05) |

## Patterns adopted
- **Adapter / facade over the skill**: `gates` and `agents` adapt the skill's scripts and docs into typed Python results; the runner never owns the policy.
- **Sequential pipeline with gates**: each stage is a checkpoint + halt-point, giving crash-resume and human gating at boundaries for free.
- **Least privilege via allowlist**: roles get only the tools they need; V1 is the strictest.
