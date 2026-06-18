---
name: cross-repo
description: >
  跨 repo 協調與一致性:當一個需求或變更橫跨多個 git repo(如前端+後端+共用 lib)時,治理文件分散
  在各 repo,容易出現契約不一致、不知哪個 repo 是真相、一邊改了另一邊沒跟上。當一項需求要同時改多個
  repo、多 repo 共用契約(API/資料格式/事件)、或接手跨 repo 系統時讀本檔。涵蓋權威來源 + 本地視圖 +
  指標、跨 repo 協調變更(XCHG)、跨 repo 抗漂移與整合驗收。單人與團隊皆適用。
---

# cross-repo — 跨 repo 協調與一致性

> 語言 / Language: **繁體中文** · [English](cross-repo.md)

## 用途

當一個需求/變更橫跨多個 git repo 時(前端 + 後端 + 共用 lib、microservices…),治理文件分散在各 repo,常見三個問題:**契約不一致**(一邊改了 API、另一邊沒跟)、**不知哪個 repo 是真相**、**變更只做一半**(改了 A repo 忘了 B repo)。本檔定義跨 repo 的單一真相來源、協調變更與一致性檢查。**單人(多個自己的 repo)或團隊都會遇到。**

## 何時讀

- 一項需求/功能需要**同時改多個 repo**
- 多個 repo **共用契約**(REST/GraphQL API、資料格式、事件 schema、共用型別)
- 接手一個由多 repo 組成的系統

## 核心:權威來源 + 本地視圖 + 指標

- **指定一個權威來源(authority)**:某個 repo(或一個專門的治理/契約 repo)持有**跨 repo 契約與共用 Guideline**=單一真相來源。
- 每個參與 repo 保留**本地視圖**(自己那部分的 `docs/`)+ 一個**指向權威的指標**:權威位置(repo/路徑)+ **釘住的版本**(commit / tag / 版本號)。
- **不要在多個 repo 各自複製一份會各自漂移的契約**;契約只有一份在權威,其他 repo 引用其版本。

```
authority-repo/docs/contracts/   ← 單一真相:跨 repo 契約 + 共用 Guideline
repoA/docs/authority.md          ← 指標:authority @ v3 (commit abc123)
repoB/docs/authority.md          ← 指標:authority @ v3 (commit abc123)
```

## 跨 repo 協調變更(XCHG)

- 一個邏輯變更橫跨多 repo → 在權威開一筆**協調變更 `XCHG-YYYYMMDD-NN`**,描述整體意圖、涉及哪些 repo、契約版本如何變。
- 每個 repo 的**本地 CHG** 在「關聯」欄連回該 XCHG;XCHG 列出各 repo 的子 CHG → **雙向追溯**。
- **契約變更順序**:權威先改契約(版本 +1)→ 各消費 repo 各開 CHG 跟進、把本地指標更新到新版本。先動契約、再動消費端,避免消費端對著舊契約改。

## 跨 repo 抗漂移(延伸 doc-integrity)

每個 repo 的文件驗證,額外比對:**本地「權威指標的版本」是否 = 權威目前契約版本**。落後 = 跨 repo 漂移(該 repo 還在用舊契約),須跟進。

**可執行檢查**:本 skill 附 `scripts/cross_repo_check.py`,讀各 repo `docs/authority.md` 的釘住版本 vs 權威 `docs/contracts/VERSION`,不一致即報錯並回傳非零碼(可直接接 pre-commit / CI)。用法:

```bash
python3 scripts/cross_repo_check.py manifest.json
# manifest.json: { "authority": "authority-repo", "repos": ["repoA","repoB"] }
```

可參考 repo 內 `examples/cross-repo/` 範本專案(authority + 兩個消費 repo + XCHG 範例)。

## 跨 repo 驗收(整合驗收)

橫跨多 repo 的變更,**不是各 repo 自己 ACC 通過就算完**。要有一次**整合驗收**:確認跨 repo 一起運作(契約相容、端到端流程通)。XCHG 收尾時連結各 repo 的 ACC + 一份整合 ACC;任一 repo 未過或整合未過 = 整體未過。

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

## 本地指標模板

各參與 repo `docs/authority.md`:

```markdown
# 權威指標
- 權威來源:<authority repo URL / 契約路徑>
- 釘住版本:vN(commit / tag)
- 本 repo 角色:契約提供者 / 消費者
- 最近同步:YYYY-MM-DD
```

## 與既有流程的關係

- 延伸「專案」概念:一個專案可能 = 多個 repo;**XCHG 是跨 repo 版的 CHG**。
- 延伸 doc-integrity:多一條「跨 repo 指標版本一致」檢查。
- 延伸驗收:多一層「整合驗收」跨 repo 把關。
- 與 cross-agent / agent-worklog 相容:不同 repo 可由不同 agent 負責,各自 claim 該 repo 範圍。
