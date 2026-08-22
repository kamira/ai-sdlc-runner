## 哨兵輪詢與兩層跳脫(autopilot 延伸錨)

ai-sdlc-autopilot 是本治理層的 **drive 層延伸**。當 autopilot 以「確定性哨兵 + 排程再進入」做「常態需求確認」時,**治理語意錨定於此——autopilot 不得自建平行 taxonomy。**

**哨兵可呼叫 check 清單**——哨兵是*確定性* check(無 LLM);可輪詢的正典集合:

| 輪詢階段 | check | 工具 |
|----------|-------|------|
| 需求 | plan ↔ CHG 一致 | `scripts/plan_check`(autopilot `plan-check`) |
| 結構 | 四結構 ↔ code drift | `scripts/doc_integrity_check` |
| 變更 | scope / halt 判定 | `scripts/halt_gate.py`、scope check |
| 驗收 | 整體治理健康 | `scripts/governance_health.py` |

**兩層跳脫**——哨兵/再進入結果只落一層:

- **A 層——無法評估**(check 不可用 / 無法解析 / 機制失效):**fail-open 退回基線線性流程**——不阻擋(exit 0、log)。降級,絕非默默吞掉真 halt。
- **B 層——真 halt**(上述 always-halt 動作、風險×閘 `HALT`、或 `unknown = halt`):**halt 並升級給人**——絕不 fall-through 到基線。B 層**只**由本文件的 always-halt 動作 + 風險×閘矩陣 + unknown=halt 預設定義;autopilot 讀取,不重定義。

再進入的 base case(plan 完成 / 達再進入上限 / 無進度)是 drive 面(autopilot),但「什麼算真 halt」是治理面(此處)。

