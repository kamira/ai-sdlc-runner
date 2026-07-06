---
name: ai-sdlc
description: >
  AI 開發治理流程套件:把開發拆成需求分析、結構設計、修改治理、驗收四個階段,並用文件貫穿,
  讓每次 AI 工作都先讀文件再動手,維持一致與可追溯。當使用者要規劃新專案或新功能、釐清需求、
  設計系統架構或資料庫、提出任何修改或新增功能、或要驗收成果是否達標時,務必使用本 skill 依
  階段流程進行,並讀取 references 內對應階段的指引。涵蓋:產出 AI Guideline、目錄/邏輯/設計/
  資料四種結構、變更記錄與影響分析、驗收報告與未通過回修迴圈。特別注意:使用者一旦提出「修改」
  或「新功能」,必須先走修改治理(modification-guide)而非直接改程式碼。Use this whenever
  planning, designing, modifying, or verifying software so the work stays documented and traceable.
metadata:
  version: 1.16.0
---

# ai-sdlc — AI 開發治理流程

> 語言 / Language: **繁體中文** · [English](SKILL.md)

這套 skill 讓 AI 協助開發時有一致流程可循。核心理念:**先把需求、結構、變更、驗收都記錄成文件,AI 後續工作時讀這些文件當作依據**,而不是每次從零猜測。動手前先讀這裡,判斷「現在該用哪個階段」,再去讀 `references/` 內對應的詳細指引。

**一套涵蓋單人到團隊**:預設以單人/單一 agent 運作;**偵測到協作情境(多 agent、跨 session 交接、多 repo)就自動升級到團隊模式**,載入對應協作 reference。「團隊」不限於人——**可以是 AI agent 團隊**(不同執行個體 / context),靠 `docs/` 協作。不需要選版本,同一個 skill 自適應。**平台中立**:全套只是 markdown + Python 腳本——任何能讀檔、能跑腳本的 AI agent 都能照著走;平台專屬的工具名(如 `Agent` 派生工具)對應到你框架的等效機制即可。

## 偵測即載入(自主偵測,使用者可選擇/覆寫)

**預設自主偵測:偵測到下列情境就主動載入對應 reference,不必等使用者點名。但使用者可明確選擇或覆寫——以使用者明示為準**(例如「強制用團隊模式」「這次不要 CI/CD」「先別管 cross-repo」「自驗就好」);使用者沒指定時才走自動判斷。

| 情境 | 偵測訊號(線索;命中任一就算) | 主動載入 |
|------|--------------------------------|----------|
| 多 repo / 共用契約 | 出現多個 repo 路徑/URL;提到前端+後端、microservice、SDK+server、monorepo 多 package;改到 API/schema/event/共用型別/protobuf;字眼:跨 repo、契約、上下游、串接 | `cross-repo`(+ `scripts/cross_repo_check.py`) |
| 並行 / 跨 session 交接 | 多個 agent 同時動;接手他人/前一 session 的專案;字眼:接手、交接、換手、續做、同時、並行、分頭 | `cross-agent` |
| 派子代理 / 多 agent 分工 | 你打算開 subagent;任務大到要拆給多個執行單位;字眼:分派、子代理、拆任務、分工、orchestrate | `agent-worklog` + `agent-hierarchy` |
| 修改 / 新功能(對既有系統) | 對已存在的功能/檔案/資料表要調整、修正、擴充、重構、改名、刪除;字眼:改、加、調整、重構、優化、修 bug、換掉 | `modification-guide`(**強制**) |
| 要驗收 / 確認達標 | 「做完了/對嗎/驗一下/檢查/測測看」;一項變更剛實作完 | `acceptance-verification`;**高風險 → `independent-acceptance`** |
| 中/高風險變更決策 | CHG 判為中或高;分級有爭議;規則多到單 agent 吃不下 | `review-panel`(依領域開席;高=全席、中=能 spawn 時**至少五席**;兩階段交叉驗證;不能 spawn 就序列自審) |
| 進場接手 / 跨 session | 每次新 session 開始、或接手既有 `docs/` 專案 | `handshake`(進場握手:讀 docs+knowledge+分支+working tree、回述確認;被派發的 subagent 走範圍層)+ `doc-integrity` |
| 收到使用者修正指示 / 需求與已知規則衝突 / 需求重複出現 | 「別這樣做」「上次講過」;新需求違反既有 directive;**同樣需求/目的跨 CHG 反覆出現** | `knowledge`(納庫/更新;自主 shallow→deep 模式記錄;衝突→三次確認+告知影響) |
| 存在多個分支 | feature/release/hotfix 並行;需求/驗收分屬不同分支 | `branch-isolation`(只採當前分支來源,不跨分支引用) |
| 有 / 要導入 CI/CD | repo 有 `.github/`、`.gitlab-ci.yml`、`.pre-commit-config.yaml`、Jenkinsfile;或提到 pipeline/hook/門檻 | `ci-cd`(選用) |
| 自主連跑 / 外部程式驅動流程 | agent 要自己連跑多階段、或用 Python 等外部協調器驅動;字眼:自動跑完、自主、無人值守、自動化流程 | `autonomy`(停點契約;查 `scripts/halt_gate.py`) |

**堵漏報(寧可多載不可漏)**:訊號常是隱含的——使用者說「順便也改一下後端」=多 repo+修改;「你來分頭處理」=多 agent;「之前那個專案繼續」=跨 session 接手。**只要疑似命中就先載對應 reference**;載多了成本低,漏掉治理代價高。判不準時,偏向載入。

自動判斷 vs 使用者選擇:**有明示用明示,沒明示用偵測**。覆寫只縮不放安全性——使用者可加嚴(要求更高把關);要放寬高風險把關時應先提醒風險再依其決定。

## 為什麼需要

AI 協助開發最大的問題是「失憶」與「漂移」:每次對話缺乏先前決策脈絡,容易做出與既有架構衝突的修改。本流程把每階段產出固定成文件(AI Guideline、結構文件、變更記錄、驗收報告),讓任何一次任務都能先讀文件、再動手。

## 四個階段與對應指引

```
 [需求/新功能]
      |
      v
 需求分析 --> 結構設計 --> 實作 --> 驗收
 (Guideline)  (四種結構)            |
                            +-------+-------+
                          通過           未通過
                            |              |
                            v              v
                          完成         修改治理
                                  (修改指引+記錄+結構同步)
                                          |
                                          v
                                重新實作 --> 重新驗收(回到驗收)

 另一入口:使用者隨時提出「修改 / 新功能」 --> 強制走修改治理 --> 實作 --> 驗收
```

| 階段 | 何時使用 | 詳細指引 | 主要產出 |
|------|----------|----------|----------|
| 1. 需求分析 | 新專案/新需求,需釐清做什麼 | [`references/requirement-analysis.zh-tw.md`](references/requirement-analysis.zh-tw.md) | `docs/ai-guideline.md` |
| 2. 結構設計 | Guideline 確立,要訂系統結構 | [`references/structure-design.zh-tw.md`](references/structure-design.zh-tw.md) | `docs/structure/*.md` |
| 3. 修改治理 | 提出修改或新功能時(**必走**) | [`references/modification-guide.zh-tw.md`](references/modification-guide.zh-tw.md) | `docs/changes/*.md` + 更新結構 |
| 4. 驗收 | 實作/修改完成,確認是否達標 | [`references/acceptance-verification.zh-tw.md`](references/acceptance-verification.zh-tw.md) | `docs/acceptance/*.md` |

跨階段的兩份(隨時可用):

| 面向 | 何時使用 | 詳細指引 |
|------|----------|----------|
| 文檔抗漂移與驗證 | 確認既有文件仍可信、變更收尾、進場接手時(單人也需要) | [`references/doc-integrity.zh-tw.md`](references/doc-integrity.zh-tw.md) |
| 子代理工作日誌 + 錯誤知識庫 | 你要派子代理、或被派執行任務前(單人派 subagent 也適用) | [`references/agent-worklog.zh-tw.md`](references/agent-worklog.zh-tw.md) |
| 代理編制與階層 | 任務由多個 agent 分工、或某 agent 要再派子 agent(編號+固定範圍+不越權;遞迴視平台而定) | [`references/agent-hierarchy.zh-tw.md`](references/agent-hierarchy.zh-tw.md) |
| 跨 repo 協調與一致性 | 一個需求/變更橫跨多個 git repo、或多 repo 共用契約時 | [`references/cross-repo.zh-tw.md`](references/cross-repo.zh-tw.md) |
| CI/CD 整合(**選用**) | 依需求,把驗收與結構一致性自動化成 pre-commit 或 pipeline 門檻 | [`references/ci-cd.zh-tw.md`](references/ci-cd.zh-tw.md) |

依當前任務屬於哪個階段,才去讀對應的 reference,避免一次載入過多無關內容。英文版為各檔的 `*.md`、本檔英文版為 SKILL.md。

> **多人/多 agent 團隊**:團隊協作(交接、並行、獨立驗收、角色與讀寫權限)已**內含於本 skill**——偵測到協作情境就自動載入 `cross-agent` / `independent-acceptance` / `agent-hierarchy`。不需另裝其他 skill。
>
> **跨專案**:同時涉及多個專案時,Guideline / CHG / ACC / 結構文件都要在標頭註明所屬「專案」,變更與驗收編號建議帶專案前綴,避免跨專案張冠李戴。

## Session 啟動檢查(跨 session 累加開發必做)

**每次進場、動任何新需求之前,先掃既有文件確認沒有「斷在半路」的階段:**

1. 讀 `docs/changes/` 最新的 CHG:若有狀態不是「已驗收」者,代表上一個 session 的變更只做到一半。(狀態「暫停」是合法 WIP:列出來、有意識地恢復或收掉,不當作壞掉。)
2. 比對 `docs/acceptance/`:若某個 CHG 沒有對應的 ACC 驗收報告,代表驗收被交棒卻沒人接。
3. 檢查 working tree(`git status`):每筆未提交變更都要能對應到某份 CHG 的修改步驟;對不上的變更代表被中斷或未經治理的工作——依 handshake / doc-integrity 對帳處理。
4. **先把這些未收尾項補完(補驗收 / 對帳 working tree),再開始新需求。**

為什麼:跨 session 開發最常見的破口是「修改流程把驗收當下一步交棒,但下一個 session 來的是新功能、不是驗收」,於是驗收永遠懸著。進場先檢查,能讓「修改→驗收」的迴圈在跨 session 也自動接上。

## 強制規則:修改一定先治理

**只要使用者在一個 session 提出「修改」或「新功能」,必須先讀並依循 `references/modification-guide.zh-tw.md`,不可直接改程式碼。** 任何變更都可能牽動既有結構與先前決策;跳過治理會造成架構漂移與記錄缺漏。修改治理有兩個入口:(1) 使用者主動提出,(2) 驗收未通過交回修正——兩者都走「修改治理 → 重新實作 → 重新驗收」,讓迴圈鎖死。

**收尾即驗收**:一次變更的實作完成後,**在同一輪就接著做 acceptance-verification 產出 ACC**,不可只把狀態標成「待驗收」就結束——跨 session 沒有人會接棒。

## 單人快速路徑(solo + 低風險的預設)

輕量是**預設**,不是要開口求的優待。單人+白名單內低風險(文案/註解、樣式、純文件、有測試的內部重構)= **CHG-lite + 內嵌自驗**(見 modification-guide),確認閘可用**預授權**跳過(directive 要窄;AI 發現同類重複確認時主動建議)。永不關閉的:commit 錨定、一行可重跑證據、lint、闖禍規則(lite 變更被抓到弄壞東西 → 補完整 CHG+該類預授權自動失效)。重型機制——完整模板、審議會、獨立驗收——依風險啟動:錯得起的地方輕,錯不起的地方重。

## 文件存放慣例

產出文件放在**目標專案**的 `docs/` 下(非本 skill):

```
目標專案/docs/
├── ai-guideline.md          # 需求分析產出
├── structure/{directory,logical,design,data}.md   # 結構設計產出
├── changes/CHG-YYYYMMDD-NN.md                      # 每次變更一份
└── acceptance/ACC-YYYYMMDD-NN.md                   # 每次驗收一份
```

若目標專案已有文件慣例,以該專案為準,並在 AI Guideline 註明實際路徑。

**入口錨點(root 層、任何 AI)**:進入點放在 **repo root,不放 `docs/` 底下**——root 是任何廠牌的 agent 第一眼掃的地方;`docs/` 是庫房,不是門。第一次建立 `docs/` 時,同時在 root 建 **`AGENTS.md`**(現存最接近跨廠商慣例的檔名),數秒可掃完:進入點是什麼、必讀是什麼、不可協商的是什麼:

```markdown
# AGENTS.md — AI entry point(任何 agent、任何廠商)
1. 動任何東西之前必做:ai-sdlc 進場握手——
   docs/ai-guideline.md → docs/knowledge/ INDEX → 未收尾 CHG / 分支狀態。
2. 治理文件在 docs/(changes/ acceptance/ structure/ knowledge/)。
3. 不可協商:修改先治理(CHG);每個 commit message 帶 CHG 編號;
   實作前先向使用者確認。
```

套件內的平台中立還不夠——**進入點必須讓不同 AI 都找得到**。對每個存在的工具專屬檔(`CLAUDE.md`、`GEMINI.md`、`.cursorrules`、`.github/copilot-instructions.md`⋯)一律放**兩行 stub 指向 `AGENTS.md`**;stub 永不承載自己的內容(複本必分岔)。lint 雙向強制:治理專案(存在 `docs/changes/`)必有 root 入口;既有 stub 必須仍指向。

**時間慣例(UTC+0)**:治理文件中的一切時間戳——CHG/ACC 編號與檔名的日期、標頭日期、worklog 時刻、claim/租約時間——一律 **UTC+0**,寫時間就標明(如 `2026-07-02 09:30 (UTC+0)`)。租約逾期與「同一天」序號都以 UTC+0 時鐘判定,跨時區團隊共用一個鐘。

## 使用原則

1. **先讀後做**:動手前先讀對應階段指引與既有文件。
2. **文件即真實**:結構變了就同步更新結構文件,不能只改程式。
3. **每次變更留痕**:修改一定在 `docs/changes/` 留記錄,寫清楚動機與取捨。
4. **驗收對齊來源**:驗收標準來自 Guideline 與該次修改指引,不憑空發明。
5. **不倚賴記憶,以文件為準**:長對話的 context 可能被壓縮而遺失或扭曲早期決策。**不要單憑印象**——每次動手前,以 `docs/`(Guideline、結構、CHG、ACC)既有文件重新確認既有約束與決策;當記憶與文件不一致時,以文件為準。這讓壓縮、跨 session、換手都不會造成漂移。重讀有明確觸發點、不是靠自覺:每個 autonomy 關卡、開始驗收前、察覺壓縮跡象時、長 session 定期——重讀 Guideline + 進行中 CHG 並發 mini-ack(見 handshake「session 中重新對齊」)。
6. **推不出的先問,不代決**:凡從文件與使用者指示推導不出的抉擇——做到一半冒出的新需求、範圍外相依、規格空白、兩可的裁決——列選項+建議後**問使用者**,不得自行代決再事後告知。僅「低風險且可逆的實作細節」可先做,且要在 CHG 標「代決」,於確認閘供追認(見 modification-guide)。
能派發時,問題**由代問者(A1)轉達**——主決策 agent 不參與問答、只讀產出的企劃(見 requirement-analysis「代問模式」);核准仍直達使用者。
7. **把每個動作當作最後一個**:session 可能在任何一步之後結束——動手前意圖先落盤、做完立刻記結果(一步一落盤;見 handshake「最後一次行為紀律」)。守住這條,正常結束與 crash 留下的狀態完全相同,中斷恢復就不是急救程序——只是普通的進場。
