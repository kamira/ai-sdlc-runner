## 上層 agent 規則(orchestrator / parent)

- **派工前指定角色與讀寫權限**:每個子代理都要有明確角色與可讀/可寫範圍(見 cross-agent、independent-acceptance);驗收類子代理唯讀。
- **收集並統整錯誤**:把所有子代理回報的錯誤,最後統整進**知識庫** `docs/knowledge/errors.md`——去重、歸納共通模式、寫下「錯誤 → 根因 → 解法 → 預防」。
- **知識庫是累積資產**:每個 agent 進場(配合 Session 啟動檢查)**先讀知識庫**,避免重犯已知錯誤。

