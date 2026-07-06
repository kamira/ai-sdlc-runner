# ai-sdlc-runner — Architecture & Feature Overview

A handover-oriented map of what the runner is, how it's put together, and where the boundaries are.
For the canonical per-stage governance, see `docs/ai-guideline.md`, `docs/structure/*.md`, and the
`docs/changes/` + `docs/acceptance/` records.

## 1. What it is

`ai-sdlc-runner` is an **external Python orchestrator** that drives the `ai-sdlc` skill's semi-autonomous
development loop (requirement analysis → structure design → implement → acceptance), stopping at gated
halt-points for human approval. The skill stays a pure markdown + zero-dependency-script package; the
runner is the driver. **Dependency is one-way: the runner depends on the skill; the skill never depends
on the runner.** The runner duplicates no governance *logic* — it reads the skill's docs and calls the
skill's scripts.

## 2. Module map (`src/ai_sdlc_runner/`)

| Module | Responsibility |
|--------|----------------|
| `cli.py` | Entry point. Subcommands `run` / `dashboard` / `check` / `migrate` / `status` / `menu`; bare `runner` opens the menu. Loads config, resolves the skill path, builds the executor, dispatches. |
| `orchestrator.py` | The four-stage sequential loop with shallow fan-out in the implement stage; one halt gate + one checkpoint per stage boundary; emits events to an optional dashboard sink. |
| `contract.py` | Version detection from `SKILL.md`; per-project `major.minor` lock; validating `migrate`; `detect_update` / `available_version_tags`. |
| `gates.py` | Halt decisions by `subprocess`-calling the skill's `halt_gate.py` (exit `0`=AUTO, `10`=HALT); cross-repo drift via `cross_repo_check.py`. No risk matrix of its own. |
| `agents.py` | Parses the skill's "Role startup spec" table; spawns role-scoped agents. Invariant: **V1 never receives the `Agent` tool**. |
| `state.py` | Checkpoint/resume (`state.json`); stage order. |
| `skillstore.py` | Offline multi-version skill store resolver (`skills/v*`), selecting the version that matches a project's lock. |
| `executors.py` | Pluggable, platform-agnostic agent backends: `stub` / `command` (subscription/CLI) / `api` (HTTP). Runs each agent in its target repo (`workdir`). |
| `workspace.py` | Multi-project workspace: an authority (main) + consumer repos, persisted at the authority. |
| `structure_scan.py` | Structure-analysis pass: scan each repo, scaffold the four structures, wire the authority contract + consumer pointers. |
| `tui.py` | Interactive arrow-key menu (stdlib curses) with a numbered fallback; exposes an embeddable arrow-key selector (`_curses_select_on`) and a pure option-cycle core (`cycle_index`) for reuse inside an existing curses screen (e.g. the resident dashboard). |
| `dashboard.py` | Multi-panel execution view (Status / Execution log / Verification / Agent log); curses live + text snapshot. Also: the resident interactive console (`ResidentApp`/`run_resident`) — a persistent, always-on control console with a 2-col bounded-height layout, a command parser, and an interactive halt-gate approver, built from pure/headless-testable functions (`parse_command`, `render_layout`, `approve_decision`). |

Dependency direction: `cli → {orchestrator, tui, dashboard, skillstore, executors}`;
`orchestrator → {contract, gates, agents, state}` + an injected `executor`. Everything is standard
library only (PyYAML optional).

## 3. The four-stage loop (`orchestrator.run`)

```
0. resolve contract lock (mismatch → migrate_required); probe runtime caps; load state (--resume)
1. requirement analysis (A1)      → gate requirement_confirmed   → checkpoint
2. structure design (A1)          → gate structure_confirmed     → checkpoint
3. implement (I1 + shallow I1.x)  → gate before_implement        → checkpoint   (depth ≤ 3, concurrency ≤ 4)
4. acceptance (independent V1)    → gate acceptance_failed (only on failure) → checkpoint
delivery                          → gate before_merge_or_release  (red lines ALWAYS halt)
```

Each stage boundary is a checkpoint **and** a halt-point, which is what gives crash-resume and
human-at-the-boundary gating for free. The role chain is `A1` (analysis) → `I1` (lead implementer, may
spawn `I1.x`) → `V1` (independent verifier; read-only; no `Agent` tool).

## 3a. Multi-project workspace & cross-repo (CHG-08)

For a system spanning several repos the flow is: **register** a workspace (`runner workspace`) — one or
more project paths, with the **main project designated as the authority** — then **analyze**
(`runner analyze`) to scan each repo and scaffold the four structures, and (for multi-project) set up
the authority's shared contract (`docs/contracts/VERSION`) + each consumer's `docs/authority.md`
pointer. `runner run <authority>` then verifies cross-repo consistency with the skill's
`cross_repo_check.py` (**a lagging consumer → HALT**) before driving the four-stage loop, and each
agent runs inside its target repo (`workdir`). This mirrors the skill's cross-repo model (authority
source + local view + pointer + XCHG). Single-project use needs none of this and is the default.

## 4. Version lock & migrate

The contract is locked **per governed project** at `major.minor` (`<project>/.sdlc-lock.json`). PATCH
differences pass freely; a `minor`/`major` bump forces an explicit, **validating** `migrate`: re-read
every doc under the new contract and raise the lock only if all re-parse; otherwise stop and list the
incompatibilities (never a forced bump). The lock travels with the governed project's git — not the
runner's, and not the project's own product version.

## 5. Skill sourcing (offline-first)

Resolution order (all offline): explicit `--skill-path` → the local store `skills/<version>` matching
the project lock major.minor (config-expected on first run, else latest) → the optional `ai-skills`
submodule fallback (not pulled by default). The runner **never fetches the skill online**. `runner
check` compares the newest available version to a project's lock and classifies patch (auto) vs
minor/major (→ migrate). Four versions ship vendored: `skills/v1.0.0`, `skills/v1.1.0`,
`skills/v1.12.1`, `skills/v1.16.0` (the current baseline / config default, CHG-20260703-06).

> **Recorded override (CHG-05):** the build guide's §1.2/§7 ("reference, never copy the skill into the
> runner") is **deliberately relaxed** with user approval to enable fully-offline operation. Bounded by:
> verbatim offline extraction from git tags (no fork), submodule retained as fallback, and **no
> governance logic duplicated** — the runner still reads the store's own scripts/refs.

## 6. Execution backends (any AI platform)

The agent-execution backend is a **runtime concern, not the contract** (build-guide §1.7), so the runner
is not tied to any AI platform. Selected by config (`executor` block) or `--backend`:

| Backend | Use | Notes |
|---------|-----|-------|
| `stub` | offline / dry-run (default) | no-op; keeps the runner inert |
| `command` | subscription / local CLI agent | runs any command; prompt via stdin or arg |
| `api` | HTTP API | `anthropic` / `openai` / `generic` adapters; key from an **env var**, never config |

The backend runs agent work only — **halt gates and red-line stops apply identically** whichever backend
is chosen.

**Pure-ai-sdlc isolation (CHG-20260703-02).** The `command` backend accepts a generic passthrough:
`executor.command.extra_args` (list, appended to `argv`) and `executor.command.extra_env` (dict, merged
into the subprocess environment on top of the inherited one). Both default to empty — no config change
means byte-for-byte identical behavior. This is deliberately generic rather than hardcoding any
Claude-Code-specific skill-disabling flags into the runner (which would break the platform-agnostic
principle, §1.7) — the restricting flags/env live in config, not code. `api`/`stub` backends are
unaffected. The shipped recipe for constraining a `claude -p` agent to load only the ai-sdlc skill:

```yaml
executor:
  command:
    argv: ["claude", "-p"]
    extra_args: ["--settings", "config/pure-ai-sdlc.settings.json"]
```

`config/pure-ai-sdlc.settings.json` sets `disableBundledSkills: true` and disables the
`everything-claude-code` / `code-review` / `feature-dev` / `claude-code-setup` plugins.

## 7. Interfaces

- **CLI**: `runner run|dashboard|check|migrate|status|menu|workspace|analyze`; `run` flags
  `--contract-version`, `--skill-path`, `--risk`, `--resume`, `--dashboard`, `--agent-view`, `--backend`.
- **Menu** (`runner menu`, or bare `runner` off-TTY): arrow-key list (curses) or numbered fallback.
- **Resident interactive dashboard** (bare `runner` on a TTY, or `runner <project>` to pre-open —
  CHG-20260703-03): the **default entry point** on a real terminal. A persistent control console that
  never exits on its own (`/quit` only); empty start (no project, empty panels). Layout: Status |
  Verification on the top row (always fully present), Execution log | Agent log on the bottom row as
  **two bounded-height columns** (each truncated to its last N lines, N scaling with terminal height,
  so the top row is never pushed off), and a bottom **input box**. The input box accepts:
  - `/open <path>` — sets the *current project* (shown in Status); tasks/`/run`/approvals target it.
  - plain text (no leading `/`) — starts a run on the current project, recording the text as the
    requirement in the exec log; `/run [text]` is the explicit form.
  - `/status`, `/check`, `/menu` (also **F2**), `/help`, `/quit`.
  - the input box accepts **any language** (UTF-8, incl. CJK): the loop reads whole characters via
    `stdscr.get_wch()` (locale set once via `locale.setlocale(LC_ALL, "")`) routed through the pure
    `apply_key` helper, instead of the old one-byte-at-a-time `getch()` path (CHG-20260703-04).
  - answers to a HALT-gate approval are **arrow-key selectable** (`[Approve / Reject]`, ↑/↓ + Enter,
    or y/n), via the same embeddable selector `tui` exposes for use inside an existing curses screen
    (`tui._curses_select_on`) — the resident app does not call `tui.select()` itself, since that opens
    its own nested `curses.wrapper` session.
  - v1 Q/A scope is intentionally limited to (a) task/requirement input and (b) HALT-gate
    approve/reject; free-form agent Q&A is a later change.
  - runs are **single-threaded**: `orchestrator.run`'s `on_event` updates the model and the loop
    redraws; its `approver` blocks synchronously for the human answer. A slow real backend would block
    the console too — an accepted, documented v1 limitation (threading is a follow-up).
  - **no governance logic lives here**: halt decisions still come from `gates`/`halt_gate.py`
    unchanged; red-line gates always require an explicit human Approve (never auto-approved); the
    resident app only supplies the human `approver` and an `on_event` sink to the same `orchestrator.run`
    every other entry point uses.
  - off-TTY (pipes/CI/`AI_SDLC_NO_CURSES=1`), bare `runner` is **unchanged**: the classic menu / its
    numbered fallback. No subcommand's behavior changes.
  - the resident redraw is **cache-backed** (CHG-20260703-05): `DashboardModel.status_panel()`/
    `verify_panel()` memoize their `git`/disk work and only recompute via `refresh()`, called on app
    start, `/open` (`ResidentState.open_project`), and after a run (`ResidentApp._start_run`) — so
    per-keystroke redraws do zero subprocess/disk I/O; `exec_log_panel`/`agent_panel` stay uncached
    (live in-memory events). The read-only snapshot path is unaffected (cold cache computes once).
- **Dashboard, read-only** (`run --dashboard` live one-shot, `runner dashboard <project>` snapshot):
  unchanged — four panels in a vertical layout; agent log consolidated by default, togglable to tabbed
  (`--agent-view tabbed` / `t` in the viewer); exits on `q`. Distinct from, and untouched by, the
  resident app above.

## 8. Inviolable guardrails (and the one recorded exception)

1. One-way dependency: skill never depends on the runner.
2. No duplicated governance logic — halt matrix, role table, CHG/ACC fields are read/called from the skill.
3. Submodule pinned to a tag, never `main` (now an optional fallback behind the offline store).
4. Red-line actions (deploy/release, migration/irreversible schema, delete/drop, money, secrets/permissions,
   publish) **never auto-run** — always surface for a human.
5. V1 verifier's tool layer is locked: no `Agent` tool, read-only on code under review.
6. Runtime variability (fan-out caps, execution backend) lives in `config/runner.yaml`, not the contract.

The single recorded exception is the §1.2/§7 reference-not-copy relaxation (offline store, CHG-05) —
explicit, bounded, and logged in the Guideline.

## 9. Testing

Standard-library `pytest`; **130+ tests** covering the version lock + migrate, role-table parsing and
the V1-excludes-Agent invariant, the menu/dashboard rendering, skill-store resolution, update detection,
the executor backends (request building, response parsing, command execution against a local agent),
and the resident dashboard's command parser / 2-col bounded-height layout / approver decision mapping
(the curses loop itself is not unit-tested — only its pure/headless-testable core is). Run:

```bash
pip install -e .[test]
export AI_SDLC_SKILL_PATH=<a local skill root>   # optional: enables the cache-gated tests
python3 -m pytest -q
```

## 10. Change history (dogfooded — this repo is governed by ai-sdlc)

| Change | Summary | Acceptance |
|--------|---------|-----------|
| CHG-20260617-01 | Initial runner package (contract/gates/agents/state/orchestrator/cli) | ACC-…-01 |
| CHG-20260617-02 | Interactive arrow-key menu (`tui`) | ACC-…-02 |
| CHG-20260617-03 | Multi-panel dashboard + orchestrator events | ACC-…-03 |
| CHG-20260617-04 | Skill update detection (`check`) | ACC-…-04 |
| CHG-20260617-05 | Offline local skill store (override §1.2/§7) | ACC-…-05 |
| CHG-20260617-06 | Platform-agnostic executor backends | ACC-…-06 |
| CHG-20260617-07 | This architecture overview | ACC-…-07 |
| CHG-20260703-01 | Vendor ai-sdlc v1.12.1 into the store; bump `contract_version` default to 1.12.1 | ACC-20260703-01 |
| CHG-20260703-02 | Executor `extra_args`/`extra_env` passthrough (pure-ai-sdlc isolation recipe) | ACC-20260703-02 |
| CHG-20260703-03 | Resident interactive dashboard (default entry, command layer, interactive halt-gate approver) | ACC-20260703-03 |
| CHG-20260703-05 | Cache the resident dashboard's I/O-bound panels; refresh on open/after-run, not per keystroke | ACC-20260703-05 |
| CHG-20260703-06 | Vendor ai-sdlc v1.16.0 into the store; bump `contract_version` default to 1.16.0 | ACC-20260703-06 |

## 11. Handover & extension notes

- **Add a CLI command**: add a `cmd_*` + subparser in `cli.py`; route menu actions through the same
  handlers so governance is preserved.
- **Add an API provider**: extend `executors.build_request` / `parse_response` with a new provider
  branch; no other module changes.
- **Add a store version**: drop a `skills/vX.Y.Z/` skill root in; `runner check` and lock-based
  resolution pick it up automatically.
- **Change runtime caps / backend**: edit `config/runner.yaml` — never the contract.
- **Any change to this repo goes through ai-sdlc governance**: write a `CHG-*.md`, implement, then close
  acceptance in the same round with an `ACC-*.md` (independent V1 for medium/high risk).

---

## 繁體中文摘要

`ai-sdlc-runner` 是驅動 `ai-sdlc` skill「需求分析 → 結構設計 → 實作 → 驗收」四階段半自主迴圈的**外部
Python 編排器**;skill 維持純淨,runner 是外部驅動器,**單向依賴、不複製治理邏輯**(讀 skill 文件、呼叫
skill 腳本)。

重點:四階段循序、每階段過停點閘並寫 checkpoint;角色鏈 A1→I1(→I1.x)→V1(V1 唯讀、無 `Agent`);版本鎖
per-project 鎖 `major.minor`(patch 放行、跳號走**驗證式 migrate**);skill **離線優先**(本地 store
`skills/v1.0.0`、`v1.1.0`、`v1.12.1`、`v1.16.0`(v1.16.0 為目前基準/config 預設),依鎖選版;submodule 僅選用 fallback;絕不連網),`runner check` 偵測更新;執行
後端**不綁平台**(`stub` / `command` 訂閱 CLI / `api` HTTP,金鑰取自環境變數),且後端不影響停點與紅線。
在真正的 TTY 上,`runner`/`runner <project>` 預設直接進入**常駐互動儀表板**(CHG-20260703-03):空狀態
啟動、`/quit` 才離開、下排執行/agent 日誌兩欄且高度有界(上排狀態/驗證永遠可見)、底部輸入框支援
`/open`、純文字任務、`/run`、`/status` 等指令,HALT 停點以方向鍵 `[Approve/Reject]` 呈現——紅線一樣
永遠需要人類明確核准,治理邏輯完全未動;非 TTY 時舊行為(選單)不變,一次性 `--dashboard`/`dashboard`
唯讀快照路徑也維持原樣。常駐重繪為**快取支撐**(CHG-20260703-05):狀態/驗證面板只在啟動、`/open`、
run 結束後才重新計算,每次按鍵重繪皆零 `git`/磁碟 I/O。

唯一刻意放寬的護欄是 §1.2/§7「不複製 skill 進 runner」(為離線 store,CHG-05),已在 Guideline 記錄且有界。
所有改動皆走 ai-sdlc 治理,留有 `CHG-*` / `ACC-*`;測試 72 筆全綠。
