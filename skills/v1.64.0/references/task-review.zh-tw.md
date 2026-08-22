---
name: task-review
description: >
  逐 task 唯讀審查:單一 reviewer 回傳雙判定——規格合規(diff 是否滿足該 task 的 interfaces
  與 test?)與品質——外加合法的「cannot-verify」判定(需求落在本 diff 之外)。一次回修機會,
  再敗即停。末端整支 review 先於驗收。判定任何 task 的 diff 時讀本檔。
---

# task-review — 一個 reviewer、兩個判定、唯讀

> 語言 / Language: **繁體中文** · [English](task-review.md)

## 輸入(與防錨定規則)

reviewer 收到的是 **task 簡報**(全域約束+該 task 條目)與**該 task 的 diff**——僅此而已。沒有實作者自述、沒有對話逐字稿:自述會複製錨定,和 ai-sdlc 獨立驗收「永不讓實作者向驗收者簡報」是同一個理由。

## 雙判定(讀一次、判兩項)

在同一次讀 diff 中判定:

- **spec** — diff 是否交付該 task 的 `interfaces:`、滿足其 `test:` 行?(`pass` / `fail` / `cannot-verify`——需求落在本 diff 之外;是合法判定,不是失敗)
- **quality** — 是否合乎周邊程式碼慣用法、無超出 task 範圍的漂移、無弱化測試、無 secrets。(`pass` / `fail`)

輸出恰好一行判定(runner 會解析):

```
[task-review] T<n> | spec: pass|fail|cannot-verify | quality: pass|fail | <一句理由>
```

## 規則

- **唯讀**:reviewer 永不動工作樹。發現寫進判定行;修是施工者的事。
- **一次回修**:任何 `fail` → 施工者拿到判定行、修一次 → 重審。第二次 `fail` 即停(exit 3)——兩次過不了審的 task 需要的是人或更好的計畫,不是第三次猜。
- **末端整支 review**:最後一個 task 完成後,對整條 branch diff 做一次 review(同判定格式,`T<n>` 改 `branch`),用可用的最強模型——逐 task 審查看不見跨 task 漂移。其判定是 ACC 的輸入之一。**接著是操作驗收階段**(依計畫的 `### Acceptance operation` 把變更真的跑一次)——review 讀 diff,操作驗收跑結果;兩者都先於驗收(見 autopilot-loop)。
- 所有判定行落 **ACC 證據欄**——審查軌跡是帳本的一部分,不是聊天紀錄。
