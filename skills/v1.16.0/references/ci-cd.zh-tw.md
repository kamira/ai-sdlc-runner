---
name: ci-cd
description: >
  選用:把 ai-sdlc 的文件治理接上自動化檢查,讓「文件即真實」由機器強制而非僅靠自律。依單人或團隊
  需求選用——可放 pipeline(PR/merge 權威門檻)或 pre-commit(本機初步檢查),兩者可併用。想把驗收與
  結構一致性變成門檻時讀本檔。涵蓋治理產物對應門檻、建議 gates、pre-commit 與 pipeline 平台中立範例。
---

# ci-cd(選用)— 把治理流程接上 CI/CD

> 語言 / Language: **繁體中文** · [English](ci-cd.md)

## 用途(選用)

**依單人或團隊需求選用**。若專案有 CI/CD,把 ai-sdlc 的文件治理變成**自動化門檻**,讓「文件即真實」「每次變更留痕」「驗收對齊來源」由機器強制,而非只靠自律。**沒有 pipeline 的專案可略過本檔**,靠 ai-sdlc 流程自律即可。單人專案通常較簡、團隊專案更需要,但兩者都可選用。

## 何時讀

- 團隊專案已有或要導入 CI/CD
- 想把驗收、結構一致性變成 merge / PR 的門檻
- 多人/多 agent 協作,需要機器把關以免有人略過治理

## 治理產物 → 自動化門檻 對應

| ai-sdlc 產物 | CI/CD 對應 |
|--------------|-----------|
| 驗收條件(Guideline §7 / ACC) | 自動化測試;CI 跑測試作為門檻 |
| 變更記錄 CHG | PR 模板必填;PR 描述須連結對應 CHG |
| 結構文件 `docs/structure/` | 結構漂移檢查(見下) |
| 驗收報告 ACC | merge 門檻:無對應且通過的 ACC 不可合併 |

## 建議 gates(由寬到嚴,依團隊需要選用)

1. **測試必綠**:對應驗收條件,最基本。
2. **PR 必連 CHG**:PR 描述要含 `CHG-` 參照(對應「每次變更留痕」)。
3. **結構同步檢查**:若這次改了結構性程式(如 `src/models/**`、schema)卻沒同步 `docs/structure/`,警告或擋下(對應「文件即真實」)。
4. **驗收門檻**:存在對應本次變更、且結論為「通過」的 ACC,才可合併(對應「當場驗收」)。
5. **身分檢查(驗收者 ≠ 實作者)**:比對 ACC 的「驗收者」與 CHG 的「實作者」(或 commit author / agent id),**兩者必須不同**——把「球員不可兼裁判」變成機器可擋。**高風險變更強制此 gate**;低風險可豁免(允許自驗)。

導入時建議**從寬到嚴**:先上「測試必綠 + PR 連 CHG」,團隊習慣後再加結構同步、ACC 與身分檢查門檻,避免一次太嚴卡住流程。

### 依風險分級套用 gates

讀 CHG 的「風險分級」決定要套哪些 gate:**高風險**→全部(含身分檢查、完整 pipeline、多情境);**中**→測試+結構同步+ACC;**低**→測試必綠即可、可走 pre-commit。讓嚴格度與風險匹配,而非一視同仁。

## 兩個檢查點:pre-commit(初步)與 pipeline(完整)

治理門檻可以放在兩個層級,兩者可擇一或併用:

- **pre-commit(本機、快、初步)**:在 commit 前先跑「便宜、秒級」的檢查,把明顯問題擋在進版控之前——例如 lint/format、快速單元測試、`CHG-` 參照檢查、「改了結構性檔卻沒動 docs/structure」的提醒。用 `pre-commit` 框架或 git hook(`.git/hooks/pre-commit`)。**初步、可被繞過(--no-verify),所以不是最終防線。**
- **pipeline(CI、完整、權威)**:在 PR / merge 時跑完整測試、結構同步、ACC 門檻——**不可繞過,是最終防線**。

建議分工:**快而便宜的放 pre-commit 給即時回饋;慢而權威的(完整測試、ACC 門檻)放 pipeline。** 同一條檢查可兩邊都放(pre-commit 給早期提醒、pipeline 強制)。單人專案可只用 pre-commit;團隊建議至少有 pipeline。

### pre-commit 範例(平台中立 pseudo)

```yaml
# 概念:.pre-commit-config.yaml 或 .git/hooks/pre-commit
pre-commit:
  - run: <lint / format>
  - run: <快速單元測試>
  - run: python3 scripts/doc_integrity_check.py --staged   # 結構漂移 + CHG↔ACC 連結,擋住才能 commit
  - check: commit message 或暫存變更含 "CHG-" 參照
```

> **把「靠遵守」變「機器擋」**:`scripts/doc_integrity_check.py --staged` 會在 commit 前檢查「改了結構性程式卻沒同步 docs/structure」與「已實作的 CHG 沒有對應 ACC(驗收懸空)」,不過就讓 commit 失敗。語意內容仍需人/agent 補,但「有沒有同步」由機器把關,不再只靠自律。

## 平台中立範例(pipeline,pseudo)

以下為概念示意,可翻成任何 CI 平台(GitHub Actions / GitLab CI / Jenkins…)的等義設定:

```yaml
on: pull_request
jobs:
  governance:
    steps:
      - run: <跑測試>                      # gate 1:測試必綠
      - check: PR 描述含 "CHG-"             # gate 2:變更留痕
      - check: 若 changed_files 命中 src/models|schema 等結構性路徑,
               則 docs/structure/ 必須也有變更                # gate 3:結構同步
      - check: docs/acceptance 內存在對應本次 CHG 且結論=通過的 ACC  # gate 4:驗收門檻
      - check: 若 CHG 風險=高,ACC 的「驗收者」≠ CHG 的「實作者」     # gate 5:身分檢查
```

GitHub Actions 對應做法舉例:用 `on: pull_request` 觸發;`gate 1` 跑測試步驟;`gate 2/3/4` 用一個腳本讀 PR body 與 `git diff --name-only` 比對路徑、並 grep `docs/acceptance/` 對應檔,任何一項不過就讓該 step 退出非零碼擋下合併。其他平台(GitLab CI 的 `rules` / Jenkins 的 stage)概念相同。

## 與既有流程的關係

CI/CD **不取代治理,而是強制治理被遵守**。ai-sdlc 定義「該產出什麼文件、該怎麼驗收」;本檔把這些變成機器可檢查的門檻。團隊版尤其需要它——人一多,光靠自律不可靠。選用:沒有 pipeline 時,靠 ai-sdlc 與 cross-agent 的流程自律即可。
