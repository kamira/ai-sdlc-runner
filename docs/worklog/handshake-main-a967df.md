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

---

## 2026-08-22 — task 3 已 merge(`d288f4d`);task 4 建置完成

分支:`claude/chg-20260822-04-task4`(自 `origin/main` @ `d288f4d`)
現在做:CHG-20260822-04 task 4/9 —— 收尾中(push → PR → CI → merge)
下一步:**task 5(work-order 格式:schema + renderer)**。task 6 前不需確認關卡,task 6 需要。

### 三態閘門

| 狀態 | exit | 意思 | 要你做什麼 |
|---|---|---|---|
| `match` | 0 | 委付的位元組就是現在生成器的產出 | 無 |
| `drift` | 10 | 重生成成功但不一致 | 重生成——或停止手改元素(§2/§8 禁止) |
| `source_missing` | 11 | 委付元素指名的來源不見了 | 救回 store;重生成救不了 |

**兩個失敗給不同 exit code,不是同一個紅**——因為它們要的動作不同。store 版本被刪掉時
叫人「重生成」,是把人推上一條走不通的路。多版同時失敗時 `source_missing` 壓過 `drift`,
否則標題會是一個修不好的建議。

`source_missing` 的偵測**走 provenance**:每份 manifest 都記了每個元素的 `source_path`,
閘門讀回來檢查路徑是否還在。這讓「這個元素的來源沒了」是機械發現,不是「這版本該有哪些檔」
的判斷——與 task 3 拒絕手寫 per-version 表同一個原則。

版本列舉**同時**掃 `skills/` 與 `elements/`。只掃 store 的話,孤兒元素樹會被整個跳過,
被刪掉的 store 版本會讀成「沒東西要檢查」——在閘門最該響的那一刻靜默放行。

### 測試

13 個測試,**每一個失敗狀態都是把 repo 真的弄壞來產生的**——手改元素、動 store 不重生成、
刪 reference、刪 policy 資產、刪整個 store 版本——沒有一個是把偵測器 stub 掉。
只測快樂路徑的閘門正是這個 repo 歷來 false-green 的活法。

CI 新增獨立的 `elements` job(不是塞進既有 job 的一個 step),所以那裡一紅永遠代表
「衍生樹與 store 不一致」,不會是「別的 lint 掛了」。

### 閘門

`pytest tests/` **251 passed, 2 skipped**;doc-integrity **exit 0**;
`runner elements --repo .` 五版全 `match`(227 / 256 / 347 / 355 / 479 個檔逐位元組相同)。

### task 4 的 CI(6/6,新閘門首次上線)

PR #14 · run 32559369266 —— **6/6 pass**(原本 5 個 job + 新增的 `elements (regeneration gate)`)。
新 job 8 個 steps、0 失敗,log 逐版印出 227/256/347/355/479 個檔 byte-identical。

值得記一筆:**元素樹是在 Windows 產生、在 ubuntu 驗證的**,跨平台 byte-compare 成立。
`.gitattributes` 的 `eol=lf` 到此是雙向都驗過了。

---

## 2026-08-22 — task 4 已 merge(`7dd8f92`);task 5 建置完成

分支:`claude/chg-20260822-04-task5`(自 `origin/main` @ `7dd8f92`)
現在做:CHG-20260822-04 task 5/9 —— 收尾中(push → PR → CI → merge)
下一步:**task 6(節點引擎 + 有序 effect 與 probe)**。**task 6 需要新的確認關卡**——
`Autonomy` 欄的 halt 對它再次生效(它取代四階段路徑)。

### 兩席一輪,三題全同(a / b / a),無分歧

- **Q1 self-sufficiency 綁產物不綁 renderer**——與 A2 判決一致,不必回退。
  fable 給了可操作形式:**工單裡出現不帶 path 與 anchor 的裸 element id 即違反**。
- **Q2 缺能力資料的角色一律硬錯誤**(不是 default-deny)。
- **Q3 task 5 只交付 schema + renderer**,node spec 由 task 6 供給。

### 缺席檢查怎麼寫成機械可驗(task 2 教訓的正面回答)

**不做子字串掃描。** 兩層:①封閉鍵集——斷言渲染輸出的鍵集**恰好等於** D5 白名單,
缺席由「枚舉在場者」證明;②**哨兵注入**——把唯一字串塞進 `RoleSpec.tools`,
斷言序列化後的工單全文不含它,精確值比對、零偽陽性,並加一條防「空過」的斷言。

### 兩個角色資料的事實

- `agents.py` 的 `tools` 清單是 **runner 寫死的 Claude Code 名字**,不是出貨資料。
- fable 又抓到第四個旗標 `writes_docs`,是從 Notes 欄**散文子字串猜**出來的;
  D5 只列三個旗標,所以它與 tools 一樣不得入單。

### 13 個角色只有 4 個能渲染,這是刻意的

沒有出貨能力資料的 9 個(`orchestrator`、`integrator`、`reviewer` + 6 個 `seat-*`)
**渲染時硬錯誤並指名角色**。兩席獨立給出同一個理由:全 false **不是中性安全預設,
是 runner 自己在寫授權政策**——`orchestrator` 顯然必須能 spawn,全 false 的工單
「看起來受治理」實則錯的;而靜默收緊會讓節點做不了該做的事。兩個方向都有害時,不能猜。

**已知後果照 `scripts/lib/` 的規格記錄下來**:在 skill 出貨機器可讀的能力資料之前,
引擎無法派發那 9 個角色,**含審議席**。task 6 **不得**臨場補預設值繞過。
有一條測試釘住 4 + 9 = 13,skill 一旦多出貨能力列就會失敗,強迫回頭重審而不是讓記錄過期。

### 一處引註更正

我在 brief 裡把「runner 只認表內的鍵,不認散文」記成出自 `role_refs.json`;
fable 查證後指出那句在 **`review_seats.json`** 的 `_extending`,而 `role_refs.json`
根本沒有 `_extending` 鍵。我複驗屬實。結論不變(散文仍不是資料),但引註錯了,已更正。

### 閘門

`pytest tests/` **285 passed, 2 skipped**;doc-integrity **exit 0**。

### task 5 的 CI

PR #15 · run 32560052136 —— **6/6 pass**,逐 job 7–8 steps、0 失敗。

---

## 2026-08-22 — task 5 已 merge(`55b6ca8`);停在 task 6 的確認關卡

分支:`claude/chg-20260822-04-task6`(自 `origin/main` @ `55b6ca8`)
現在做:**停在確認關卡,尚未動工。`src/` 一行未改。**
下一步:使用者核可後開 task 6(節點引擎 + 有序 effect 與 probe)。

task 6 為何要新的確認關卡:`Autonomy: high` 對它再次生效——它**取代四階段執行路徑**,
是本 CHG 風險評為 high 的主因(碰 `orchestrator` 233 行 / `state` 90 行 / `agents` 175 行)。

停在此處要向使用者陳明的三件事:
1. opt-in flag:旗標翻轉前既有四階段路徑一行不動;翻轉是**更後面的另一個決定**,不在 task 6。
2. 舊 `state.json` checkpoint 直接失效(設計定案時使用者已核可,無遷移)。
3. **task 5 的硬邊界會在 task 6 發火**:13 角色只有 4 個能渲染工單,引擎碰到另外 9 個
   (含審議席)必須硬停。兩席明確要求不得臨場補預設值——那是把已否決的方案從後門放回來。
   所以 task 6 交出的引擎**流程本來就不完整,這是誠實狀態不是缺陷**。

進度:task 1–5 merged(125 個測試,全套 285 passed);task 8 部分;task 6、7、9 未開工。

### 使用者追加的需求(2026-08-22,逐字保存,將進 CHG 的 requirement 節)

1. runner 要符合的 flowchart **就是 skill 內提供的那一份**,也是一般開發流程路線;
   skill 本身也是基於這流程建置。runner 只是為了不要使用 codex 等其他公司提供的 agent,
   而是**基於本流程重新開發的 AGENT**,**不需要其他花俏的東西**。
2. 流程:使用者輸入指令 → PM 確認方案 → 分發主 agent(主管)確認可行與風險 →
   與 PM 確認後分發 subagent(工程師)做小模組 → 開發後自我驗證 →
   主 agent review 後交 QA 全面測試驗證 → 用戶反饋回報 PM 調整。
3. 節點細分是**為了區分功能:一個項目只做單一類型的工作**。
4. **審議席的目的在於 review**——不能確定單一模型會不會有偏頗的看法與作法,
   需要多個 review 交叉決議達到一致性共識或多數決才允許放行,是避免出錯的機制。
5. `branch_review` 改成**一或多席,由使用者設定多寡**。
6. **所有「詢問節點」都要是獨立 session**,避免 session 連貫時發生偏見。
   (使用者更正:是**詢問節點**,不是所有節點——runner 自己做的事(讀帳本、查閘門)沒有在問任何模型,
   不在此列;綁的是每一個把工單派出去問模型的節點。)

### 第 6 條的現況(實地查證,不是宣稱)

「每個節點獨立 session」**已經是現狀**,不是要新增的機制:

- 工單自足(task 5:封閉 schema、無 session 或前一輪上下文欄位)
- `graph.py` 無狀態;`effects.py` 的 probe 讀世界(ledger / git / forge),不讀自己寫的紀錄
- `config/runner.yaml` 的 executor 預設 `argv: ["claude", "-p"]` —— 一次性非互動呼叫,
  `extra_args` 為空,本來就沒有 session 延續

要補的是**在引擎派發點加測試把它釘死**,避免日後有人為了省 token 加上續接。

**由第 5 + 6 條推出的一件事**:審議席的多席是**同一個節點裡的多次詢問**,所以
**每一席也各自是獨立 session**。否則「多席」會退化成同一個模型在同一個脈絡裡答 N 次——
那正是出貨 phase 1 要防的錨定,也正是使用者說的「單一模型的偏頗」。
席數由使用者設定,獨立性不由使用者設定:它是機制本身。

### 第 4、6 條的理由是同一個,而且比原本的理由更根本

使用者給的理由是「session 連貫會造成偏見」;出貨的 `review-panel.md` phase 1 給的理由是
「anti-anchoring;a seat that reads first agrees first」。**同一件事。**
原本 CHG 記的三個理由是 token 成本、崩潰不汙染流程、跨模型彈性——
第四個理由是**獨立性是正確性的前提,不只是省錢**。

### 第 5 條的一個衝突,需要裁決

出貨政策有風險分級的席數下限:高風險**六席全開且強制**、中風險**至少五席**、低風險不開;
決策不少於 5 席、驗證不少於 3 席。而全案原則是「只准加嚴」。
所以使用者設定**可以往上加席,不得低於該風險等級的出貨下限**——除非使用者另行指示。

### 席數下限的裁決(使用者,2026-08-22)

**預設有強制下限**(依出貨政策:高風險六席全開、中風險至少五席、決策不少於 5 席、驗證不少於 3 席),
**但允許使用者開啟「高風險模式」來規避這個限制,在 GUI 上設定。**

這是對出貨政策的**放寬**,而 halt policy 規定放寬需人預先核准——使用者就是那個人,已核可。
實作要點,比照出貨對 `--allow-no-ci` / `--allow-untested` 的處置
(「prints a warning and is written to the handshake file」):

- 預設路徑強制下限,不可繞過。
- 高風險模式是**顯式開關**,在 GUI(`tui.py` / `dashboard.py`)設定,不是設定檔裡一個安靜的欄位。
- **開啟這件事本身要寫進帳本**(worklog + 該次 run 的紀錄),含當時的風險等級與實際席數。
  沒有留痕的繞過正是本 repo 反覆抓到的那一類。

### 審議席 phase 1:codex 回了**兩票否決**,兩票都成立,已照收

1. **副作用缺陷席 — 否決(真 bug)**:`effects.run` 找到 frontier 後,對其後所有 effect
   **無條件 apply**,不再各自探測。真實世界會重複副作用(`gh pr create` 對已存在的 PR)。
   更糟的是**我自己的測試 `test_a_later_met_postcondition_...` 正是在斷言這個行為**——
   測試在掩護風險而不是抓它。而且它與 `effects.run` 自己的 docstring 直接矛盾。
   **已修**:任何 postcondition 已為真的 effect 一律不再 apply(frontier 前後都是);
   frontier 之後卻已為真的,列入新的 `out_of_order` 回報——不靜默重做、也不靜默放行。
   新增一條一般化測試(已為真的 effect 在任何位置都不被 apply)。
2. **測試強度席 — 否決(範圍)**:task 6 要交付的是 **node engine**,目前只有圖資料 +
   靜態 `validate()` + 獨立的 effect helper。沒有節點走訪、沒有 branch/loop 執行、
   沒有 work-order 接線、沒有 opt-in flag;而且硬停測試只直接呼叫 `capabilities_for`,
   **沒有走圖派發**,所以沒證明執行時真的硬停。`Effect` 也還沒落實 D6.1 的 ledger-first。
   **照收:引擎確實還沒做。**

註:codex 無法執行測試(唯讀沙箱沒有可用的 temporary directory,pytest 收集前即停),
判定依原始碼與測試逐項審讀。這不減損上述兩項——第 1 項是讀 `run()` 就看得出來的。

### 使用者再追加(2026-08-22,逐字)

7. **每次詢問都是獨立建立一次 session,詢問完畢後就關閉 session,不要有持續的情況。**
8. **本項目要允許多模型互審**,並**抗 session 失聯**——最糟情況下也要能**保留詢問的內容**,
   待下次恢復時再詢問。目的:**抵抗模型依照先前的問答偷懶或者偏見**。
9. **不只是在 review**——PM、QA、主管、被派工者**都要**能在 session 中斷時接續前一個命令。

### 這三條怎麼變成機制(不是宣稱)

- **session 生命週期改由引擎持有**:`open → ask → close`,close 放在 `finally`。
  dispatcher 沒有機會把 session 留著跨 ask 用。**工廠若回傳曾經回傳過的 session,直接硬錯誤**
  ——那正是「持續」的定義。純 callable 仍相容,被包成 one-shot,第二次 ask 會被拒。
- **問題先寫下來再問**(`AskJournal`):order 在 session 開之前就落盤成 `pending`,答完才轉
  `answered`。session 掉了,**損失的是答案不是問題**;下次恢復時 pending 的那筆可以**逐位元組
  原樣再問**。已答的不會被重問。這是 D6 的紀律套到「問」這件事上。
- **多模型互審**:路由(誰來答)住在 session factory,**不進工單**——D5 本來就把 model /
  dispatch 設定排除在工單外。所以「同一個問題、不同的答題者」是結構保證,測試斷言三席拿到的
  order 字串完全相同、答題者互異。
- **第 9 條已由機制涵蓋**:journal 對**每一個詢問節點**生效,不只 review。測試逐角色驗過:
  analyst(PM 那段)、lead-implementer(主管)、sub-implementer(被派工者)、verifier(QA),
  各自在中斷時 pending 恰好一筆、node 與 role 正確,先前已答的全是 answered。

### 順帶被測試逼出來的一個真缺陷

分支決策原本是 `{node_id: 單一字串}`,**表達不了出貨的 per-task 迴圈**(要能說「task, task, none」)。
靜態 map 會讓迴圈要嘛無限跑、要嘛只跑一次。已改成可給序列,逐次消耗;次數不夠就硬錯誤,
**不猜迴圈何時結束**。

### 現況

`graph.py`(22 節點)、`effects.py`、`engine.py` + `test_graph`(21)、`test_effects`(12)、
`test_engine`(36)。全套 **354 passed, 2 skipped**;doc-integrity exit 0。
