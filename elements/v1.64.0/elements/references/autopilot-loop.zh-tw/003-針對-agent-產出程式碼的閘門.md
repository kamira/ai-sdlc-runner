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

