## 核心原則:docs/ 是 agent 之間唯一的事實來源

不靠對話記憶在 agent 間傳遞狀態——對話記憶不可跨 agent、且會被壓縮。每個 agent **進場先讀 `docs/`**(呼應本 skill 的「Session 啟動檢查」與原則「不倚賴記憶,以文件為準」)。能被下一個 agent 接續的前提,是上一個 agent 把狀態完整寫進了文件。

