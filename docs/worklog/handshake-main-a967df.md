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

### CI 結果(真的綠,不是沒跑成)

PR #11 · run 32556767352 —— **5/5 pass**。逐 job 用 API 查過 `steps`,不只看紅綠:

| job | 結果 | steps | 失敗步驟 |
|---|---|---|---|
| doc-integrity | pass 6s | 7 | 0 |
| pytest ubuntu py3.13 | pass 13s | 8 | 0 |
| pytest ubuntu py3.9 | pass 22s | 8 | 0 |
| pytest windows py3.13 | pass 31s | 8 | 0 |
| pytest windows py3.9 | pass 1m28s | 8 | 0 |

Windows py3.9 的 log 讀到 `185 passed, 2 skipped`,兩個 skip 就是既有的 `curses`——
**24 個 decompose 測試在 Windows 上全跑了**。這一點是啟發式 B 的實證:
`test_crlf_and_lf_sources_produce_identical_elements` 自己造 CRLF 與 LF 兩份同內容來源比對,
在兩個 OS 上都通過,所以跨 OS 雜湊一致是**由構造保證**,不是剛好 checkout 一樣。

repo 為 PUBLIC(`gh repo view --json visibility`),不涉計費封鎖。

---

## 2026-08-22 — task 1 已 merge;task 2 建置完成

分支:`claude/chg-20260822-04-task2`(自 `origin/main` @ `30a9bd3`)
現在做:CHG-20260822-04 task 2/9 —— 收尾中(push → PR → CI → merge)
下一步:**task 3(fuse into vendoring + backfill v1.64.0)**。task 6 之前不再需要確認關卡。

- task 1:PR #11 merge 為 `30a9bd3`,兩輪 CI 皆 5/5 真綠(逐 job 查 steps,7–8 個、0 失敗)。
- task 2:`dispatch.py` + `test_dispatch.py`(25 測試)。全套 **210 passed, 2 skipped**;
  doc-integrity exit 0。

### 兩席審議:兩輪,codex 三題全部改判

| | round 1 codex | round 1 fable | round 2 |
|---|---|---|---|
| Q1 元素鍵 | 13 × 11 = 143 | 不做乘積:11 checkpoint + 13 role manifest | codex 改判 |
| Q2 錨點收斂 | 規則選出 + fail-closed | 角色檔案集全錨點 | codex 改判(自認「會永遠失敗」) |
| Q3 risk 軸 | 進元素鍵 | 執行期參數 | codex 改判 |

收尾無分歧。每次改判都掛在一個實測事實上,不是折衷。

### 我自己查證、兩席都沒查到這麼細的三件事

1. **11 個 policy key 對 402 個真標題:真陽性 0、偽陽性 21**(`pr` 中在 `Org principles`、
   `merge` 中在 `Emergency override`)。這是 Q2 的判決依據。
2. **同一個子字串陷阱咬到我自己的守門測試**:`test_no_node_id_is_written_in_the_source`
   首跑就掛,回報 `merge` 與 `pr` ——它們出現在我自己程式碼的普通英文字裡。
   已改成比對**帶引號的字串字面量**,那才是真正被禁止的東西。
3. **store 缺 `scripts/lib/`**:`autopilot_runner.py` 在 vendored store 裡**跑不起來**
   (`from lib import roles` → `ModuleNotFoundError`),CHG-20260822-03 的 `git archive` 沒收進去。
   所以 autopilot 軸**沒有可用的出貨解析器**——元素照實寫 `"shipped_resolver": null`,
   不自己發明 `halt` 與 `halt_independent` 的全序。補 vendoring 是另一筆變更。

最後更新:2026-08-22(UTC+0)

### task 2 的 CI(真綠)

PR #12 · run 32557718514 —— 5/5 pass。doc-integrity 7 steps、四個 pytest job 各 8 steps,
全部 0 失敗;windows py3.9 的 log 讀到 `210 passed, 2 skipped`。

---

## 2026-08-22 — task 2 已 merge(`5c87246`);task 3 建置完成(含 task 8 的窄幅 §7 條目)

分支:`claude/chg-20260822-04-task3`(自 `origin/main` @ `5c87246`)
現在做:CHG-20260822-04 task 3/9 —— 收尾中(push → PR → CI → merge)
下一步:**task 4(重生成閘門:CI 三態)**。task 6 之前不再需要確認關卡。

### 三件事一起落地(審議席判定不可分離)

1. **修正 task 2 的包裝缺陷(實測驅動,具名記錄不靜默改)**——單份 role manifest
   54,670 → **6,644** bytes;13 份 819,984 → **110,920**;整棵 v1.64.0 樹 1,536,506 → **838,922**。
   成因:5 組 situational 在 13 份裡 hash 完全相同(單塊 20,397 bytes,純重複 265KB),
   加上錨點欄位重複 `element_id` 已能決定、`manifest.json` 已權威持有的資訊。
   **fable 在看到數字後撤回自己 round 2 的細化寫法。**
2. **全五版 backfill**——1,664 個檔、2,731,490 bytes,落在 `elements/v<version>/`
   (`skills/` 的兄弟目錄,不進 store 內,KN-1)。
3. **§7 窄幅覆寫條目**隨同一筆落地(task 8 部分完成)。

### 審議席三輪,兩席都改判

CHG **自己內部矛盾**:D2 說 v1.64.0 是 one-time migration,task 3 的 done-when 說
「no store version exists without elements」。

| 輪 | codex | fable |
|---|---|---|
| 1 | (iii) 全版本 + 每版受治理期望基線 + 第四態 not_applicable | (ii) 只 v1.64.0 + 凍結四版名單 + 改述 done-when |
| 2 | **改判 (iv)** | **改判 (iv)** |

**讓兩席同時改判的是我實跑推導的結果,不是論證**:內容元素五版全可導;`halt:*` 五版全可導
(五版都有 halt_policy)——舊版報錯是**我自己把兩份 policy 綁在同一個函式**的實作耦合,
不是資產缺失。只有 v1.0.0 真的組不出 work order(無 role table)。
fable 的「舊版是不可派發的裝飾品」對它涵蓋的四版中的三版不成立,它自己說得很直白:
「我的核心論證被實測推翻,而且我自己的方案帶有我攻擊對方的同一缺陷。」

(iv) 的關鍵:**族系可導與否讀該版自己的 `assets/`**——它就在 archive 裡,它**就是**清冊。
兩個第一輪方案各自需要的第二真相源就此消失,而第二真相源會靜默過期卻仍看起來權威(KN-4 形狀)。

### fable 的約束性保留(已滿足)

閘門必須是整樹重生成 + byte-compare,**任何地方都不得有手寫的 per-version 期望表**,
連測試也不行——`test_elements_tree.py` 在執行期列舉 `skills/`,
`test_no_version_is_hard_coded_in_the_generators` 會在版本字串出現在生成器裡時失敗。

### 又一次 CRLF

`elements/**` 已在 `.gitattributes` 釘成 `text eol=lf`。沒釘的話 `* text=auto` 會讓這棵樹在
Windows 檢出成 CRLF 而 blob 是 LF,byte-compare 在半個矩陣上必失敗——
**這是同一個變更裡第二次要防這個形狀**。

### 閘門

`pytest tests/` **238 passed, 2 skipped**;`doc_integrity_check.py` **exit 0**。

### task 3 的 CI(真綠,而且驗到了關鍵那一格)

PR #13 · run 32558950015 —— 5/5 pass,逐 job 7–8 steps、0 失敗。
**windows py3.9 讀到 `238 passed, 2 skipped`** ——委付的 1,664 個元素檔在 CRLF 傾向的
Windows 檢出上與現生成結果 byte-compare 通過。`.gitattributes` 的 `elements/** text eol=lf`
因此是在真實環境驗證過的,不是只在本機推論。
