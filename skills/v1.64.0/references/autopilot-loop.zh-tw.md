---
name: autopilot-loop
description: >
  驅動契約:從需求到 merge 的狀態機、停點決策順序(永遠停點 → CHG Autonomy → policy 矩陣 →
  查無=停)、續作語意、落帳對應、runner 指令與 exit codes。跑整條流程、續作中斷的執行、
  或把 runner 接進 cron/CI 時讀本檔。
---

# autopilot-loop — 驅動契約

> 語言 / Language: **繁體中文** · [English](autopilot-loop.md)

## 狀態機

```
ai-sdlc 進場握手(治理層——必經,含 knowledge INDEX + 未收尾 CHG 掃描)
  → CHG 存在且已確認?  否 → 先走需求/修改治理(ai-sdlc)
  → plan-check 閘(不過 exit 2——壞計畫永遠不開跑)
  → 確認閘            (依 policy:auto / confirm / halt)
  → [ 逐未勾 task T_i:
        TDD 施工 → task 測試 → 唯讀 task review
        → 過:打勾 + commit「CHG-<id>: T<i> <標題>」+ 更新 live handshake
        → 敗:一次回修 → 重審 → 第二次敗 = 停 ]
  → 整支 review
  → 實際操作驗收(真的跑起來:operate → observe → pass;依 policy)
  → 驗收(ACC;依 policy 自驗/獨立)
  → PR → merge(依 policy)→ 收尾:CHG 狀態 + Commit/PR + 重複性檢查 + knowledge
```

## 實際操作驗收——最後一哩(task 測試不夠)

逐 task 的 `test:` 是**單元/build 級**(RED-GREEN——零件對)。它**不證明**變更真的跑起來、真的被操作過——就是「全綠但功能還是壞的」盲區。驗收前 runner 要求一次**操作測試**:把 app/變更真的跑起來、操作它、觀察行為。

- 計畫在 **`### Acceptance operation`** 節宣告操作測試(`operate:` 怎麼跑/操作 / `observe:` 什麼確認可用 / `pass:` 通過標準)——見 execution-plan。
- runner 在此階段的行為:
  - 給了 `--verify-cmd C` 且階段為 `auto`(低/中):跑 `C`;非零 → 停(exit 3,「操作驗收失敗」)。
  - 無 `--verify-cmd`(且非 dry-run):印出 `### Acceptance operation` 簡報後停(exit 3)——**人在迴圈**:實際操作、記錄證據入 ACC,再續 merge。
  - 階段為 `halt`(高風險):**永遠由人執行**——高風險操作簽核不可機器自證,即使 `--verify-cmd` 通過也一樣。
  - `--dry-run`:模擬 operate/observe/pass。
- **docs-only 豁免**:CHG 宣告 `Acceptance-operation: n/a (docs-only)`(且無 `### Acceptance operation`)則略過此階段——純文件變更不逼造假操作。
- **程式類 CHG 既無 `### Acceptance operation` 也無 docs-only 標記→在此停(exit 3)**——程式變更沒有操作測試在案,不得抵達 ACC。

## 針對 agent 產出程式碼的閘門

`--test-cmd` 全綠只證明「agent 寫的測試沒抓到 agent 寫的錯」。兩者出自同一個模型,
共享同一組盲點——ai-sdlc `independent-acceptance` 早已對驗收講過這件事;
當同一個 agent 一口氣把程式與測試都寫完時,這條同樣成立。

四道閘依序架在 agent 產出的程式碼上:

1. **單元執行——強制。** 無 `--test-cmd` 現在會 halt(exit 3)。原本是靜默略過,
   於是一個 task 可以在**一行程式都沒被執行過**的狀態下被打勾、commit。
   `--allow-untested` 是明示逃生口,會印警告並寫入 handshake。
2. **變異。** `--mutation` 對**本 task 變更的檔案**種入錯誤,再跑一次該 task 自己的測試。
   存活變異體逐一報出行號與算子:那些就是「改錯了也不會有東西變紅」的行。
   低於 `--min-kill-rate`(預設 90)給一次回修機會,再不足即 halt。
   測試檔本身排除在變異之外——變異測試檔會用同義反覆把 kill rate 灌高。
   僅支援 Python;其他語言標為**未涵蓋**。
3. **行為規格。** Skill ≥ v1.5.0 的程式類 CHG 必須宣告 `### Behaviour spec` 與
   `- feature: <路徑>`,由 verify 階段逐一執行。CHG 的使用者故事因此從「散文」
   變成可重跑的斷言。
4. **整支 branch review。** 不再是 no-op:真的把 branch diff 交給審查指令,並要求判定行。
   沒有輸出不算通過。

### 驗證器自己也要被驗證

閘門是程式,而 agent 會寫程式。把 `require_test_command` 從前置條件的 tuple 裡刪掉、
或把 kill rate 門檻設成 0,所有既有測試都仍是綠的。兩個機制守住這件事:

- `verifier_integrity.py` 錨定構成檢查裝置那些檔案的 SHA-256。重新錨定必須指名授權的 CHG,
  於是修改驗證器不再是一次靜默編輯,而是一筆有署名的帳本紀錄。
- `test_gates_wired.py` 以 AST 斷言每道閘仍接在流程上——讓閘門失效最省事的方法是把它移除,
  而被移除的閘門不會抗議。

逃生口(`--allow-untested`、低於底線的 `--min-kill-rate`、`--no-commit`)一律印出並寫入
handshake;把門檻降到 60 以下另需 CHG 有一行 `Escape-hatch:` 說明。

## 停點決策順序(嚴格、只准加嚴)

1. **永遠停點**——task 或 CHG 帶 `permanent-halt:<類別>` 標記(不可逆刪除/金流/生產遷移/安全邊界):無條件停;runner 拒絕任何放寬這些的設定。
2. **CHG `Autonomy:` 欄**——只准比 policy 更嚴。
3. **`assets/autopilot_policy.json`**——風險×階段矩陣。
4. **查無 → 停。** 契約認不得的關卡就停下來;猜「auto」正是自動駕駛出事的方式。

`confirm` 階段可經 knowledge directive 預授權(窄類別、闖禍自動失效)——ai-sdlc 的預授權規則,原樣沿用。

## 續作語意

已勾 checkbox=已完成 task;重跑 `run` 會跳過它們、從第一個未勾 task 繼續。live handshake 檔(`docs/worklog/handshake-autopilot.md`)在每個 task 邊界重寫——任一時刻中斷,檔案都是最新。重進場的工作樹對帳屬於 ai-sdlc 握手,不屬於 runner。

## Runner 指令與 exit codes

```
plan-check --chg <CHG.md>                      # 只驗計畫格式(操作測試提示為非阻斷)
run  --chg <CHG.md> --repo . [--agent-cmd T] [--test-cmd C] [--verify-cmd V] [--dry-run] [--no-commit] [--max-tasks N]
status --chg <CHG.md>                          # 已勾/未勾、下一個 task、當前階段
```

`--test-cmd` 跑每個 task 的單元/build 測試;`--verify-cmd` 跑末端操作測試(把變更真的操作一次)。Exit codes:`0` 完成 · `1` 非預期錯誤 · `2` 計畫無效 · `3` 合法停點(印出原因)。cron/CI 接 3(帶原因通知人)與 0(接下一筆 CHG)。`--dry-run` 模擬施工/測試/審查**與操作驗收**成功,不需 agent 即可演練狀態機與停點策略。

## 降級模式

- **無 headless agent**(未設 `--agent-cmd` 且非 dry-run):runner 印出每個 task 簡報後停(exit 3)——人在迴圈模式;勾選照樣驅動續作。
- **無 `--verify-cmd`**(且非 dry-run):runner 印出 `### Acceptance operation` 簡報後停(exit 3)——人執行操作測試並記錄證據入 ACC。
- **無 gh CLI**:PR/merge 階段印出該執行的指令後停(exit 3),不代行合併。
- **審查無法 spawn**:同一 agent 序列地施工再審查——在 ACC 註明降級(與 ai-sdlc 審議降級同規則)。

## 角色拆成獨立指令

迴圈的每個階段也可單獨呼叫——只審一個 diff、只跑操作驗收、只裝哨兵——而 `run` 是同一批單元的**組合**(單一實作、不漂移)。拆成指令**不是治理繞道**:每個角色都走同一 halt policy 與同一帳本,前置條件缺失即 halt(exit 3)。

| 角色 | 前置條件(缺則 halt) |
|------|----------------------|
| `plan` | CHG 可解析、task 格式完整(否則 exit 2) |
| `build` | 計畫有效 · 無永遠停點標記 · 確認閘已過(中/高風險需 `--confirmed`) |
| `review` | 全 task 已勾(整支 review 接在逐 task review 之後) |
| `verify` | 全 task 已勾 · 有 `### Acceptance operation`(或 `docs-only`) |
| `accept` | 全 task 已勾 · 操作驗收已過(先跑 `verify`,或 `--verified` 且證據入 ACC) |
| `sentinels` | ——(確定性輪詢;見下節) |

```
runner plan|build|review|verify|accept --chg <CHG.md> --repo .   # plan-check 仍為 plan 的別名
```

## 施工與審查派給不同模型

`--review-cmd` 讓逐 task 審查指向**與施工不同的指令、因而不同的模型**。未給時審查回退為 `--agent-cmd`,即施工與審查跑在同一個模型上——共享同一組訓練偏誤與盲點,某些錯會**系統性地一起看不到**。回退會**明示、不靜默**,以免高估該輪審查的獨立性。

runner 維持 no-LLM:不解析模型名稱。每個指令實際打到哪個模型,由執行者寫在指令模板裡。各角色的模型選擇依 ai-sdlc `agent-hierarchy` 的「派工模型選用」——判斷密度、獨立性需求、成本。

```
runner build|run --chg <CHG.md> --repo . --agent-cmd '<施工>' --review-cmd '<審查>'
```

## 常態哨兵與排程再進入

「以常態輪詢做需求確認」但不撞平行 fan-out 停滯:一次性 orchestrator 裝好確定性哨兵 + 排程再進入後即**退出**(休眠=退出,非常駐 agent;每次再進入 spawn 全新一次性執行)。治理語意錨定 ai-sdlc `references/autonomy.md`——本層只做 drive,不自建 taxonomy。

- **哨兵**(`scripts/autopilot_sentinels.py poll`):對需求 / 結構 / 變更 / 驗收跑確定性、無 LLM 的 check(`assets/sentinel_policy.json`)。兩層跳脫:
  - **A 層——無法評估**(check 不可用 / 崩潰 / 無法解析):fail-open 退回基線線性流程(exit 0、log)——降級,絕非默默吞掉真 halt。
  - **B 層——真 halt**(check 跑了且旗標:always-halt 動作 / 風險×閘 HALT / unknown=halt):exit 3,升級給人——絕不 fall-through。
- **排程尾遞迴**:cron / scheduled-task 週期重呼 poll;ticked checkbox 是跨次的狀態累加器。base case(`plan 完成 / 無進度 / max_reentry`)停止再進入。
<!-- claim: sentinel-install-always-halts -->
- **安裝=halt**(`scripts/sentinel_install.py install`):建立 cron/CI 屬持久設定 → **永遠 halt 等人授權**(`--i-authorize-cron`);即使授權也只產出可審閱的 crontab 行 + CI 片段,不逕改系統 cron。

```
runner sentinels --repo . [--chg CHG] [--reentry-count N]   # exit 0 = 基線 / 3 = 升級人
```
