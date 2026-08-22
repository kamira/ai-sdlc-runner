## 協調變更模板(XCHG)

放在權威 `docs/changes/XCHG-YYYYMMDD-NN.md`:

```markdown
# XCHG-YYYYMMDD-NN — <跨 repo 變更標題>

- 權威:<authority repo / 契約位置>
- 涉及 repo:<repoA, repoB, ...>
- 風險分級:高 / 中 / 低
- 契約版本:vN → vN+1(改了什麼契約)
- 各 repo 子變更:repoA → CHG-...;repoB → CHG-...
- 整合驗收:<整合 ACC 連結>
- 狀態:草稿 / 各 repo 實作中 / 整合驗收通過

## 動機 / 整體意圖
...
## 各 repo 影響與順序
<先改誰、後改誰;契約相容性與遷移>
```

