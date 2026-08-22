## 規則(plan-check 機器強制)

- 必有 **Global Constraints** 節。版本下限、命名規則、精確值都放這——任何約束*每個* task 的東西。把適用的 knowledge 全域條目與 Guideline 約束摺進來,讓 task 簡報自包含。
- 每個 task 必帶 **`interfaces:` 行**(消耗什麼、產出什麼——task 可組合、可審查的關鍵)與 **`test:` 行**(指令或可斷言條件;純文件 task 改寫可重跑的檢核)。
- Task 編號 **T1..Tn 連續**;每個 task 的大小以一次 agent 執行可完成為準(夠小;若一個 task 需要自己的計畫,就是太大——拆)。
- 勾選在 **task 通過 review 的當下**寫入——它們是任何中斷後的續作點(crash-only 紀律)。
- **`### Acceptance operation`** 宣告末端操作測試(`operate`/`observe`/`pass`)。這**不是** task 級 `test:` 行——task 測試是單元/build 級,這一個把整個變更真的跑一次。plan-check 只在缺它時*提示*(非阻斷);**run** 階段的操作驗收才強制(程式 CHG 缺它又無 `docs-only` 標記,會在驗收前停——見 autopilot-loop)。
<!-- claim: local-gate-before-merge-code-bearing -->
- **`### 本機閘`**(或 `## 本機閘` / `Local gate`):**程式類**變更在 **merge 之前**必須在本機跑過一次自主檢查(Skill ≥ v1.22,前瞻適用)。格式:`- cmd: <指令>` / `- pass: <通過標準>`。沒宣告時 runner 會依序找專案的慣例載具(`.github/ci_local.sh`、`scripts/check.sh`、`make check`、`just check`);**四條路都沒有就停下**(exit 3)——合併是單向門,查不到即不准合併。純文件(`Acceptance-operation: n/a`)與 `Template: lite`/`classic` 免。**宣告的 `cmd` 預設不執行**:那是 repo 內容不是操作者打的,需 `--trust-chg-commands` 或改用 `--local-gate-cmd`(見 autopilot-loop「信任邊界」)。
- **`## 設計圖`**(或 `### 設計圖` / `Design diagrams`):**中/高風險**變更必附,且**阻斷**——缺它 plan-check 直接 exit 2,計畫不開跑。裡面放受影響範圍的架構圖與本次變更的流程圖,Mermaid 為主、ASCII 亦可;機器只驗「節存在且至少有一個圍欄區塊」,**不驗圖畫得對不對**——那是使用者在確認閘判斷的事(見 modification-guide 第 6 步)。使用者決定不看時,表頭寫 `Diagrams: skipped — <理由>`;**理由空白視同沒宣告**。低風險與 `Template: lite`/`classic` 一律免。**前瞻適用**:只對宣告 `Skill: ai-sdlc-autopilot v1.21` 起的記錄生效,既有 CHG 一份都不受影響。

