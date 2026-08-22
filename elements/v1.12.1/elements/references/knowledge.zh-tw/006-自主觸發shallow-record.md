## 自主觸發(shallow record)

不要等被糾正——**同樣的需求/目的第二次跨 CHG/需求出現,就觸發 shallow record**(閾值 2,可調)。可能跨 session,所以**證據與計數落在條目裡,不靠記憶**。檢查點在 CHG 收尾(見 modification-guide):本次變更的動機是否重複了先前某筆?

```markdown
## KN-<n> — <一句規則假說>
- tier:shallow / deep(+升級日期)
- 日期 / 分支:YYYY-MM-DD(UTC+0)/ <branch 或全分支>
- tags/scope:<模組 / 主題——小寫英文固定詞彙;這是檢索鍵>
- 觸發證據:<CHG-… 編號 / 需求提及(≥2 次)>
- 計數:seen <n> / applied <n> / last-applied <日期>
- 狀態:觀察中 / 生效 / 失效(原因)
```

