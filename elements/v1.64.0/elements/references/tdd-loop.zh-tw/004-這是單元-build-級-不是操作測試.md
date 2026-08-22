## 這是單元/build 級——不是操作測試

task 的 `test:` 行證明**零件對**(RED-GREEN)。它**不是**操作驗收測試——那個把整個變更真的跑一次,寫在計畫的 `### Acceptance operation` 節,在 run 末端閘門(見 autopilot-loop 的操作驗收)。所有 task 綠是必要、非充分;程式 CHG 沒有操作測試在案,仍不得抵達 ACC。
