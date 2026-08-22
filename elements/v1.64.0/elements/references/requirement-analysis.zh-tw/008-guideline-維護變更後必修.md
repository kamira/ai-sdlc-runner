## Guideline 維護(變更後必修)

Guideline 是活文件,不是一次性:**每當結構調整或需求更新,原有 Guideline 必須同步修正並升版**(改對應 FR/範圍/驗收條件、版本 +1、在變更歷程註記)。修改流程(modification-guide)收尾時要檢查 Guideline 是否已跟上;文件驗證(doc-integrity)也把「Guideline 落後於已定案的結構/需求」視為漂移。過時的 Guideline 會誤導後續所有階段。

**大改版(pivot)**:需求方向根本改變時,不可改寫歷史——Guideline 升 **major** 版;砍掉的 FR 標**棄用(日期+由誰取代)**而非刪除;**FR 編號永不重用**。舊 CHG/ACC 對**它們當時引用的 Guideline 版本**仍然有效(記錄帶日期與版本,舊軌跡照樣讀得通);只有新工作對齊新版本。pivot 本身走 modification-guide——它就是一筆變更,通常高風險。

