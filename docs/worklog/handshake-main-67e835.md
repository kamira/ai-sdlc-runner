# handshake — agent `main-67e835`

分支/角色/範圍:`claude/ai-sdlc-handshake-67e835`(worktree `.claude/worktrees/ai-sdlc-handshake-67e835`)
| 角色:A1 / orchestrator(單人進場,完整握手)| RW:全 repo
現在做:CHG-20260822-02 步驟 7/7 完成(改名清理,ACC 已收尾);等使用者確認 push
下一步:(順序 2→1→3,使用者已定)②完成 → ①push + PR + 回填 CI run → ③上游 CHG
最後更新:2026-08-22(UTC+0)

## 進場 ack(2026-08-21 15:31 UTC+0)

- **工具鏈**:進場時 `NOT_RUN`(exit 4);**已由 CHG-20260822-01 修復 → 現為 `PASS`(exit 0)**。原因:——`requirements-dev.txt` 不存在。**這不是「沒有相依」,是探測判不出來**。
  本 repo 刻意零執行期相依,開發相依宣告在 `pyproject.toml` 的 `[project.optional-dependencies]`
  (`yaml = PyYAML>=6.0`、`test = pytest>=7.0`),探測腳本只認 `requirements-dev.txt`,不認 pyproject。
  **人工補驗**:python3 3.11.9 可執行、pytest 9.1.1 已裝、PyYAML 6.0.3 已裝——宣告的開發相依實際全數到位。
  探測缺口本身是待修項(探測器的涵蓋範圍,不是本機環境問題)。
- **基準**:**降級**——目前分支沒有 upstream(新建 worktree 分支,尚未 push)。**不是落後**。
  `doc_integrity_check.py --repo . --check-baseline` exit 0,同時回報 doc-integrity 全數通過
  (結構同步 + CHG↔ACC + 欄位 + secrets)。
- **worktree**:乾淨(`git status --porcelain` 無輸出)——無未提交變更需對帳。
- **錨點後 commits**:ACC-20260817-11 錨在 `1268002`;`1268002..HEAD` 共 3 筆
  (`1268002`、`173becd`、`40923cd` merge PR #6),**全部引用 CHG-20260817-11 或為 PR merge**。無未治理 commit。
- **現行 Guideline**:v1.0(2026-06-17,Confirmed)。
- **skill 版本自檢**:ledger 最新記錄 `ai-sdlc v1.16.0`(vendored `skills/v1.16.0`);
  執行中 skill 為 **v1.64.0**。記錄比我舊 → 安全(新規則只往後適用),不需升級。
  **但另有一項待辦**:repo 的離線 store 最新只到 `skills/v1.16.0`,而已發布 skill 已到 v1.64.0——
  這是產品面的 store 落後(對照 KN-1 的 vendoring 慣例),不是握手阻擋項。
- **未收尾**:無。`docs/changes/` 20 筆 ↔ `docs/acceptance/` 20 筆,一對一無懸空。
- **結構漂移**:無(doc-integrity 結構同步檢查通過);`docs/structure/` 四份齊全
  (`logical.md`、`design.md`、`data.md`、`directory.md`)。
- **coordination**:`docs/coordination.md` 不存在——單人 repo,無他人 claim,無撞車風險。
- **已知須遵守(knowledge INDEX,3 筆全域 pattern,全部載入)**:
  - **KN-1**(contract / skill sourcing):`skills/` 是 PRIMARY 離線 store;`ai-skills/` submodule 只是可選 fallback,**永不從中複製**。
  - **KN-2**(contract / version lock):per-project `.sdlc-lock.json` 鎖 major.minor;`runner.yaml` 的 `contract_version` 只是首跑預設;**永不靜默 auto-migrate**。
  - **KN-3**(dashboard / TUI):stdlib `curses` + 非 TTY fallback;`render_snapshot` 路徑永遠保留;**紅線閘門仍需人工核可**。
- **使用者指示(本 session 新增)**:所有及往後的修正項目,一律交由 **fable 與 codex 交叉決議達成共識**。
  codex CLI 已確認可用:`C:\Users\haruharu\AppData\Local\Programs\OpenAI\Codex\bin\codex.exe`。
- **停點**:依 autonomy——尚無指派需求,此關卡 **halt**,等待使用者給出工作項。

## 步驟紀錄

- 2026-08-22 — CHG-20260822-01 開立 → TDD(guard test 先紅)→ `requirements-dev.txt` 落地 →
  探測 `NOT_RUN`(4) 翻成 `PASS`(0) → 四次 mutation 全數殺死 guard → 全套 161 passed / 2 skipped →
  `doc_integrity_check.py --repo .` exit 0 → ACC-20260822-01 收尾(Pass,11 項全過)→
  KN-4 入知識庫(tag `toolchain` 先註冊進 vocabulary.json)。
- 決議方式:fable × codex 交叉共識(首輪即一致,均選 B),再以實測探測結果佐證。
- 2026-08-22 — 使用者指出 `ai-skills` 已分割改名。查證:`kamira/ai-skills` **已封存**(最後 push
  2026-08-04);使用者說的 `skill-ai-sdlc` 查無此 repo,實際後繼是 **`kamira/skill-ai-sdlc-autopilot`**,
  且**已 clone 在本機同層目錄**、與遠端同步、內含同一支尚未修正的探測器。
  → 我今天寫進 CHG/ACC/KN-4 的「上游構不到、無可預期時程」是**當天就錯的敘述**,已就地更正
  (決議不變,理由更正)。歷史 ledger(2026-06~08 各筆)**不改**——寫下時為真,append-only。
- 未完成:①push + PR + 回填 CI run(需人工確認的 outward 動作);
  ②**改名清理另開 CHG**——`.gitmodules` url、`ai-guideline.md`、`directory.md`、KN-1、README、
  `ARCHITECTURE.md`、`config/runner.yaml`、`src/` 四檔(其中 `cli.py:112` 與 `runner.yaml:20` 的
  `skill_path` 預設值 `./ai-skills/skills/ai-sdlc` 是**功能性過期**,連子路徑都變了——後繼是
  `skills/ai-sdlc-autopilot/`)。動到 `src/` 屬較高風險層級,不併入本輪低風險 CHG;
  ③探測器 pyproject 支援要在 `skill-ai-sdlc-autopilot` 那邊另開 CHG。

- 2026-08-22 — CHG-20260822-02(改名清理)收尾。審議席 **五輪**才收斂:R1 三項分歧;R2 codex 三項全改判;
  R3 兩席提的失敗機制都不合本 repo 慣例(慣例是 typed error → print → return 2),改判並一致選
  S2 分拆;R4 又分歧(V1/V4);R5 fable 改判 V1。定案:刪 `.gitmodules`、fallback 值改
  `./skills/v1.16.0`、KN-1 就地改、guideline:90 劃除加註。`src/` **零邏輯變動**。
  161 passed / 2 skipped(未動任何測試),探測仍 PASS,doc-integrity exit 0。
- 未完成:①push + PR + 回填 CI run(**medium 風險,merge 前需一次人工確認**);
  ②**CHG-ii 尚未開**——移除重複預設 + 六個呼叫點接 `SkillPathError`;審議席留一個未決點:
  類別定義在 `cli.py`(codex)還是 `skillstore.py`(fable,避開 cli↔dashboard 循環);
  ③上游 `skill-ai-sdlc-autopilot` 的 pyproject 探測支援。
