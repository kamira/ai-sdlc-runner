## 兩個檢查點:pre-commit(初步)與 pipeline(完整)

治理門檻可以放在兩個層級,兩者可擇一或併用:

- **pre-commit(本機、快、初步)**:在 commit 前先跑「便宜、秒級」的檢查,把明顯問題擋在進版控之前——例如 lint/format、快速單元測試、`CHG-` 參照檢查、「改了結構性檔卻沒動 docs/structure」的提醒。用 `pre-commit` 框架或 git hook(`.git/hooks/pre-commit`)。**初步、可被繞過(--no-verify),所以不是最終防線。**
- **pipeline(CI、完整、權威)**:在 PR / merge 時跑完整測試、結構同步、ACC 門檻——**不可繞過,是最終防線**。

建議分工:**快而便宜的放 pre-commit 給即時回饋;慢而權威的(完整測試、ACC 門檻)放 pipeline。** 同一條檢查可兩邊都放(pre-commit 給早期提醒、pipeline 強制)。單人專案可只用 pre-commit;團隊建議至少有 pipeline。

