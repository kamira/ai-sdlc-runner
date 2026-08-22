## 平台中立範例(pipeline,pseudo)

以下為概念示意,可翻成任何 CI 平台(GitHub Actions / GitLab CI / Jenkins…)的等義設定:

```yaml
on: pull_request
jobs:
  governance:
    steps:
      - run: <跑測試>                      # gate 1:測試必綠
      - check: PR 描述含 "CHG-"             # gate 2:變更留痕
      - check: 若 changed_files 命中 src/models|schema 等結構性路徑,
               則 docs/structure/ 必須也有變更                # gate 3:結構同步
      - check: docs/acceptance 內存在對應本次 CHG 且結論=通過的 ACC  # gate 4:驗收門檻
      - check: 若 CHG 風險=高,ACC 的「驗收者」≠ CHG 的「實作者」     # gate 5:身分檢查
```

GitHub Actions 對應做法舉例:用 `on: pull_request` 觸發;`gate 1` 跑測試步驟;`gate 2/3/4` 用一個腳本讀 PR body 與 `git diff --name-only` 比對路徑、並 grep `docs/acceptance/` 對應檔,任何一項不過就讓該 step 退出非零碼擋下合併。其他平台(GitLab CI 的 `rules` / Jenkins 的 stage)概念相同。

