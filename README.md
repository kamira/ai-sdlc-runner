# ai-sdlc-runner

A governed development agent. It drives an ordinary development flow — PM plans, the lead judges
feasibility, engineers build one small module each, the lead reviews, a panel cross-checks, QA
verifies, the user's feedback returns to PM — and it decides, at every step, whether that step may
proceed on its own or has to stop and ask a person.

It depends on no other company's agent, and it holds no skill, prompt pack, or vendored contract.
The flow and the governance are this repository's own, in two files anyone can read:

| File | What it holds |
| --- | --- |
| [`policy.py`](src/ai_sdlc_runner/policy.py) | the governance: roles and their capabilities, ten gates × three risk grades, the never-automated actions, the review seats and how their verdicts are adjudicated |
| [`graph.py`](src/ai_sdlc_runner/graph.py) | the flow: 23 nodes, one kind of work each, with the module loop, the bounded retry, and the feedback edge back to PM |

Everything else serves those two: [`engine.py`](src/ai_sdlc_runner/engine.py) walks the flow and
enforces the policy, [`workorder.py`](src/ai_sdlc_runner/workorder.py) renders the closed-schema
order each ask is given, and [`cli.py`](src/ai_sdlc_runner/cli.py) connects them to real models.

## Install

```bash
pip install -e ".[test]"
```

Standard library only. PyYAML is optional — `runner.yaml` is read by a small built-in parser when it
is absent.

## Usage

Print the flow, so you can see what will happen before anything does:

```bash
runner flow
```

Print the governance table — every gate at every risk grade, the never-automated actions, and the
review seats:

```bash
runner policy
```

Walk the flow for real. `--risk` grades the change; `--seats` sets how many review seats open;
`--confirm` names a gate you have already approved, and may be repeated:

```bash
runner run --config runner.yaml --risk medium --seats 3 --confirm plan_confirmed
```

## The four rules the runner is built around

**One node, one kind of work.** Building something, verifying your own work, and having someone else
review it are three different kinds of work, so they are three nodes. Opening a pull request and
merging are two. Planning and confirming the plan are two — the second is where a person can still
say no, cheaply.

**Every asking node is its own session.** A session is opened for one ask and closed the moment it
answers. Nothing is carried between asks, and a dispatcher that hands back a session it already
returned is refused. This is deliberate: a model that can see the previous exchange can coast on it,
and a reviewer who has already seen the answer is not a second opinion.

**The question survives the session.** Every ask is written down as `pending` *before* its session
opens, and marked `answered` only after it returns. If the session drops — for the PM, the lead, an
engineer, QA, or a review seat — the exact question is still on disk, and what was already answered
is not asked again.

**Reviews decide.** A single model can be wrong in a way it cannot see, so the panel is several
seats, each asked separately and each blind to the others. Their verdicts are adjudicated, not
averaged: a veto seat cannot be outvoted, a majority is needed to pass, and a tie does not pass.

## The gates

Ten gates, three risk grades each. The rule behind every cell is the same: **a gate stops when
getting it wrong is expensive to undo.** Reviewing a module is cheap to redo, so it never stops the
run; merging is a one-way door, so it asks even on a low-risk change.

`auto` proceeds. `confirm` asks. `halt` stops for a person. `halt_independent` stops for a person
*and* forbids the implementer from being the one who verifies it.

A halt is a pause with a way back, not a wall — `--confirm <gate>` continues past one, and the
approval is recorded in the run report so it can be audited afterwards. Run `runner policy` for the
current table.

Six actions are never automated at any grade, and no confirmation or mode relaxes them: production
deploys, data migrations, hard deletes, moving money, changing secrets or permissions, and
publishing public content. They are checked against what each node says it is about to do, and they
stop the run before the work is dispatched.

## High-risk mode

The review panel has a floor of three seats. A user who needs fewer can turn on high-risk mode and
open one — and the run report records that the floor was bypassed, at what seat count. Bypassing a
safeguard silently is the thing being prevented; bypassing it on the record is a decision someone
made.

## Governance

This repository is developed under its own rules. Every change is written down as a `CHG` record in
[`docs/changes/`](docs/changes) before the work starts, and closed by an `ACC` acceptance record in
[`docs/acceptance/`](docs/acceptance) with evidence. [`tools/ledger_check.py`](tools/ledger_check.py)
runs in CI and fails the build when a record is missing a required field, claims completion without
an acceptance, or drifts from what was actually done.

---

# ai-sdlc-runner(繁體中文)

一個**受治理的開發代理**。它跑一條普通的開發流程——PM 規劃 → 主管判斷可行性與風險 → 工程師各做一個
小模組 → 自我驗證 → 主管 review → 審議席交叉複核 → QA 全面驗證 → 用戶回饋回到 PM——並在每一步判斷:
這一步可以自己走,還是必須停下來問人。

它**不依賴其他公司提供的 agent**,repo 內也**不存放、不讀取任何 skill**。流程與治理都是本專案自有的,
寫在兩個檔案裡:

| 檔案 | 內容 |
| --- | --- |
| [`policy.py`](src/ai_sdlc_runner/policy.py) | 治理:角色與能力、10 個閘門 × 3 個風險等級、永久停點、審議席與裁決規則 |
| [`graph.py`](src/ai_sdlc_runner/graph.py) | 流程:23 個節點,一個節點只做一種工作,含模組迴圈、有界重試、回饋回到 PM 的邊 |

## 用法

```bash
runner flow      # 印出流程
runner policy    # 印出治理表
runner run --config runner.yaml --risk medium --seats 3
```

## 四條核心規則

**一個節點只做一種工作。** 開發、自我驗證、被人 review 是三種工作,所以是三個節點;開 PR 和 merge 是
兩個;規劃和確認方案是兩個——後者是人還能便宜地說「不」的地方。

**每個詢問節點都是獨立 session。** 一次詢問開一個 session,答完立刻關閉;session 之間不帶任何東西,
把用過的 session 再交回來會被拒絕。目的很明確:能看到前一輪問答的模型會偷懶,而已經看過答案的人不算
第二意見。

**問題比 session 活得久。** 每次詢問在 session 開啟**之前**就先落盤成 `pending`,答完才標記
`answered`。session 斷線時——不論斷的是 PM、主管、工程師、QA 還是審議席——原本的問題原封不動留在磁碟
上,已經答過的不會再問一次。

**Review 要能決定事情。** 單一模型可能有它自己看不見的偏差,所以審議席是多席,各自獨立詢問、互相看不
到彼此的答案。他們的判定會被**裁決**而不是平均:有否決權的席次不可被多數推翻,放行需要多數決,平手
不算通過。

## 閘門

10 個閘門 × 3 個風險等級。每一格背後只有一條規則:**出錯難以復原的地方才停**。一個模組的 review 重做
很便宜,所以它永不停止流程;merge 是單向門,所以即使低風險也會問。

`auto` 直接走、`confirm` 詢問、`halt` 停下來等人、`halt_independent` 停下來等人**而且**驗收者不得是
實作者。

停下來是**可以續走的暫停**,不是牆:`--confirm <閘門>` 可以續走,而且該次核可會記進執行報告以供稽核。

六個動作在任何風險等級都不自動、任何確認或模式都不能放寬:上線部署、資料遷移、硬刪除、金流、變更金鑰
或權限、對外發布。它們比對每個節點宣告要做的事,並在派工**之前**停住。

## 高風險模式

審議席預設下限三席。需要更少的使用者可以開啟高風險模式並只開一席——而執行報告會記下「下限被規避,實際
開了幾席」。要避免的是**無聲**繞過安全機制;留下紀錄地繞過,那是有人做的決定。

## 治理

本 repo 以自己的規則開發:每個變更先在 [`docs/changes/`](docs/changes) 開 `CHG`,再由
[`docs/acceptance/`](docs/acceptance) 的 `ACC` 帶證據收尾。
[`tools/ledger_check.py`](tools/ledger_check.py) 在 CI 執行,缺欄位、沒有驗收就宣稱完成、或與實際做的
事漂移,都會讓 build 失敗。
