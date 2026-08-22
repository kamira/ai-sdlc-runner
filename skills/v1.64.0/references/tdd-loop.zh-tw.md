---
name: tdd-loop
description: >
  autopilot 每個 task 的測試先行紀律:RED(先寫失敗測試、親眼看它失敗)→ GREEN(最小程式碼
  讓它通過)→ REFACTOR(全綠時整理)。沒有失敗測試就沒有生產程式碼;絕不為了變綠而弱化或
  刪除測試。施工任何 task 時讀本檔;它產出的證據行餵進 ACC。
---

# tdd-loop — 紅、綠、重構,逐 task

> 語言 / Language: **繁體中文** · [English](tdd-loop.md)

## 循環

1. **RED** — 從 task 的 `test:` 行出發,先寫最小的失敗測試,**跑一次、親眼看它失敗**。沒看過失敗的測試什麼都證明不了(它可能什麼都沒測)。
2. **GREEN** — 寫**最少**的生產程式碼讓它通過。忍住不超前施工;下一個 task 有它自己的測試。
3. **REFACTOR** — 全綠狀態下整理命名/重複/結構。過程中測試保持綠;行為變更屬於新的 RED,不屬於重構。

## 硬規則

- **沒有失敗測試,就沒有生產程式碼。** task 沒有可測面(純文件)時,其 `test:` 行必須寫一個可重跑的檢核(grep、lint、build),由它扮演 RED/GREEN 的角色。
- **絕不刪除、跳過、放寬測試來變綠**——那是穿著綠衣的漂移。測試本身真的錯了,修它是一個獨立可稽核的步驟(在 commit 裡說明)。
- **同一 task 連續失敗兩次 → 停,切換到 systematic-debugging。** 盲目重試燒預算、學不到東西。

## 給 ACC 的證據

每個 task 以一行可重跑證據收尾——`<測試指令> → 綠(N 通過)`——autopilot 將其彙入 ACC 證據欄。低風險 CHG-lite 的內嵌自驗用同一種行。

## 這是單元/build 級——不是操作測試

task 的 `test:` 行證明**零件對**(RED-GREEN)。它**不是**操作驗收測試——那個把整個變更真的跑一次,寫在計畫的 `### Acceptance operation` 節,在 run 末端閘門(見 autopilot-loop 的操作驗收)。所有 task 綠是必要、非充分;程式 CHG 沒有操作測試在案,仍不得抵達 ACC。
