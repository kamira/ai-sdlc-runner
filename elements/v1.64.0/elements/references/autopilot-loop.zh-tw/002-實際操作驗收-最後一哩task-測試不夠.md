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

