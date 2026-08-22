## AI-friendly 結構與範圍檢索(INDEX)

沒有人該讀整份知識庫——那是目錄式思維。檔案**以 INDEX 開頭**;條目為帶錨點的小節,附 `tags/scope`:

```markdown
## INDEX(讀這裡,不是整份檔)
| id | tier | tags/scope | 一句規則 | 狀態 |
|----|------|-----------|----------|------|
| DIR-1 | 使用者確認 | 全分支 · api | 金額一律整數分 | 生效 |
| KN-2 | deep | report | 匯出一律 UTF-8 BOM | 生效(applied 5) |
| KN-3 | shallow | payment | 偏好 dry-run 先行 | 觀察中(seen 2 / applied 1) |
```

檢索規則(進場與派發皆同):讀 INDEX → 載入**全域條目 + tags 與當前 scope 相交的條目**——僅此而已。派發包用同一規則夾帶相符條目(見 handshake 範圍握手層)。

