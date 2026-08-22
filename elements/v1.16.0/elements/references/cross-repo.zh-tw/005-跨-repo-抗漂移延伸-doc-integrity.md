## 跨 repo 抗漂移(延伸 doc-integrity)

每個 repo 的文件驗證,額外比對:**本地「權威指標的版本」是否 = 權威目前契約版本**。落後 = 跨 repo 漂移(該 repo 還在用舊契約),須跟進。

**可執行檢查**:本 skill 附 `scripts/cross_repo_check.py`,讀各 repo `docs/authority.md` 的釘住版本 vs 權威 `docs/contracts/VERSION`,不一致即報錯並回傳非零碼(可直接接 pre-commit / CI)。用法:

```bash
python3 scripts/cross_repo_check.py manifest.json
# manifest.json: { "authority": "authority-repo", "repos": ["repoA","repoB"] }
```

可參考 repo 內 `examples/ai-sdlc/cross-repo/` 範本專案(authority + 兩個消費 repo + XCHG 範例)。

