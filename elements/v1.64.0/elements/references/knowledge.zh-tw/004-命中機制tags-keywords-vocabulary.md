## 命中機制(tags + keywords + vocabulary)

檢索需要**契約**,不是語感。兩個軸加一座橋:

- **`tags` = 分類軸**:受控詞彙、小寫英文——INDEX 的主鍵。
- **`keywords` = 命中軸**(選填欄位):自由語言、**任何語言**——使用者原詞、API 名、錯誤字串。作為 INDEX 欄位露出,讓命中在索引層就能完成。
- **`docs/knowledge/vocabulary.json` = 橋與註冊處**:tag → 別名。把任務裡的自由詞正規化成受控 tag,也是「固定詞彙」真正固定的原因——lint 會擋 tag 未註冊的條目(詞彙表解析不了也大聲失敗)。沒有詞彙表=豁免(小專案)。

```json
{
  "_doc": "tag 註冊處+別名橋:key=受控 tag,value=任何語言的別名",
  "payment": ["金流", "付款", "pay", "billing"],
  "report": ["報表", "匯出", "export"]
}
```

**命中程序**:任務側取鍵=分支+結構位置+檔案路徑段+需求名詞 → 過別名表正規化 → 與 INDEX 的 `tags` 交集;另外任務原文對 `keywords` 欄做子串命中。**召回優先於精準**:寧可多中、讀後再篩(條目很小);漏掉規則才是貴的失敗。命中 20+ 條仍然代表 tags 太寬。

**Database-like,但刻意不用資料庫**:檔名=主鍵、schema=DDL、fail-loud lint=constraints、INDEX=物化視圖、vocabulary=維度表。儲存引擎維持純文字,因為 git 可合併、AI 直讀、diff 可審計三者不可退讓——二進位儲存三個全破。(條目上千再由腳本載入**衍生、用後即棄**的查詢快取——永不是真相來源。)

