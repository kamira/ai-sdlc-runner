# handshake — agent `main-a967df`(session ai-sdlc-handshake-a967df)

分支/角色/範圍:`claude/ai-sdlc-handshake-a967df`(worktree,HEAD == `origin/main` @ `cdf0158`)
| 角色:A1 / orchestrator | RW:全 repo

現在做:**進場握手完成,等待需求指派。**
下一步:**若要動 CHG-20260822-04 Task 1(拆解器),需先過該筆 `Autonomy` 欄的人工確認關卡
——設計定案不等於施工授權。**
最後更新:2026-08-22(UTC+0)

---

## 進場對帳結果(與前一棒 `handshake-main-67e835.md` 的預期逐項比對)

| 檢查 | 前一棒預期 | 本次實測 | 一致 |
|---|---|---|---|
| 工具鏈探測 | PASS | `TOOLCHAIN: PASS`(exit 0,python3 3.11.9,相依全符合) | ✅ |
| working tree | 乾淨 | `git status --porcelain` 空 | ✅ |
| CHG / ACC | 24 / 23,差的是 CHG-20260822-04(draft,刻意無 ACC) | 24 / 23,同一筆 | ✅ |
| doc-integrity | exit 0 | exit 0(結構同步 + CHG↔ACC + 欄位 + secrets + commit 治理) | ✅ |
| Guideline | v1.0,§6 current baseline = CHG-20260822-03(store v1.64.0) | 同 | ✅ |
| knowledge | KN-1 ~ KN-4 | KN-1 ~ KN-4,全 active | ✅ |

**無數字落差,無需追查。**

## 基準

- `--check-baseline`:**降級**——本分支(worktree 新開)無 upstream,非落後。
- 人工補對:`git fetch origin` 後 `HEAD..origin/main` = 0、`origin/main..HEAD` = 0,
  即 **HEAD 與 `origin/main` @ `cdf0158` 完全一致**。降級不掩蓋落後。

## Skill 版本自檢

- 帳本最新記錄(CHG-20260822-03/-04)宣告 `Skill: ai-sdlc v1.64.0`。
- 本次握手所有閘門腳本都從 `skills/v1.64.0/scripts/` 執行,該版 SKILL.md frontmatter `version: 1.64.0`。
- **記錄沒有比我新 → 不過舊。** 惟安裝端 plugin 載體(`~/.claude/plugins/data/ai-sdlc-suite-inline`)
  目錄為空,讀不到執行中 plugin 的自報版本;以 vendored store 為準(KN-1:store 是唯一 skill 來源)。

## 未收尾

- **無懸空驗收。** CHG-20260822-04 狀態 `草稿 / draft`,全文無 `implemented` / `accepted` 字樣
  (KN 之外的既知陷阱:doc-integrity 靠字樣判「已實作」),因此不被判為懸空,doc-integrity 亦確認。
- 它是**未開工**,不是未收尾。13 個 task 全未勾。

## 須遵守(knowledge,全 active)

- **KN-1** — `skills/` 是唯一 skill 來源(vendored git archive);無 submodule fallback;不得複製 skill markdown 進 runner。
- **KN-2** — per-project `.sdlc-lock.json` 鎖 major.minor;`runner.yaml` 的 `contract_version` 只是首跑預設,版本升不得動既有鎖。
- **KN-3** — dashboard 走 stdlib curses + 非 TTY fallback;紅線閘門仍需人工核可。
- **KN-4** — `requirements-dev.txt` 只吃裸名;加回版本範圍會讓閘門**靜默變 NOT_RUN**。

## 常設授權(使用者 2026-08-22 明示,不必再問)

- 出貨流程:`commit → push → 開 PR → 等 CI → 綠就 merge`。
- **但 merge 只認真的綠**:`steps` 空陣列 / 2 秒結束 = job 沒啟動,不算 pass。
- 所有修正與待修項目的處置,一律交 **fable × codex 兩席審議**,不由單一席次拍板;分歧就再開一輪。

---

## 2026-08-22 — 停在 CHG-20260822-04 Task 1 的確認關卡(尚未動工)

使用者指派 Task 1(拆解器:reference → 錨點切段)。該筆 `Autonomy: high`,施工前須人工確認。
**目前 `src/` 一行未改。** 以下為確認關卡前的唯讀量測結果。

### 量測到三件 CHG 沒涵蓋 / 記錯的事

1. **CHG 的位元組數標籤錯了。** 「23 English `references/*.md` | 343,366」——實測 343,366 是
   **46 份 EN+ZH 的總和**;EN 單獨是 **184,452**。`modification-guide.md` 18,703 與
   `SKILL.md` 40,607 兩個數字都對得上,只有這一列標錯。動機不受影響(單一 section 仍要付整份語料),
   但數字會被下一棒繼承。
2. **`##`/`###` 有 56 個落在 ``` 圍欄內,不是標題。** EN 257 個匹配中,真標題 201 個。
   `structure-design.md` 17 個、`modification-guide.md` 14 個、`requirement-analysis.md` 10 個——
   都是文件骨架範例。裸 `^##` 切段會生出 56 個假元素並切碎正文。圍欄計數全為偶數,偵測可靠。
3. **`.gitattributes` 是 `* text=auto`,store 內 46 份 md 在 Windows 工作區全是 CRLF。**
   git blob 是 LF。若 provenance 的 `source_sha256` 取工作區原始位元組,**同一份 store 在
   ubuntu 與 windows 會算出不同雜湊**,Task 4 的重生成閘門必定在其中一個 OS 硬失敗。
   這正是 CHG-20260817-09 那五個 Windows-only 失敗的同一類缺陷。

### 處置

第 3 點是實作層決定,歸 D3 點名的「runner-authored 分段啟發式」:**雜湊基準取 LF 正規化後的內容**
(對齊 git blob),產物一律以 LF 寫出。這是唯一能通過 OS 矩陣的選法,不改設計。
第 1、2 點待確認關卡回報。語言範圍(EN 23 份 vs EN+ZH 46 份)是唯一需要使用者裁決的分歧點。

最後更新:2026-08-22(UTC+0)

---

## 2026-08-22 — CHG-20260822-04 Task 1 已建置(使用者於確認關卡授權)

分支:`claude/chg-20260822-04-task1`(自 `origin/main` @ `cdf0158`)
現在做:CHG-20260822-04 task 1/9 —— 收尾中(push → PR → CI → merge)
下一步:**task 2(policy → dispatch elements)**;它不需要新的確認關卡,
task 6(引擎取代四階段)才需要。

### 產出

- `src/ai_sdlc_runner/decompose.py` —— 純 stdlib,唯讀 `skills/<version>/`,不改 skill。
- `tests/test_decompose.py` —— 24 個測試,三組對應三個 done-when,另兩組釘住兩個啟發式。
- `docs/structure/directory.md` —— 補上兩個新檔(結構同步閘要求)。
- `docs/changes/CHG-20260822-04.md` —— 任務表加 State 欄、task 1 打勾、補 Task 1 record、
  修正位元組數標籤、狀態改為 `草稿 / draft — 1 of 9`。

### 量測

46 份 reference → **448 個元素**(en 224 + zh-tw 224;preamble 46 / `##` 360 / `###` 42)。
中位數 577 bytes,最大 5,093 bytes(`modification-guide#workflow`)——對照原檔 18,703、
整份語料 343,366。

### 閘門

- `pytest tests/` → **185 passed, 2 skipped**(2 個是既有的 Windows `curses` skip,無關)。
- `doc_integrity_check.py --repo .` → **exit 0**(以 `cmd >/dev/null 2>&1; echo $?` 判,不接管線)。

### 對前一棒交接文件的兩處更正

1. 「13 個 task 全部未勾」——實際是**任務表 9 筆 + 結構文件 3 個勾選格 = 12**,沒有 13。
2. CHG 動機表「23 English `references/*.md` | 343,366」標籤錯:343,366 是 46 份 EN+ZH 總和,
   EN 單獨 184,452。已在 CHG 內更正並保留原數字為第二列。

最後更新:2026-08-22(UTC+0)
