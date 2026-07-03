---
name: handshake
description: >
  進場握手協定:每個 agent / session / 換手在動手前,先做一次「握手」——按固定順序讀既有 docs、
  抓出重點、並回述確認理解,才能安全接手。當你剛進場、接手既有專案、或跨 session/跨 agent 交接時
  讀本檔。定義讀什麼、順序、重點、以及進場回述(ack)格式。是 Session 啟動檢查的具體化。
---

# handshake — 進場握手協定

> 語言 / Language: **繁體中文** · [English](handshake.md)

## 用途

任何 agent 一進場(新 session、接手、換手)都先做「握手」:**按固定順序讀既有文件 → 抓重點 → 回述確認**,再開始工作。目的是讓交接可稽核、避免「沒讀就動手」造成的漂移與誤解。這是 Session 啟動檢查的可執行版。

## 從哪讀(固定順序)

1. **當前分支與 working tree**:先確認在哪個 branch(見 branch-isolation),並跑 `git status`——記下未提交變更,留待步驟 5 對帳;後續只引用該分支的需求/驗收。**session 中途切換分支視同重新進場:重做本握手。** **沒有 git?** commit 錨定、commit 掃描、`--commits-since` 均不適用——在 ack 中聲明降級模式;CHG 步驟勾選+worklog 成為唯一中斷標記,對帳改為人工(檔案 vs CHG 步驟)。強烈建議先 `git init` 再做任何事。
2. **`docs/ai-guideline.md`**:現行 Guideline——目標、範圍、現行**版本號**、待確認項。**skill 版本自檢**:比對近期 CHG/ACC 的 `Skill:` 版本與你執行中的 skill 版本——記錄比你的 skill 新,代表**你過舊:先升級再工作**(舊 skill 會靜默漏掉新規則);記錄較舊沒關係(新規則只往後適用,見 doc-integrity)。
3. **`docs/knowledge/`——讀 INDEX,不是整份**:先讀索引,只載入**全域條目 + tags 與當前 scope 相交的條目**(directive、deep/shallow 模式記錄、已知錯誤——見 knowledge)。將套用的 deep 記錄要列進 ack。
4. **`docs/coordination.md`**:編制/claim——我的角色、鎖定範圍、讀寫權限、進行中的他人工作。
5. **`docs/changes/` + `docs/acceptance/`**:有無未收尾(CHG 未驗收 / 缺 ACC);先補再開新。**working-tree 對帳**:步驟 1 記下的每筆未提交變更,都要能對應到某份 CHG 的修改步驟(或 worklog 條目);對不上的變更代表被中斷或未經治理的改動——視為漂移處理(見 doc-integrity),先解決再開新工作。**commit 歷史也要掃**:從上一個治理錨點(最新 ACC 的 Commit 欄,或最後一個引用 CHG 的 commit)到 HEAD,每個 commit message 都應引用某個 CHG 編號(見 modification-guide「commit 粒度」);沒引用任何 CHG 的 commit 就是未治理工作——同樣按漂移處理(squash merge 工作流的 trunk 以 squash commit 為粒度掃描——見 modification-guide「PR / squash / rebase」)。機器輔助:`scripts/doc_integrity_check.py --commits-since <錨點>`。
6. **`docs/structure/`**:現況結構,判斷是否與程式漂移(見 doc-integrity)。

## 重點(務必抓到)

- **當前分支** 與其範圍(不可引用其他分支需求)。
- **現行 Guideline 版本** 與待確認項。
- **我的角色 / 讀寫權限**(role_refs、tools allowlist)。
- **已知錯誤與修正指示**(knowledge,高權重)。
- **未收尾階段**(懸空的驗收)。
- **working-tree 狀態**(未提交變更已對應到 CHG,或標記為漂移)。
- **進行中的 claim**(避免撞車;停滯 claim → 見 cross-agent 接管規則)。

## 回述確認(handshake ack — 動手前必做)

進場讀完後,**先用幾行回述你理解的狀態,再動手**:

```
[handshake] 分支:<branch> | 角色:<role>(RW:<scope>)
worktree:<乾淨 / 有未提交 → 對應 CHG-… / 對不上 → 漂移>;錨點後 commits:<全有治理 / N 筆未治理>
現行 Guideline:v<x>;未收尾:<CHG-… 待驗收 / 無>
已知須遵守(knowledge):<重點條目 / 無>
我接下來要做:<一句話>;停點:<依 autonomy,此關卡 auto/halt>
```

回述能讓人/上層在你動手前攔截誤解;跨 agent 時,這也是「我已正確接手」的憑證。

## 分層握手:完整 vs 範圍(subagent)

什麼都讀撐不起規模,被派發的 subagent 也不需要全貌。分兩層:

**完整握手**——單人進場、orchestrator / 主 agent、接手整個專案、以及**沒有派發者的對等並行 agent**(沒人替你組包 → 完整義務自己扛):讀上方完整清單。

**範圍握手**——**被派發的 subagent**。其情境由四鍵決定:**branch + 結構位置(模組)+ 需求(其任務對應的 FR/CHG 切片)+ 位置(鎖定檔案範圍)**。

- **讀**:主 agent 從全貌切出的**派發包**(任務、鎖定範圍、讀寫權限、相關契約/介面節錄、相關結構文件節錄、全域或標記本範圍的 knowledge 條目)+ 自己範圍的結構文件與 worklog。
- **不讀**:其他分支;其他模組的 claim / worklog / 握手。分支從派發繼承——不得引用其他分支來源。
- **全域 knowledge 穿透範圍**:標「全分支/全域」的 directive 每一層都必讀——唯一跨範圍的東西。
- **scoped ack 回給主 agent**(不廣播):`[handshake:scoped] 分支 | 結構位置 | 需求 | 鎖定位置 | 下一步:<一句話>`。
- **主 agent 審查**:只有它有全貌——派發前組包;收到 ack 後比對**四鍵是否與派發一致**,錯位在動手前攔下。跨範圍一致性永遠是主 agent 的事(影響分析、整合驗收)。subagent 發現超出範圍的相依 → **上報**,不得自行橫向讀取或擴權(見 agent-hierarchy)。

**代價要說清楚**:範圍握手的 subagent 抓不到派發包漏掉的東西。補償控制:主 agent 的影響分析(CHG)、並行的整合驗收、V1 較廣視野的驗收。這個取捨是刻意的——便宜、並行、有邊界的工人 + 一個負全責的全貌審查者。

## Session 中重新對齊(mini-handshake)

完整握手在進場時做——但長 session 的 context 會被壓縮,「以文件為準」只有在你真的重讀文件時才成立。重讀 Guideline + 進行中的 CHG(有 directive 在身時加讀 knowledge),並發兩行 mini-ack:

```
[re-sync] CHG-…:步驟 <n>/<m> 完成;分支 <b>;下一步:<一句話>
重新確認的約束:<knowledge / guideline 重點 / 無>
```

觸發點:**每個 autonomy 關卡**;**開始驗收前**;**察覺壓縮跡象時**(想不起先前某個決策的細節——別憑印象猜,重讀);長 session 定期(建議約每 20 輪)。

## 與既有流程的關係

- 具體化 Session 啟動檢查;讀取項對應 knowledge / branch-isolation / doc-integrity / coordination / autonomy。
- 機器輔助:用 `scripts/role_loadout.py` 取得該角色要載的 references;用 `scripts/doc_integrity_check.py` 掃未收尾與漂移。
- 讀到未收尾/漂移/衝突 → 依對應 reference 先處理,再開始新需求。
