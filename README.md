# ai-sdlc-runner

External Python orchestrator that drives the [`ai-sdlc`](https://github.com/kamira/ai-skills) skill's
semi-autonomous development loop. **The skill stays pure (markdown + zero-dependency gate scripts);
the runner is an external driver that references — never copies — the skill.** Dependency is one-way:
the runner depends on the skill; the skill never depends on the runner.

## Install

```bash
git clone https://github.com/kamira/ai-sdlc-runner.git
cd ai-sdlc-runner
pip install -e .                   # optional: .[yaml] for PyYAML, .[test] for pytest
```

**Offline by default.** The skill is vendored into a local store at `skills/` (`skills/v1.0.0`,
`skills/v1.1.0`), and that is the primary source — the runner never fetches the skill online. It
auto-selects the store version matching each project's lock (major.minor); after a `migrate` raises
the lock, the next run uses the new version automatically. `runner check` lists the store versions and
flags when a newer one is available.

> The `ai-skills` git submodule (`.gitmodules`) is kept **only as an optional fallback** and is *not*
> pulled by default. To use it instead of the store, run `git submodule update --init` and point
> `skill_path`/`--skill-path` at it. The runner detects the actual contract version by reading the
> skill's `SKILL.md` frontmatter either way.

## Usage

```bash
runner                                    # no subcommand → interactive menu (arrow-key list)
runner menu                               # the same interactive menu, explicitly
runner run <project>                      # drive the four-stage loop for a governed project
runner run <project> --dashboard          # ...with the live multi-panel dashboard
runner dashboard <project>                # open the dashboard over a project's saved state
runner check [project]                    # detect whether the local skill has an update
runner migrate <project> --to <version>   # validating contract upgrade (re-read all docs first)
runner status <project>                   # show the per-project lock + run state
```

Options for `run`: `--contract-version` (defaults to config), `--skill-path` (override, e.g. a local
skill cache for offline verification), `--risk {low,medium,high}`, `--resume`.

The **interactive menu** uses an arrow-key selectable list (stdlib `curses`; ↑/↓ + Enter, `q` to
cancel) and falls back to a numbered prompt when not on a TTY (pipes/CI) or when `curses` is
unavailable — no third-party dependency. It only collects a choice and dispatches to the commands
above, so every halt gate and red-line stop still applies. Set `AI_SDLC_NO_CURSES=1` to force the
numbered fallback.

The **dashboard** (`run --dashboard` for live, `runner dashboard <project>` for a saved-state
snapshot) shows four panels: **狀態/Status** (git branch + dirty, stage progress, current stage +
contract lock), **執行日誌/Execution log** (stage transitions + gate AUTO/HALT), **檢驗結果/Verification**
(acceptance reports + latest V1 result), and **agent 行為日誌/Agent log**. The agent log is consolidated
in one panel by default and can be switched to tabbed-per-agent (`--agent-view tabbed`, or `t` in the
curses viewer, or the menu). It is read-only — a run launched from the dashboard still halts at the
red-line gate.

**Execution backend (any AI platform).** The agent-execution backend is a runtime concern, not the
contract — so the runner is **not tied to any AI platform**. Choose per run with `--backend` or in
`config/runner.yaml`'s `executor` block:

- `stub` (default) — no-op, offline/dry-run.
- `command` — run any local CLI / **subscription** agent (e.g. a logged-in tool); the prompt is passed
  via stdin or as an argument: `executor.command.argv: ["claude", "-p"]`, `prompt_via: stdin|arg`.
- `api` — call an **HTTP API**: `executor.api.{provider: anthropic|openai|generic, base_url, model,
  api_key_env}`. The API key is read from the named **environment variable**, never stored in config.

```bash
runner run <project> --backend command     # drive agents via a subscription/CLI agent
runner run <project> --backend api         # drive agents via an HTTP API (key from env)
```

The backend only runs agent work — **halt gates and red-line stops apply identically** whichever
backend you pick. Uses only the standard library (`urllib`/`subprocess`); no extra dependency.

**Skill update detection.** `runner check [project]` reads the version at the local skill location
(`skill_path`, overridable with `--skill-path`) and compares it to the project's lock (or the
config-expected version): a **patch** difference passes freely, a **minor/major** difference reports
that you should run `migrate` (exit 20), and it also surfaces any newer version tag found in the
skill's git repo (e.g. `ai-sdlc-v1.1.0`). The same line appears in `status` and the dashboard Status
panel. Detection is read-only — it never auto-migrates; the validating `migrate` stays explicit.

## How it works

- **Contract lock is per project, `major.minor`.** PATCH differences pass freely; a `minor`/`major`
  bump forces an explicit, *validating* `migrate` (re-read every doc; raise the lock only if all
  re-parse). The lock lives in the **governed project** as `.sdlc-lock.json` and travels with that
  project's git — not to be confused with the project's own product version.
- **No duplicated governance logic.** Halt-point decisions are obtained by `subprocess`-calling the
  skill's `scripts/halt_gate.py` (exit `0`=AUTO, `10`=HALT); role definitions are parsed from the
  skill's `references/agent-hierarchy.md`. The runner holds no risk matrix and no hardcoded role
  table of its own.
- **Stages run sequentially with shallow fan-out.** Four stages (requirement analysis → structure
  design → implement → acceptance), each passing a halt gate, with a checkpoint at every boundary
  (`--resume` continues from the last one). Fan-out is capped at depth ≤ 3 / concurrency ≤ 4 —
  deliberately conservative to save tokens (the platform supports more). These runtime limits live
  in `config/runner.yaml` and are probed at startup; the contract targets the skill's stable output,
  not Claude Code's current runtime behavior.
- **V1 verifier is locked down.** The independent acceptance agent is spawned with a tools allowlist
  that **excludes `Agent`** (it cannot spawn or fix while verifying) and is read-only on the code
  under review (but may run tests/CLI/GUI to verify).
- **Red lines always halt.** Deploy/release, data migration/irreversible schema, delete/drop, money,
  secrets/permissions, and publishing are never auto-run — they always surface for human approval.

> **The skill without the runner is still a pure skill.** Installing the runner adds an external
> driver; it does not modify or depend back on the skill.

## Governance

This repo is itself governed by ai-sdlc (dogfooding). See `docs/ai-guideline.md`,
`docs/structure/*.md`, `docs/changes/CHG-*.md`, and `docs/acceptance/ACC-*.md`.

---

# ai-sdlc-runner（繁體中文）

驅動 [`ai-sdlc`](https://github.com/kamira/ai-skills) skill 半自主開發迴圈的**外部 Python 編排器**。
**skill 維持純淨(markdown + 零依賴 gate 腳本);runner 是外部驅動器,引用 skill 而非複製。**
依賴為單向:runner 依賴 skill,skill 永不依賴 runner。

## 安裝

```bash
git clone https://github.com/kamira/ai-sdlc-runner.git
cd ai-sdlc-runner
pip install -e .                   # 選用:.[yaml] 裝 PyYAML、.[test] 裝 pytest
```

**預設離線。** skill 已內置成本地 store(`skills/v1.0.0`、`skills/v1.1.0`),這是主要來源——runner
**絕不從線上抓** skill。它會依每個專案的鎖(major.minor)自動選對應版本;`migrate` 升鎖後,下一次 run
自動改用新版本。`runner check` 會列出 store 內版本並提示有無更新。

> `ai-skills` git submodule(`.gitmodules`)**僅保留為選用 fallback**,預設**不**拉取。若要改用它,
> 執行 `git submodule update --init` 並把 `skill_path`/`--skill-path` 指過去即可。兩種來源 runner 都以
> 讀 `SKILL.md` frontmatter 偵測實際契約版本。

## 用法

```bash
runner                                    # 不帶子指令 → 互動選單(方向鍵清單)
runner menu                               # 顯式進入同一個互動選單
runner run <project>                      # 對受治理專案驅動四階段迴圈
runner run <project> --dashboard          # ...同時開啟即時多面板儀表板
runner dashboard <project>                # 對專案已存的狀態開啟儀表板
runner check [project]                    # 偵測本地 skill 位置是否有更新
runner migrate <project> --to <version>   # 驗證式契約升版(先全部重讀 docs)
runner status <project>                   # 顯示該專案的版本鎖與執行狀態
```

`run` 的選項:`--contract-version`(預設取 config)、`--skill-path`(覆寫,如指向本地 skill 快取做離線
驗證)、`--risk {low,medium,high}`、`--resume`。

**互動選單**採方向鍵可選清單(stdlib `curses`;↑/↓ + Enter,`q` 取消);在非 TTY(pipe/CI)或無
`curses` 時自動退化為數字選單——零第三方依賴。選單只負責收集選擇、再分派給上述指令,因此所有停點與
紅線停下依然生效。設 `AI_SDLC_NO_CURSES=1` 可強制使用數字選單。

**儀表板**(`run --dashboard` 即時、`runner dashboard <project>` 讀已存狀態快照)有四個面板:
**狀態/Status**(git 分支 + dirty、階段進度、目前階段 + 契約鎖)、**執行日誌/Execution log**(階段轉換 +
停點 AUTO/HALT)、**檢驗結果/Verification**(驗收報告 + 最新 V1 結果)、**agent 行為日誌/Agent log**。
agent 日誌預設統整在同一面板,可切換成分頁分 agent(`--agent-view tabbed`,或 curses 視圖中按 `t`,或從
選單)。儀表板為唯讀——從儀表板啟動的 run 一樣會在紅線停點停下。

**執行後端(不限任何 AI 平台)。** agent 執行後端屬於 runtime、不屬契約——所以 runner **不綁任何 AI 平台**。
可用 `--backend` 或 `config/runner.yaml` 的 `executor` 區塊選擇:

- `stub`(預設)——無動作,離線/dry-run。
- `command`——走任何本地 CLI /**訂閱**型 agent(例如已登入的工具);prompt 以 stdin 或參數傳入:
  `executor.command.argv: ["claude", "-p"]`、`prompt_via: stdin|arg`。
- `api`——呼叫 **HTTP API**:`executor.api.{provider: anthropic|openai|generic, base_url, model,
  api_key_env}`。API 金鑰從指定的**環境變數**讀取,**絕不**寫進 config。

```bash
runner run <專案> --backend command     # 用訂閱/CLI agent 驅動
runner run <專案> --backend api         # 用 HTTP API 驅動(金鑰取自環境變數)
```

後端只負責跑 agent——**停點與紅線停下不論用哪個後端都一樣生效**。僅用標準庫(`urllib`/`subprocess`),無額外依賴。

**Skill 更新偵測。** `runner check [project]` 讀取本地 skill 位置(`skill_path`,可用 `--skill-path` 覆寫)
的版本,與該專案的鎖(或 config 預期版本)比對:**patch** 差異自由放行;**minor/major** 差異會提示你執行
`migrate`(exit 20);並會回報 skill git repo 內有無更新的版本 tag(如 `ai-sdlc-v1.1.0`)。同一行也會出現在
`status` 與儀表板的狀態面板。偵測為唯讀——絕不自動 migrate,驗證式 `migrate` 仍須顯式執行。

## 運作方式

- **版本鎖採 per-project 的 `major.minor`。** PATCH 差異自由放行;`minor`/`major` 跳號則強制走顯式的
  **驗證式 `migrate`**(全部重讀,能全數解析才升鎖)。鎖檔 `.sdlc-lock.json` 屬於**受治理專案**、隨其
  git 一起走,勿與該專案自身的產品版本混淆。
- **不重複治理邏輯。** 停點判斷一律 `subprocess` 呼叫 skill 的 `scripts/halt_gate.py`(退出碼
  `0`=AUTO、`10`=HALT);角色定義從 skill 的 `references/agent-hierarchy.md` 解析。runner 內**不寫死**
  風險矩陣,也不寫死一份角色表。
- **大項依序、淺扇出。** 四階段(需求分析 → 結構設計 → 實作 → 驗收)循序執行,每階段過停點閘,並在
  每個邊界寫 checkpoint(`--resume` 可從上次接續)。扇出深度 ≤ 3、併發 ≤ 4——刻意保守以省 token
  (平台其實支援更多)。這些 runtime 上限放在 `config/runner.yaml`、啟動時實測;契約對著 skill 的穩定
  輸出,不對著 Claude Code 當前的 runtime 行為。
- **V1 驗收者工具層鎖死。** 獨立驗收代理啟動時的工具 allowlist **不含 `Agent`**(無法再生子代理、也無法
  邊驗邊改),且對受驗的碼唯讀(但可執行測試/CLI/GUI 來驗證)。
- **紅線永遠停。** 部署/發佈、資料遷移/不可逆 schema、刪除/drop、金流、密鑰/權限、發布公開內容,一律
  不自動執行——必須浮出給人核准。

> **沒有 runner,skill 仍是那包純 skill。** 安裝 runner 只是加上外部驅動器,不會修改 skill、也不會反向
> 依賴它。

## 治理(dogfooding)

本 repo 自身即受 ai-sdlc 治理。詳見 `docs/ai-guideline.md`、`docs/structure/*.md`、
`docs/changes/CHG-*.md`、`docs/acceptance/ACC-*.md`。
