# ai-sdlc-runner

External Python orchestrator that drives the [`ai-sdlc`](https://github.com/kamira/ai-skills) skill's
semi-autonomous development loop. **The skill stays pure (markdown + zero-dependency gate scripts);
the runner is an external driver that references — never copies — the skill.** Dependency is one-way:
the runner depends on the skill; the skill never depends on the runner.

## Install

```bash
git clone https://github.com/kamira/ai-sdlc-runner.git
cd ai-sdlc-runner
git submodule update --init        # pulls ai-skills pinned at tag v1.0.0 (NOT main)
pip install -e .                   # optional: .[yaml] for PyYAML, .[test] for pytest
```

The `ai-skills` submodule is **pinned to tag `v1.0.0`** and must never track `main` (main drifts and
breaks the contract lock). The runner detects the *actual* contract version by reading the skill's
`SKILL.md` frontmatter, so a missing/incorrect tag surfaces as a contract-version mismatch rather
than silent drift.

## Usage

```bash
runner                                    # no subcommand → interactive menu (arrow-key list)
runner menu                               # the same interactive menu, explicitly
runner run <project>                      # drive the four-stage loop for a governed project
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
git submodule update --init        # 取得釘在 tag v1.0.0 的 ai-skills(非 main)
pip install -e .                   # 選用:.[yaml] 裝 PyYAML、.[test] 裝 pytest
```

`ai-skills` submodule **釘在 tag `v1.0.0`**,絕不可追 `main`(main 會漂、使契約鎖失效)。runner 透過
讀取 skill 的 `SKILL.md` frontmatter 來偵測**實際**契約版本,因此缺漏或錯誤的 tag 會以「契約版本不符」
浮現,而非悄悄漂移。

## 用法

```bash
runner                                    # 不帶子指令 → 互動選單(方向鍵清單)
runner menu                               # 顯式進入同一個互動選單
runner run <project>                      # 對受治理專案驅動四階段迴圈
runner migrate <project> --to <version>   # 驗證式契約升版(先全部重讀 docs)
runner status <project>                   # 顯示該專案的版本鎖與執行狀態
```

`run` 的選項:`--contract-version`(預設取 config)、`--skill-path`(覆寫,如指向本地 skill 快取做離線
驗證)、`--risk {low,medium,high}`、`--resume`。

**互動選單**採方向鍵可選清單(stdlib `curses`;↑/↓ + Enter,`q` 取消);在非 TTY(pipe/CI)或無
`curses` 時自動退化為數字選單——零第三方依賴。選單只負責收集選擇、再分派給上述指令,因此所有停點與
紅線停下依然生效。設 `AI_SDLC_NO_CURSES=1` 可強制使用數字選單。

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
