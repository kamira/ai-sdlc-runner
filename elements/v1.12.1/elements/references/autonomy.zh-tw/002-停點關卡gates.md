## 停點關卡(gates)

流程中幾個會「往前推進」的轉換點,都是潛在停點:

| gate | 位置 |
|------|------|
| `requirement_confirmed` | 需求分析產出 Guideline 後、進結構設計前 |
| `structure_confirmed` | 結構設計產出後、開始實作前 |
| `before_implement` | 修改治理產出 CHG 後、開始改碼前 |
| `acceptance_failed` | 驗收未通過、要進回修迴圈前 |
| `before_merge_or_release` | 驗收通過後、合併 / 發佈 / 交付前 |

