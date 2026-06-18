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
| `dashboard.DashboardModel` | Panel data | `add(event)` / `from_saved(project)`; `status_panel`/`exec_log_panel`/`verify_panel`/`agent_panel(view)` |
| `dashboard.render_snapshot` | Text render | `(model, agent_view, width) -> str`; CJK display-width aware borders; used off-TTY/tests; `view()` adds a curses viewer (t = toggle, q = quit) |

## Interface / API contracts
- **Lock file** `<project>/.sdlc-lock.json`: `{contract_major, contract_minor, contract_version, first_run, runner}`. Gate compares `(major, minor)`; `contract_version` is record-only.
- **Halt decision**: `Decision{result: "AUTO"|"HALT", gate, risk, reason}`. HALT → `orchestrator.await_human_approval(...)`.
- **AgentSpec**: `{role, tools: list[str], can_spawn: bool, writable, scope, prompt}`. Invariant: `"Agent" not in tools` when `role == "V1"`.
- **Error behavior**: unknown gate/risk or exit codes other than 0/10 from the script → raise (conservative; never silently continue). Missing skill files → raise with a clear message.

## Design decisions & trade-offs
| Decision | Options | Rationale |
|----------|---------|-----------|
| Detect version from file vs git tag | file (SKILL.md) **vs** git tag | User chose file detection: a missing/wrong tag surfaces as a contract-version mismatch instead of silent drift; works without git plumbing |
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

## Patterns adopted
- **Adapter / facade over the skill**: `gates` and `agents` adapt the skill's scripts and docs into typed Python results; the runner never owns the policy.
- **Sequential pipeline with gates**: each stage is a checkpoint + halt-point, giving crash-resume and human gating at boundaries for free.
- **Least privilege via allowlist**: roles get only the tools they need; V1 is the strictest.
