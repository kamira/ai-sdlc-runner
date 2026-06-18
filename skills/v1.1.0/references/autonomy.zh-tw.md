---
name: autonomy
description: >
  自主執行與停點契約:定義一個自主跑流程的 AI / 外部協調器(Python 等)「跑到哪該停下等人核准、
  哪裡可自主續跑」,而不是讓協調器自己看 Risk 欄憑感覺推斷。當你要讓 agent 自主跑完多階段、或用外部
  程式驅動本流程時讀本檔。涵蓋停點關卡、風險×關卡決策表、永遠停點動作、CHG 覆寫,以及機器可讀契約
  (assets/halt_policy.json)與查詢工具(scripts/halt_gate.py)。
---

# autonomy — 自主執行與停點契約(halt points)

> 語言 / Language: **繁體中文** · [English](autonomy.md)

## 用途

讓「自主跑流程」有明確界線:**哪些關卡可自主續跑(auto)、哪些必須停下等人核准(halt)**。這是給「會自己連跑多階段的 agent」或「用外部程式(Python 等)驅動本流程的協調器」的契約——把停點寫成**機器可讀規則**,協調器用讀的、不用自己看 Risk 憑感覺推斷。

> 注意:這與 `ci-cd` 的 pre-commit / pipeline 不同——那是「commit/合併」的把關閘;本檔是「自主執行過程中該不該停下等人」的停點,兩者互補。

## 停點關卡(gates)

流程中幾個會「往前推進」的轉換點,都是潛在停點:

| gate | 位置 |
|------|------|
| `requirement_confirmed` | 需求分析產出 Guideline 後、進結構設計前 |
| `structure_confirmed` | 結構設計產出後、開始實作前 |
| `before_implement` | 修改治理產出 CHG 後、開始改碼前 |
| `acceptance_failed` | 驗收未通過、要進回修迴圈前 |
| `before_merge_or_release` | 驗收通過後、合併 / 發佈 / 交付前 |

## 決策:風險 × 關卡

依本次變更的 **Risk**(來自 CHG/ACC 的風險分級欄)查表,得 `auto` 或 `halt`:

| gate \ Risk | 低 | 中 | 高 |
|-------------|----|----|----|
| requirement_confirmed | auto | auto | **halt** |
| structure_confirmed | auto | auto | **halt** |
| before_implement | auto | auto | **halt** |
| acceptance_failed | auto | **halt** | **halt** |
| before_merge_or_release | auto | **halt** | **halt** |

直覺:**低風險全程自主;中風險在「合併/交付」與「驗收失敗」處停;高風險每個關卡都停等人。**

## 永遠停點動作(不論風險)

以下動作**一律 halt 等人**,風險低也不例外(對應安全紅線):

- 上線 / 發佈(production deploy / release)
- 資料遷移 / 不可逆 schema 變更
- 刪除資料 / drop table / 硬刪除
- 金流 / 移動資金
- 變更密鑰 / 憑證 / 存取權限
- 發佈公開內容

## CHG 覆寫(per-change)

單筆變更可在 CHG 標頭用 `Autonomy:` 欄覆寫:
- `Autonomy: halt`(加嚴)→ 直接停點,隨時可用。
- `Autonomy: auto`(放寬)→ **只對非「永遠停點」項有效,且高風險停點的放寬需人預先核准**;契約不會自動放寬高風險(仍回 HALT 請人確認)。
原則:**覆寫只准加嚴;放寬要人點頭。**

## 機器可讀契約與查詢工具

- 契約:[`assets/halt_policy.json`](../assets/halt_policy.json)(可編輯;含 gates 決策表 + always_halt_actions)。
- 查詢:[`scripts/halt_gate.py`](../scripts/halt_gate.py)——外部協調器在每個關卡呼叫,讀契約回傳決策:

```bash
python3 scripts/halt_gate.py --gate before_merge_or_release --risk high
# 印出 AUTO 或 HALT;退出碼 0=AUTO、10=HALT。範例:
#   python3 scripts/halt_gate.py --gate "$G" --risk "$R" --action "$ACTION" || await_human_approval
```

這樣「跑到哪該停」由契約決定,協調器讀規則執行,而非各自推斷——可重現、可稽核、可調整。

## 與既有流程的關係

- 風險來源:`modification-guide` 的 CHG 風險分級欄 / `acceptance-verification` 的 ACC 風險欄。
- 與 `agent-hierarchy`:自主跑的編制中,上層 agent 在每個關卡查停點契約決定要不要回報人類。
- 與 `ci-cd`:停點管「自主執行中途」;CI 閘管「commit/合併」。兩者可同時存在。
