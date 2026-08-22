# handshake — agent `main-67e835`(session ai-sdlc-handshake-67e835)

分支/角色/範圍:`claude/chg-20260822-05`(自 `origin/main` @ `c8f4640`)| 角色:A1 / orchestrator
| RW:全 repo
現在做:**本 session 收尾。所有已開工的變更都已 merge,無未收尾工作。**
下一步:**下一個 session 從進場握手接手,起點是 CHG-20260822-04 的 Task 1(拆解器)。**
最後更新:2026-08-22(UTC+0)

---

# 給下一棒:你要做什麼,以及怎麼開始

## 一、先做進場握手,不要跳過

按 `references/handshake.md` 的固定順序。這個 repo 現在的狀態應該是:

| 檢查 | 預期 |
|---|---|
| 工具鏈探測 | **PASS**(exit 0)。本 repo 有 `requirements-dev.txt`,是 CHG-20260822-01 加的 |
| working tree | 乾淨 |
| CHG / ACC | **24 / 23**。差的那一筆是 **CHG-20260822-04,狀態 draft、刻意無 ACC**——那不是懸空,是還沒開工 |
| doc-integrity | exit 0 |
| Guideline | v1.0;§6 的 current baseline 是 CHG-20260822-03(store v1.64.0) |
| knowledge | KN-1 ~ KN-4 |

**對到不一樣的數字就先查清楚再動手**,尤其 CHG/ACC 若差超過一筆。

## 二、你要做的事:CHG-20260822-04 的 Task 1

`docs/changes/CHG-20260822-04.md` 是**設計定案但一行程式都沒寫**的 CHG。13 個 task 全部未勾。
設計已經過四輪 fable × codex 審議、三次改判、收尾無分歧,**不要重新設計,照著做**。

**但先過確認關卡。** 那筆的 `Autonomy` 欄寫明:高風險,實作開始前需要一次人工確認。設計定案
不等於施工授權——先跟使用者確認再動 Task 1。

從 **Task 1(拆解器:reference → 錨點切段)** 開始。它的 done-when 是「同一份 store 進去,
兩次產出逐位元組相同」,而且每個元素都要能回溯到來源錨點。

## 三、這個 repo 的既定出貨流程(使用者常設授權,不必再問)

```
commit → push → 開 PR → 等 CI → 綠就 merge
```

使用者 2026-08-22 明示「往後都是這個方式處理」。**但 merge 只認真的綠**,見第五節第 2 點。

另一條常設規則:**所有修正項目與待修項目的決策,一律交由 fable × codex 兩席審議**,
不由單一席次拍板。分歧就再開一輪,把對方的立場與你自己查證過的事實餵回去,直到收斂。
**不要平均、不要調和。**

## 四、本 session 做完了什麼(五筆,全部 merged)

| CHG | 內容 | merge |
|---|---|---|
| 20260822-01 | 工具鏈閘門本來就沒在跑(`NOT_RUN`),加衍生 `requirements-dev.txt` | `b61b389` |
| 20260822-02 | `ai-skills` 已封存,改名 `skill-ai-sdlc-autopilot`,清掉所有活引用 | `b61b389` |
| 上游 20260822-01 | 探測器改為讀 pyproject(在 `skill-ai-sdlc-autopilot` repo) | `e3d27c3` |
| 20260822-03 | vendored store 提到 v1.64.0(原本落後 48 個 minor) | `c645d4e` |
| 20260822-04 | **節點引擎設計定案(draft,未實作)** | `c8f4640` |

## 五、踩過的坑,不要再踩一次

1. **`$?` 接在管線後面拿到的是最後一段的退出碼。** 我在這個 session 犯了**兩次**,其中一次
   還是在寫「不要接 `| tail`」那份文件的同一天。判閘門結果一律
   `cmd >/dev/null 2>&1; echo $?`。

2. **CI 的紅 X 可能代表「根本沒跑」。** `steps` 是空陣列、2 秒結束 = job 沒啟動。用
   `gh api repos/<o>/<r>/check-runs/<id>/annotations` 讀真正原因。**private repo 計費、
   public 不計費**(`gh repo view --json visibility`)。沒跑成**不算 CI pass,不得 merge**。

3. **shim 測不到「委派出去的東西合不合法」。** 上游那輪的 `_cmp_prog` 引號寫壞、`$PY -c`
   每次 SyntaxError,而 behave **12/12 全綠**——因為 shim 靠 argv 子字串分派,壞掉的程式裡
   照樣有那個關鍵字。**真實環境跑一次**才抓得到。

4. **`open(p,'w')` 會先截斷,再求值它的參數。** 我寫了
   `open(p,'w').write(open(p).read().replace(a,b))` ——外層先把檔案清成 0 bytes,內層才去讀,
   讀到空字串,**這份交接文件整個被清空**(靠 `git checkout --` 救回)。改檔一律
   「先讀進變數 → 再開寫」,絕不把讀與寫串在同一個運算式裡。

5. **交接文件寫完要逐條對帳。** 第一版待辦寫「`.coverage` 是被追蹤的二進位產物」,查證後
   發現這個 repo 早就 ignore 了(`.gitignore:43`)——我把上游 repo 的觀察錯記到這裡,
   而且「更正」時又寫錯一次。**交接文件裡的假事實比漏寫更糟**,下一棒會照著它動手。
   每一條可查證的宣稱,寫完就跑一次指令驗。

6. **doc-integrity 靠字樣判「已實作」。** `IMPLEMENTED_HINTS` 含 `accepted` / `implemented`,
   所以一份未實作的 CHG 只要出現這些字(**包括英文欄位標籤 `Implemented by:`**)就會被判成
   懸空驗收。未實作的 CHG:用中文欄位標籤 `實作者:`,狀態寫 `草稿 / draft`,
   全文不得出現 `implemented` / `accepted`。

7. **上游 repo 的閘門會擋五種治理補件**,沒有一種是程式邏輯錯:`Verifier-change` 欄 + 基線重簽、
   宣稱清冊重建、`plugins/build_suite.py` 同步、分支名要含 `chg-YYYYMMDD-NN`、diffcov 豁免要
   含 `[signoff: <席次> @ <CHG 編號>]`。**其中 1/3/5 會互相觸發**,順序是
   「改檔 → 重簽 → 同步 → 重建清冊 → 再同步檢查」。

## 六、待辦(處置決策走審議席,不要自己拍板)

1. **CHG-ii(下游)**——移除 `cli.py` 裡 `_resolve_skill_path()` 結尾那行重複的 `skill_path`
   預設(`config.get("skill_path", "./skills/v1.64.0")`),六個呼叫點接 `SkillPathError`
   (house style:typed error → `print` → `return 2`),含測試。
   **審議席留了一個未決點**:類別定義在 `cli.py`(codex)還是 `skillstore.py`(fable,
   為避開 `cli` ↔ `dashboard` 的 import 循環——`dashboard.py` 的 `_resolve_skill_path()`
   現在正是用 `from . import cli as _cli` 的延遲 import 在閃它)。
   **用符號找,不要用行號**:本文件初稿寫的 `cli.py:112` / `dashboard.py:629` 在寫完的當下
   就已經位移成 116 / 627 了。

2. **PEP 735 `[dependency-groups]`**——不是不正當,是 `include-group` 是解析步驟;在聯集語意下,
   只能部分解析的來源會讓今天綠的 repo 掉成 `NOT_RUN`。等 include 解析做完整再開 CHG。

3. **下游那份衍生 `requirements-dev.txt` 現在已非必要**——store v1.64.0 帶進了修好的探測器。
   撤除是另一筆變更,而且要先確認探測器真的生效。

4. **上游 `skill-ai-sdlc-autopilot` 把 `.coverage` 當成追蹤檔**(**這個 repo 沒這問題**,
   `.gitignore:43` 已排除)。上游那筆 PR 的 diff 因此出現
   `.coverage | Bin 77824 -> 69632 bytes` ——一個每跑一次測試就變動的二進位產物進了版本控制。
   屬於上游的另一筆小變更。

## 七、本 session 的 ack(存查)

- 工具鏈:進場時 `NOT_RUN`(exit 4)→ 由 CHG-20260822-01 修成 `PASS`
- 基準:進場時分支無 upstream(降級,非落後);離場時對齊 `origin/main` @ `c8f4640`
- 未收尾:進場時無;離場時無(CHG-20260822-04 是 draft,不算)
- 已知須遵守:KN-1(store 是唯一 skill 來源)、KN-2(per-project 鎖不得被動)、
  KN-3(紅線閘門仍需人工核可)、KN-4(探測器只吃裸名,加回版本範圍會**靜默關掉閘門**)
