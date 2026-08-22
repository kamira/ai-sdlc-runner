---
name: ai-sdlc-autopilot
description: >
  一支 skill 涵蓋受治理的 AI-SDLC:**治理層**(需求分析、結構設計、修改治理、驗收——
  每個任務先讀文件、可追溯)與**自動駕駛執行層**(把一筆已確認的需求驅動到合併:
  計畫 → 逐 task TDD 施工 → 多席審查面板 → 各道驗證閘 → 驗收 → PR → merge)。
  當使用者要規劃專案或功能、釐清需求、設計架構或資料庫、提出任何修改、詢問結果是否達標、
  或要在治理下端到端自動完成一筆變更時使用。停點由風險分級驅動(低=全自動、中=一次確認閘、
  高/不可逆=必停人)。重要:一旦提出修改或新功能,先走修改治理,不要直接改程式碼。
metadata:
  version: 1.64.0
---

# ai-sdlc-autopilot — 受治理的自動駕駛執行

> 語言 / Language: **繁體中文** · [English](SKILL.md)

**一句話**:ai-sdlc 管帳本與閘門;本 skill 管施工與駕駛——需求進、一筆受治理/已審查/已測試/已合併的變更出,每一步自動落入 ai-sdlc 帳本。

三層:**治理**(ai-sdlc,外部相依、只讀)、**執行**(本 skill references:計畫格式、TDD、task review、除錯)、**驅動**(autopilot-loop 契約 + `assets/autopilot_policy.json` + `scripts/autopilot_runner.py`)。

## 兩層,一支 skill

本 skill 同時是**治理層**與**執行層**:治理層管帳本與閘門(需求分析、結構設計、
修改治理、驗收),執行層管施工與駕駛(計畫格式、TDD、逐 task 審查、runner)。

兩者原本是兩支 skill(`ai-sdlc` 與 `ai-sdlc-autopilot`),同在一個 plugin 裡發佈。
自 v1.18.0 起**合併為一支**——它們本來就必須一起裝、一起用,而分成兩支只多出一組
「誰依賴誰、版本要不要對齊」的協調成本,沒有換到任何隔離上的好處。

**不建平行帳本**:計畫寫在目標專案的 CHG(修改指引段)、review 判定落 ACC 證據欄、
錯誤入 `docs/knowledge/`。若發現自己在寫一個新的 docs 目錄,就是正在漂移。

## 偵測 → 載入


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
| **還沒有帳本**(找不到 `CHG-*.md`) | 新專案從零起手;程式已建置但從未治理;`docs/` 被文件網站/生成產物佔用;要把帳本搬到新落點;字眼:初始化、導入、接進治理、既有專案 | `onboarding`(四態路由 init/adopt/已治理/`docs` 被佔用;落點判準;不覆寫與續跑;存量專案的**治理基準點**——已盤點 ≠ 已驗收) |
| 收到使用者修正指示 / 需求與已知規則衝突 / 需求重複出現 | 「別這樣做」「上次講過」;新需求違反既有 directive;**同樣需求/目的跨 CHG 反覆出現** | `knowledge`(納庫/更新;自主 shallow→deep 模式記錄;衝突→三次確認+告知影響) |
| 存在多個分支 | feature/release/hotfix 並行;需求/驗收分屬不同分支 | `branch-isolation`(只採當前分支來源,不跨分支引用) |
| 有 / 要導入 CI/CD | repo 有 `.github/`、`.gitlab-ci.yml`、`.pre-commit-config.yaml`、Jenkinsfile;或提到 pipeline/hook/門檻 | `ci-cd`(選用) |
| 自主連跑 / 外部程式驅動流程 | agent 要自己連跑多階段、或用 Python 等外部協調器驅動;字眼:自動跑完、自主、無人值守、自動化流程 | `autonomy`(停點契約;查 `scripts/halt_gate.py`) |

**堵漏報(寧可多載不可漏)**:訊號常是隱含的——使用者說「順便也改一下後端」=多 repo+修改;「你來分頭處理」=多 agent;「之前那個專案繼續」=跨 session 接手。**只要疑似命中就先載對應 reference**;載多了成本低,漏掉治理代價高。判不準時,偏向載入。

自動判斷 vs 使用者選擇:**有明示用明示,沒明示用偵測**。覆寫只縮不放安全性——使用者可加嚴(要求更高把關);要放寬高風險把關時應先提醒風險再依其決定。

**執行層(施工/駕駛)另有一組偵測:**


| 情境 | 線索 | 載入 |
|------|------|------|
| 撰寫/驗證可執行計畫 | 任務拆解、約束、介面、「幫我規劃」 | [`references/execution-plan.zh-tw.md`](references/execution-plan.zh-tw.md) |
| 施工一個 task | 實作、寫碼、紅綠、測試先行 | [`references/tdd-loop.zh-tw.md`](references/tdd-loop.zh-tw.md) |
| 某 task 的 diff 要判定 | 審這個 task、判決、規格合規 | [`references/task-review.zh-tw.md`](references/task-review.zh-tw.md) |
| 測試連續失敗 | 同一 task 連續 2+ 次失敗 | [`references/systematic-debugging.zh-tw.md`](references/systematic-debugging.zh-tw.md) |
| 跑整條流程/續作/接 CI | autopilot、端到端跑完、resume、停點策略 | [`references/autopilot-loop.zh-tw.md`](references/autopilot-loop.zh-tw.md) |


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
├── acceptance/ACC-YYYYMMDD-NN.md                   # 每次驗收一份
└── knowledge/                                      # 一開始就建(見 knowledge);「先建」規則前的存量專案由進場握手補建
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
## 迴圈


```
ai-sdlc 握手 → CHG(plan-check 閘)
  → [ 逐 task:TDD 施工 → 單元/build 測試 → 唯讀 task review → 打勾 + commit ]
  → 整支 review → 實際操作驗收(真的跑起來)→ ACC → PR →(依 policy)merge → knowledge 收尾
```

任一時刻中斷都安全:已勾 checkbox 是續作點,live handshake 檔(`docs/worklog/handshake-autopilot.md`)在每個 task 邊界更新。

**task 測試 ≠ 驗收**:逐 task 的 `test:` 是單元/build 級;驗收前 runner 要求一次**操作測試**(計畫的 `### Acceptance operation`——operate/observe/pass,真的跑一次)。程式 CHG 缺它(又無 `docs-only` 標記)會在驗收前停——見 autopilot-loop。

## 停點策略(風險×階段——只准加嚴)


| 風險 | 確認閘 | task review | 操作驗收 | 驗收 | PR | merge |
|------|--------|-------------|----------|------|----|-------|
| 低 | auto | auto | auto(verify-cmd / 人) | auto(自驗) | auto | auto |
| 中 | **confirm**(可預授權) | auto | auto(verify-cmd / 人) | auto | auto | **halt** |
| 高 | **halt** | auto | **halt**(人執行) | **halt**(獨立驗收者) | auto | **halt** |

**中/高風險的確認閘要附設計圖**(v1.21.0)——**不新增停點**,停不停仍由上表決定;新增的是「停下來時要給使用者看什麼」。上表左欄那一格原本交出去的是純散文:動機、影響範圍、代決事項、風險分級。而使用者真正要攔截的「模組接錯邊了」「資料流向不對」,恰好是散文最不擅長表達、也最容易讓人看過就點頭的——**一份看不懂的確認材料,拿到的不是確認,是默許**。所以中/高風險的 CHG 必附 `## 設計圖`(受影響範圍的架構圖 + 本次變更的流程圖,Mermaid 為主、ASCII 亦可),**呈給使用者、依指正改到他確認為止,才往下做**;新專案的結構設計同理(見 structure-design 第 5 步)。使用者可以決定不看:`Diagrams: skipped — <理由>`,**理由空白視同沒宣告**(空白簽名不算簽名),而沒宣告時的預設是畫。低風險與 `Template: lite`/`classic` 免——記帳成本隨風險縮放。plan-check 阻斷(exit 2),但只驗「有沒有給東西看」,**不驗圖畫得對不對**:圖的語意由使用者判斷,不是 lint 的職責;驗 Mermaid 語法要外部 parser,而被測程式一律 stdlib-only。**前瞻適用**(`DIAGRAM_SINCE = (1, 21)`):既有記錄一份都不受影響。

<!-- claim: local-selfcheck-ahead-of-ci -->
**合併前先過本機自主檢查**(v1.22.0)——**排在 CI 閘之前**,且**僅限程式類**。合併前原本只有一道閘(下一段的 CI 全綠),而它有兩個洞:(1) **CI 可能根本跑不起來**,理由與程式無關(額度、帳務、runner 排隊);(2) CI 跑得起來時**它也不是本機**——本機有的東西(開發者的 venv、真實檔案系統、平台特性)CI 不一定有,反過來也是。所以 merge 之前先在本機把這個變更跑過一次:指令的優先序是**操作者的 `--local-gate-cmd` → CHG 的 `### 本機閘` → 專案的慣例載具**(`.github/ci_local.sh`、`scripts/check.sh`、`make check`、`just check`),**四條路都沒有就停下**(exit 3)——合併是單向門,查不到即不准合併(與 CI 閘同向,見 KN-004)。純文件(`Acceptance-operation: n/a`)與 `Template: lite`/`classic` 免——記帳成本隨風險縮放。**信任邊界不變**:`### 本機閘` 的 `cmd` 來自 repo 內容不是操作者打的,**預設不執行**,需 `--trust-chg-commands`(執行前印出原文)——與互動閘同一條線,不為新閘另開後門。逃生口 `--allow-no-local-gate` 會留痕。**前瞻適用**(`LOCAL_GATE_SINCE = (1, 22)`):既有記錄不受影響。

**合併前 CI 必須全數完成且為綠**(v1.7.0)——`pending` 不算綠。查不到狀態同樣停下:合併是單向門,故此閘 fail-closed,與哨兵的 fail-open 相反。專案沒有 CI 要用 `--allow-no-ci` 明示,會留痕。

**永遠停點**(永不自動、硬編碼、任何設定不可放寬):不可逆刪除、金流、生產資料遷移、安全邊界變更。決策順序:永遠停點 → CHG `Autonomy:` 欄(只准加嚴)→ policy 矩陣 → 查無=halt。

## Runner


```
python3 scripts/autopilot_runner.py plan-check --chg <CHG.md>
python3 scripts/autopilot_runner.py run --chg <CHG.md> --repo . \
    [--agent-cmd 'claude -p "$(cat {brief})"'] [--test-cmd 'pytest -q'] [--verify-cmd './run-smoke.sh'] [--dry-run] [--no-commit]
python3 scripts/autopilot_runner.py status --chg <CHG.md>
python3 scripts/autopilot_runner.py sentinels --repo . [--chg <CHG.md>] [--reentry-count N]
python3 scripts/autopilot_runner.py plan|build|review|verify|accept --chg <CHG.md> --repo .
python3 scripts/autopilot_runner.py build --chg <CHG.md> --repo . --agent-cmd '<施工>' --review-cmd '<審查>'
```

迴圈每個階段亦為**獨立角色指令**(也有 slash 指令:`/autopilot-plan`、`-build`、`-review`、`-verify`、`-accept`、`-sentinels`);`run` 是它們的組合。拆成指令**不是治理繞道**——每個角色都走同一 halt policy 與同一帳本,前置條件缺失即 halt(build 需已核准 CHG;accept 需 review + 操作驗收)。見 autopilot-loop「角色拆成獨立指令」。

**針對 agent 寫出來的程式碼的四道閘**(v1.5.0)。`--test-cmd` 全綠只證明「agent 寫的測試沒抓到 agent 寫的錯」——兩邊出自同一個模型,共享同一組盲點。四道閘補這個洞:

- **單元強制**:無 `--test-cmd` 現在會 **halt**(原本靜默略過)。`--allow-untested` 是明示且留痕的逃生口,供純文件 task 使用。**破壞性變更。**
- **變異閘預設開啟**(v1.10.0;`--min-kill-rate` 預設 90):對本 task 變更的檔案種入錯誤,檢查 agent 的測試是否真的會紅。存活變異體逐一列出行號與算子。僅支援 Python——其他語言標為**未涵蓋**,絕不標為通過。`--no-mutation` 是明示且留痕的逃生口;`--mutation` 保留為相容 no-op。**破壞性變更**——測試的「存在」原本就是強制的,而「強度」卻是選配的,這個排序反了。
- **行為規格**(CHG 的 `### Behaviour spec` → `.feature`):使用者故事變成可重跑的斷言。v1.5.0 起前瞻適用,於 verify 階段執行。
- **整支 branch review 不再是 no-op**:真的呼叫審查指令並要求判定行。沒有輸出不算通過。

**performance 已接上**(v1.17.0)——適用於本 repo 的非功能性類別,現在全部真的在跑。這一類我延後過兩次,理由都一樣:*沒有第一個「慢」的實例之前建立基準,只會建出一個沒人看的數字。* 那個理由沒有錯,但它指的其實是一件**可以解掉**的事,而不是「不要做」。

沒人看的原因很具體:在共用的 CI runner 上它會無故轉紅,而**無故轉紅的閘,人會在第一時間關掉它**——那與沒有閘是同一件事。所以量的是**比值**而不是秒數:每一輪都先在同一個行程裡跑一段固定的校準負載,再把每個目標的時間除以它,機器快慢在分子分母上約掉。門檻抓**倍數**(2×)而不是百分比——要抓的是 O(n) → O(n²),不是 10% 的排程雜訊。取七次的中位數,不取平均。

量的對象是**閘本身**,因為閘是逐 task 跑的:慢下來的代價會被乘上 task 數,而「變慢」在這裡的具體傷害不是誰多等了幾秒,是**驗證被放棄**。

這一類有一個別類沒有的風險:其他每一道閘的輸入都是確定的,只有這一道的輸入是時間。所以除了照例的紅燈可達,**綠燈穩定性也寫成常駐斷言**——同一份工作量兩次,不得互判為退步。量到 0 個目標、校準時間四捨五入為 0 秒,兩者都擋:對著什麼都沒量到回報「沒有退步」,又是恆真回報。

**api-contract 與 property-fuzz 已接上**(v1.16.0)——適用於本 repo 的五類非功能性全部真的在跑。兩者當初都因為「要引入新相依」而被延後,結果兩者都是 stdlib 就能解的題。

- **api-contract** 以 `ast` 把這個專案真正承諾的東西抽成快照:公開的頂層函式簽章(被 MCP server 與 hooks 匯入)與 runner 的命令列旗標。它**只擋破壞性**變更:模組或公開函式消失、必填參數消失**或新增**(既有呼叫端會少傳)、旗標消失。新增一律不擋——一個會對擴充課稅的契約檢查,會被關掉。
- **property-fuzz** 打的是吃人寫的文字的那些解析器:CHG 解析、判定行、每一個 `### …` 宣告區塊、四個工具的產物格式。不變式只有一條:**解析器不得拋出未捕捉的例外。** 回空、回 None、回報錯誤都可以;崩潰不行,因為崩潰與正確擋下在退出碼上分不開(KN-003)。

模糊測試帶出一個別類沒有的問題:**它第一次跑就過了。** 0 個失敗與引擎壞掉,看起來完全一樣。所以引擎接受可注入的目標與固定種子,並有一條常駐斷言餵它一個故意會炸的函式,證明紅燈可達。跑 0 次而回報 0 個失敗,一律判為**沒跑過**,絕不判為通過。

**license-compliance 與 build-reproducibility 已接上**(v1.15.0),而且非功能性產物現在是**被判讀**而不只是被數。v1.14.0 交付了分派(哪幾類適用於哪種型態),卻留下 C2 剛在別處補掉的洞:它只驗「指令回 0 + 產物存在」,從不讀內容。一份寫著「12 個 GPL 相依」的報告存在且非空——它會通過。

- **license-compliance** 以 stdlib `importlib.metadata` 取得相依授權(License-Expression → License → Classifier 三段回退),所以查授權本身不必再引入一個相依。**本專案自己缺 LICENSE 即擋**——查別人的授權卻不查自己的,是最容易漏的一格,而本 repo 正好就漏了。開發期相依的 copyleft 或未知授權**指名但不自動擋**:它們不感染散布出去的東西,但得有人決定。
- **build-reproducibility** 同時斷言兩件不同的事:同步是冪等的(跑兩次雜湊一致)**且**已提交的 plugin 複本等於重新建置的結果。前者抓建置不穩定,後者抓建置產物被手改。
- **逐類 `- defer: <理由>`** —— 整段 `n/a` 會把你**已經接上**的類別一起豁免掉。具名延後回報為**未涵蓋**,絕不寫成通過;空的延後視同未宣告。

**非功能性驗證,依專案型態調用**(v1.14.0)。在此之前的每一道閘驗的都是**正確性**;這一塊驗的是快不快、穩不穩、會不會漏——九類:效能、負載壓力、併發競態、資源洩漏、建置可重現、授權合規、API 合約、視覺回歸、屬性/模糊測試。

把九類一律加上是典型的錯誤:**對一個 CLI/library repo 課負載測試的稅,人會把整套關掉**。所以每一類自己宣告 `applies_to`,專案在 `.ai-sdlc/profile.json` 宣告一次自己的型態(可多選),runner 只做交集——它對專案型態不內建任何意見,因為新增一種型態應該是改設定,不是改 runner。

這引入了**第三種狀態**,而把三者分開正是這一塊的全部重點:

| 狀態 | 意思 | 後續動作 |
|---|---|---|
| 通過 | 驗了,而且過了 | 無 |
| **未涵蓋** | 該驗,但這個環境驗不了 | 補環境 |
| **不適用** | 這個專案型態根本不需要 | 永久結論 |

把「不適用」讀成「通過」,與把「未涵蓋」讀成「通過」是同一個錯誤。`Non-functional: n/a` 的豁免**必須帶理由**——否則任何人只要宣稱「我不是後端」,整塊就消失了。未宣告型態時**視為全部適用**:拿不準時倒向多驗。

**委派四類真的跑起來了**(v1.13.0)。它們自 v1.9.0 起就有**位置**——分類表、宣告解析、產物存在性檢查——卻一次也沒跑過。讀了程式碼才知道原因不只是「還沒做」,是**現在做會壞**:`run_gate` 以**退出碼**判生死(mypy 在本 repo 有 72 個發現 → 從第一天就紅),否則就只看產物**存不存在**(一份塞滿錯誤的報告照樣存在且非空)。用退出碼判會恆紅,用存在判等於沒判。

所以判讀的單位是**相對基線的差集**:既有的入基線(每條具名理由),**新增的一律擋**,而且基線**只准往下**——發現消失時會被提示移除該條。指紋不含行號(行號會漂移,規則與檔案不會)。bandit 依 severity × confidence 分級,80 個 LOW 只列出不擋——因為噪音正是讓人把整道閘關掉的原因。覆蓋率是棘輪,不是門檻。基線裡沒有理由的條目一律拒絕載入:豁免要留下署名。

**審查是面板,不是一個人的意見**(v1.12.0)。runner 原本會**印出**「同模型=共享盲點」然後什麼也不做——一句沒人處理的警語,久了就是背景噪音。現在審查依風險分級調用,而且**沿用治理層既有的面板機制**(ai-sdlc `references/review-panel.md`),不另立第二套:

- **座位制,一席一領域**——`conformance`(做的是不是 task 寫下的那件事,逐字對照)、`defect`(會不會壞,而且要能指出觸發條件)、`idiom`(讀起來像不像這個 codebase)。每席**只拿到自己那一列**,整張表屬於 dispatcher。`--seat-cmd conformance=<指令>` 可讓各席指向不同模型;未指定時全席共用一個,runner **會說出來**。
- **風險分級**:低 = 1 席(既有快速路徑,完全不變),中/高 = 3 席。`--review-panel N` 可以往上加,不能降到分級下限以下。
- **信心只降級,絕不平均**——低於 `--confidence-threshold`(預設 80)的判定變成 `cannot-verify`。review-panel 明寫分歧是*調和或升級,絕不平均*:一票有把握的反對,不該被兩個沒去看那個角落的贊成票稀釋。
- **`spec: fail` 是否決**,裁決者不得推翻;**全席無法判定即停下**——「查不出來」不等於「沒問題」(KN-004)。
- **高風險多一個交叉讀階段**:各席先獨立判定(防定錨),再讀彼此的判定並標記同意與否。有分歧就升級交人,runner 不替他們調和。

裁決算術在 runner(no-LLM)內完成。把彙整交給模型,等於讓那個模型的盲點蓋過所有座位,而且又多一層「模型轉述模型」。

<!-- claim: gates-wired-blocks-gate-deletion -->
**兩道守住測試本身的閘**(v1.11.0)。`test_gates_wired.py` 擋的是「拔掉閘門」;同一句話往下一層沒人在看——**讓 build 轉綠最省事的方法,是把那個紅的測試刪掉**。單元閘只問測試指令有沒有回 0,而刪掉那支測試它就回 0 了;變異閘在完全沒有測試時回報的是「未涵蓋」,不是失敗。

- **測試棘輪**:本 task 的 diff 不得淨減少測試函式或斷言數(以 AST 計數,所以註解裡的 `# assert` 與字串裡的 `"assert"` 不會灌水)。刪掉整個測試檔算**完整損失**——否則刪一個函式被擋、刪掉它所在的整個檔案反而過。把三個小測試檔合併成一個**不會**被擋:判的是總量,不是逐檔。語句數另給 10% 容忍帶,抓得住「保留函式外殼、把裡面的斷言刪光」,又不會對一般整理誤報。`--allow-test-reduction` 是明示且留痕的逃生口。
- **不穩定測試偵測**:單元測試轉綠後,在**同一份程式碼**上重跑。跑一次綠不算通過——不穩定的綠燈與恆真的綠燈是同一個失效(KN-001)。`--flaky-runs N`(預設 2,下限 1)設總次數;N=1 等同關閉且會留痕。

閘序維持先擋便宜的:test → 棘輪(AST + git)→ 靜態(AST)→ flaky(重跑測試)→ 變異。

**回修那一輪會拿到上一輪的失敗**(v1.10.0)。閘紅了原本是用**同一份 brief** 重試——施工者從來看不到自己哪裡錯,所以那是重擲不是回修。現在每一輪都把上一輪的失敗**原文**(測試 stderr、靜態發現、存活變異體、review 判定行)帶進下一份 brief,複審也拿到同一份 findings 清單逐項確認。`--max-fix-rounds`(預設 3,下限 1)設上限;最後一輪若有 `--escalate-cmd` 就換,沒有就明講(同模型只換了提示,沒換盲點)。達上限即 halt(exit 3)並列出**每一輪的未解項**,不是只印最後一行。

**驗證器自己也被驗證。** `verifier_integrity.py` 錨定構成檢查裝置的 100 個檔案的 SHA-256,重新錨定必須指名授權的 CHG。`test_gates_wired.py` 以 AST 斷言各道閘仍接在流程上——因為讓閘門失效最省事的方法是把它刪掉,而被刪掉的閘門不會抗議。v1.10.0 起這也涵蓋回饋路徑本身:把它拔掉不會讓任何測試變紅,因為迴圈照跑、輪數照樣,只是每一輪都在重擲。

`--test-cmd` = 逐 task 單元/build 測試;`--verify-cmd` = 末端操作測試(把變更真的跑一次)。無 `--verify-cmd` 時操作驗收階段停(exit 3),交人執行。

<!-- claim: sentinels-two-tier-escape -->
`sentinels` 跑確定性需求確認輪詢,兩層跳脫(A 無法評估→exit 0 基線;B 真 halt→exit 3 升級人);以 `scripts/sentinel_install.py` 掛排程(建 cron/CI **停等人授權**)。治理語意錨定 ai-sdlc `references/autonomy.md`——本層只做 drive。見 autopilot-loop「常態哨兵與排程再進入」。

`--review-cmd` 讓逐 task 審查派給**與施工不同的指令/模型**;未給則回退 `--agent-cmd` 並**明示**(同模型=共享盲點)。各角色模型選擇見 ai-sdlc `agent-hierarchy`。

runner **不含 LLM**:它是狀態機與裁判——施工與審查由你設定的任意 headless agent 指令執行。Exit codes:`0` 完成、`1` 非預期錯誤、`2` 計畫無效、`3` 合法停點(印出原因;cron/CI 據此接線)。

## 存放慣例


一切落入**目標專案**既有的 ai-sdlc 帳本——對應表見 [`docs/ai-sdlc-autopilot/structure/data.md`](../../docs/ai-sdlc-autopilot/structure/data.md)(計畫→CHG、判定→ACC 證據、根因→knowledge、每 task 一個帶 CHG 編號的 commit)。

## NOTICE(出處聲明)


本 skill 的執行方法論——計畫的全域約束/逐 task 介面塊、單 reviewer 雙判定(規格+品質)含合法的「diff 看不出」判定、末端整支 review、TDD/系統化除錯紀律——改寫自 **Superpowers**(Jesse Vincent/obra,MIT License,© 2025 Jesse Vincent)。見 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。差異:產物落 ai-sdlc 帳本(不另立 plans/specs 目錄)、觸發靠 skill 偵測+runner(不靠 harness hook)、停點由治理層風險分級驅動。
