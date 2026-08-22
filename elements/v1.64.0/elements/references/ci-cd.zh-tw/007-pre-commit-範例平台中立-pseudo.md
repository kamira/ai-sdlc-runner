### pre-commit 範例(平台中立 pseudo)

```yaml
# 概念:.pre-commit-config.yaml 或 .git/hooks/pre-commit
pre-commit:
  - run: <lint / format>
  - run: <快速單元測試>
  - run: python3 scripts/doc_integrity_check.py --staged   # 結構漂移 + CHG↔ACC 連結,擋住才能 commit  <!-- claim: doc-integrity-staged-blocks-commit -->
  - check: commit message 或暫存變更含 "CHG-" 參照
```

> **把「靠遵守」變「機器擋」**:`scripts/doc_integrity_check.py --staged` 會在 commit 前檢查「改了結構性程式卻沒同步 docs/structure」與「已實作的 CHG 沒有對應 ACC(驗收懸空)」,不過就讓 commit 失敗。語意內容仍需人/agent 補,但「有沒有同步」由機器把關,不再只靠自律。

