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
| [`graph.py`](src/ai_sdlc_runner/graph.py) | the flow: 24 nodes, one kind of work each, with the module loop, the bounded retry, and the feedback edge back to PM |

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

Set how much review this project wants, and whether the floor may be crossed:

```bash
runner settings
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

Point the seats at different commands with `--seat-model` and the review is genuinely cross-model.
Leave it out and the run **says so** — three seats answered by one backend are independent of each
other's context, not of that model's blind spots, and a report that does not distinguish those is
worse than no report.

## The gates

10 gates, three risk grades each. The rule behind every cell is the same: **a gate stops when
getting it wrong is expensive to undo.** Reviewing a module is cheap to redo, so it never stops the
run; merging is a one-way door, so it asks even on a low-risk change.

`auto` proceeds. `confirm` asks. `halt` stops for a person. `halt_independent` stops for a person
*and* forbids the implementer from being the one who verifies it.

A halt is a pause with a way back, not a wall — `--confirm <gate>` continues past one, and the
approval is recorded in the run report so it can be audited afterwards. Run `runner policy` for the
current table.

Six actions are never automated at any grade: production deploys, data migrations, hard deletes,
moving money, changing secrets or permissions, and publishing public content. Nothing is checked
against them by guessing — a run says what each node will do, and it is read in four places, each
able only to **add** a stop:

1. **the node's brief** — every field of it. A work order whose instructions say "wipe the users
   table" stops, whatever is declared beside it;
2. **the targets** an operation names — `kubectl apply -f prod/`, `secrets/key.pem`. These are facts
   rather than claims, so they overrule a declaration that says otherwise. A target the runner does
   **not recognise** is a third case, and it is not the safe one: it stops by default. What counts
   as recognised is small on purpose — a plain repo path, read-only version control, and the
   commands you vouch for in `runner settings`. A command whose name says nothing about what it does
   (`python`, `sh`, `rm`, `curl`) cannot be vouched for at all, and vouching covers the tool rather
   than the command line;
3. **the declaration** — every operation says which of the six kinds it is, or `ordinary`. An
   operation that declares nothing is refused, not assumed safe;
4. **the description**, against word lists. The weakest layer by far, and both of its numbers are
   measured: it catches 6 of 18 known attempts and falsely stops 0 of 46 ordinary engineering
   briefs. Never trusted alone.

All of it happens before the work is dispatched. An operation nothing could confirm — `ordinary`,
with no targets or with unrecognised ones — rests on the plan's word; it stops by default, and if
allowed through the run report says so under `unverified:`.

**Resuming.** `runner run --resume --ask-journal DIR` continues an interrupted run without re-asking
what was already answered.

## High-risk mode

The review panel has a floor of 3 seats. A user who needs fewer can turn on high-risk mode and
open one — and the run report records that the floor was bypassed, at what seat count. Bypassing a
safeguard silently is the thing being prevented; bypassing it on the record is a decision someone
made.

Both live in `runner settings` — a terminal screen, curses with a numbered fallback — and persist to
`config/settings.json`. `runner settings --show` prints them without opening a menu, so the bypass
is visible to somebody reading a log rather than sitting at a terminal. A flag wins for a single run
in **both** directions: `--high-risk-mode` turns it on, `--no-high-risk-mode` declines a saved one.

Settings can lower the seat floor and can do nothing else — gates, the never-automated actions and
the adjudication rule are in `policy.py` and take no input. A key the runner does not read is
refused rather than ignored, and a corrupt settings file is an error rather than a silent default:
a typo must not be indistinguishable from turning a safeguard off.

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
| [`graph.py`](src/ai_sdlc_runner/graph.py) | 流程:24 個節點,一個節點只做一種工作,含模組迴圈、有界重試、回饋回到 PM 的邊 |

## 用法

```bash
runner flow      # 印出流程
runner policy    # 印出治理表
runner settings  # 設定審議席數與高風險模式
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

六個動作在任何風險等級都不自動:上線部署、資料遷移、硬刪除、金流、變更金鑰或權限、對外發布。判斷不靠
猜:執行計畫必須說明每個節點要做什麼,而這件事會在四個地方被讀,每一層都**只能加停、不能解停**:

1. **節點自己的工作說明**——工單裡寫「wipe the users table」就停,旁邊申報成什麼都一樣;
2. **operation 申報的 targets**(`kubectl apply -f prod/`、`secrets/key.pem`)——這些是事實而非說法,
   所以可以推翻申報;
3. **申報本身**——每個 operation 必須說自己是六類之一或 `ordinary`;什麼都不申報會被拒絕,不會被當成安全;
4. **描述文字**比對字詞表——最弱的一層,兩個數字都實測並釘在測試裡:18 句已知繞過擋下 6 句,
   46 句正常開發任務誤擋 0 句。絕不單獨採信。

以上全部在派工**之前**發生。申報為 `ordinary` 又沒指定 targets 的 operation 等於靠計畫的說法,執行報告
會在 `unverified:` 底下把它列出來。

## 高風險模式

審議席預設下限 3 席。需要更少的使用者可以開啟高風險模式並只開一席——而執行報告會記下「下限被規避,實際
開了幾席」。要避免的是**無聲**繞過安全機制;留下紀錄地繞過,那是有人做的決定。

兩者都在 `runner settings` 的畫面上設定,存進 `config/settings.json`;`runner settings --show` 不開
選單也能印出目前狀態,讓「這個專案在低於下限的情況下執行」是讀 log 的人也看得到的事實。單次執行仍可用
旗標覆蓋。

設定只能放寬審議席下限,不能碰其他任何東西——閘門、永久停點、裁決規則都在 `policy.py`,不吃任何輸入。
不認得的設定鍵會被拒絕而不是忽略;設定檔壞掉是錯誤而不是靜默採用預設:打錯字不可以和「關掉某個安全
機制」長得一模一樣。

## 治理

本 repo 以自己的規則開發:每個變更先在 [`docs/changes/`](docs/changes) 開 `CHG`,再由
[`docs/acceptance/`](docs/acceptance) 的 `ACC` 帶證據收尾。
[`tools/ledger_check.py`](tools/ledger_check.py) 在 CI 執行,缺欄位、沒有驗收就宣稱完成、或與實際做的
事漂移,都會讓 build 失敗。
