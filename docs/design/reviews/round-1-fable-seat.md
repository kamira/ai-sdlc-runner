# Design review — CHG-20260823-11, fable-seat

Files reviewed: `docs/changes/CHG-20260823-11.md` (the record), `src/ai_sdlc_runner/engine.py`, `src/ai_sdlc_runner/policy.py`, `src/ai_sdlc_runner/graph.py`, `docs/design/console-mockup.html`. All five read at commit `73f4032`; nothing edited.

---

## Q1 — The front/back line. **Verdict: holds, with one leak — identity.**

No endpoint lets the browser compute a verdict or an adjudication. The endpoint list (record `docs/changes/CHG-20260823-11.md:132-135`; mock-up table `docs/design/console-mockup.html:477-491`) puts every decision behind `POST /run/gate` and `POST /run/decide`, both of which transport a *human's* answer, and the mock-up's own rule table states "The front end never adjudicates. It shows the voices; the server decides the outcome" (`console-mockup.html:523-524`). The mock-up's gate prompt says "Blocked **server-side**. You can close this tab" (`console-mockup.html:1225`). That is consistent.

The leak is **who**. `POST /run/decide` is specified as "Recorded with who decided" (record line 135; mock-up line 488) and the tie prompt promises "recorded with **your name** on it" (`console-mockup.html:1185`) — but no endpoint in either list establishes identity. There is no auth, no session, no user model anywhere in the design. So the "who" in a governance record can only be a value the front end supplies, i.e. the back end trusting a front-end-computed claim. This bites hardest at `halt_independent`: `policy.GATES` grades acceptance `halt_independent` at high risk (`policy.py:115`), whose meaning is "the verifier must not be the builder", and the mock-up's only enforcement is the label on a button — "Accept (as verifier)" (`console-mockup.html:1222`). With no identity model, independence is asserted by whoever clicks. That is governance resting on the front end.

Endpoint named: `POST /run/decide` (and `POST /run/gate` in its `halt_independent` case).

Secondary observation: the mock-up's gate prompt offers "Reject — send back" (`console-mockup.html:1223`), but the engine's gate has no reject-and-reroute transition — a stopping verdict either halts or is confirmed (`engine.py:660-678`), and `graph.py` has no edge for it. If `POST /run/gate` can carry "reject", that is a new flow edge no task designs. See Q6.

---

## Q2 — `Approver` and the halt guarantee. **Verdict: workable, but a suspended-state shape is safer — and the repo already owns most of it.**

How halting works today: every stop is a *return*. `_gate` sets `halted_at`/`halt_reason` and returns the report through `_finish` (`engine.py:674-678`), `walk` returns it (`engine.py:680-682, 711-713`), and the process exits. Nothing after the halt can execute, which is the "crude and completely reliable" property the record itself names (record lines 155-157).

What a callable `Approver` makes reachable that is not reachable today: a `walk` frame blocked *inside* the loop, holding `report`, `confirmations`, `taken`, and the journal open, in a state no `RunReport` describes — `RunReport` has no "waiting" state at all (`engine.py:156-179`); a report only exists once the walk returns. So while blocked, the only witness that the run is stopped is the server's transient state, not the engine's record.

Ways "alive and stopped" can be mistaken for "alive and continuing":
1. **Approver failure semantics are undefined.** If the Approver raises, returns `None`, or returns early, the code after the gate call runs in-process. Today the equivalent bug is impossible because the stop is a `return`. Task 1's done-when ("a stopping verdict suspends the walk; the CLI's approver refuses", record line 141) does not pin what a malformed Approver answer does.
2. **The observer cannot re-derive the state.** The endpoint list has `GET /run/events` (SSE) and nothing else that reads run state — there is no `GET /run` snapshot (record lines 132-135; `console-mockup.html:477-491`). A browser that reconnects after missing the `BLOCKED` event (`console-mockup.html:515`) has no way to distinguish waiting from running. Task 10's done-when "a reload mid-run rebuilds the view" (record line 150) is not satisfiable from the listed endpoints.
3. The gate-stop seam is already delicate: `_gate` returns `_finish(report, confirmations)` (`engine.py:678`) and the caller then wraps it in `_finish` *again* (`engine.py:680-682, 711-713`), so a run stopping at one gate while holding an unspent confirmation for another appends the "confirmed N more time(s)" line twice (`engine.py:586-589`). Latent and minor today; Task 1 rebuilds exactly this seam.

The safer shape: **the walk returning a suspended/stopped report the caller resumes**, i.e. keep "every stop is a return" and put the waiting in the server. The machinery exists and is tested: `AskJournal` re-asks only what is pending (`engine.py:94-139`), `resume=True` + `confirmed=[gate]` continues a stopped run past exactly one spend of that gate (`engine.py:234-239, 615-642`), effects are probe-idempotent so a re-walk redoes nothing (`engine.py:210-213, 334-353`), and `tests/test_resume.py` / `tests/test_kill_resume.py` exist. `POST /run/gate` then means "re-enter the walk with this gate confirmed", the halt guarantee is untouched, and "alive and stopped" is impossible because stopped is never alive. Its one real cost: the tie/`undecided` stop is *not* a gate (no gate name to confirm — see Q3/Q6), so resuming past a tie needs its own recorded decision input; that must be designed either way.

If the Approver shape is kept anyway, Task 1's done-when must add: refusal is the default on any non-answer, and the blocked state is externally observable and reconstructable.

---

## Q3 — `undecided` in `policy.adjudicate`. **Verdict: yes, it belongs in policy — and no existing caller would continue on it; the one caller would silently collapse it to `fail`.**

Call sites, grepped: production code calls `policy.adjudicate` in exactly one place — `engine._adjudicate` at `engine.py:570`, reached from `walk` at `engine.py:726`. Everything else is tests (`tests/test_policy.py:142-166`, `tests/test_flow.py:351-391`) and a docstring mention in `tests/test_nothing_is_unwired.py`.

What that caller does with a third value: `engine.py:572` — `return "pass" if outcome["outcome"] == "pass" else "fail"`. So `undecided` would **not** be treated as not-fail-and-continue; it would be silently flattened to `"fail"` and routed down `lead_review`'s fail branch to `review_failed` (`graph.py:114-120`). Fail-safe in direction, but wrong in meaning: the run would send the work back — an automated decision — where the design's entire point is that *nobody decided* and a person must (record lines 74-81). So Task 2 is only coherent if `engine._adjudicate` changes in the same task; its done-when ("the caller must handle it or the run stops", record line 142) says so, but note the fallback "or the run stops" is not what the shipped caller does — it continues down the fail branch. The done-when as written can be satisfied by behaviour the design forbids.

Why `undecided` belongs in policy rather than being the caller's reading of a fail: the repo's own stated rule is that the adjudication rule lives in one place — `test_the_panel_routes_through_the_policy_not_the_engines_own_arithmetic` (`tests/test_flow.py:385-391`). Having the caller re-count verdicts to distinguish tie-fail from majority-fail duplicates the counting outside policy, and only policy knows the veto structure (`policy.py:655-657`) that makes a veto-fail *not* a tie. The tests asserting tie→fail (`tests/test_policy.py:152-156`) change with a written reason, as the record already commits to (record lines 158-160).

One knock-on the record misses: with the default `SEAT_FLOOR = 3` (`policy.py:568`) an odd panel cannot tie; a seat-panel tie is reachable only at 4 seats or an even multi-model panel. Not an objection — but it means the tie path gets little natural exercise and needs deliberate tests.

---

## Q4 — Pool vs panel. **Verdict: the distinction is well-founded; it is NOT decidable from the node data in `graph.py`; and yes — today three configured models would silently become one ask.**

Well-founded: N adjudicated voices and a dispatch pool are different claims about what happened, and calling a dispatch a vote would misrepresent the record. The mock-up's framing (one does the work, "this is a dispatch, not a vote", `console-mockup.html:996-999`) is right, and random choice with the stated rationale (record lines 69-71) is defensible.

Not decidable: `graph.Node` carries `id, kind (step/decision/loop/terminal), label, role, gate, gate_when, next, branches, answer_decides, note` (`graph.py:59-75`). Nothing there separates `engineer_build` (pool) from `engineer_selfverify` (follows-the-builder): both are `role="engineer"`, kind `STEP`, no branches (`graph.py:97-101`). Nor does anything separate a verdict node from a work-producing one — the mock-up's own "verdict" set includes `lead_assess`, which in `graph.py` is a plain STEP with `answer_decides=False` (`graph.py:86-90`), so `answer_decides` is not a usable proxy. The proof is by construction: the mock-up had to **invent** fields the graph does not have — `kind:"verdict"/"pool"/"follows"/"work"`, `main:"lead"`, `follows:"engineer_build"` (`console-mockup.html:569-587`) — and every behavioural branch in it keys off that invented field (`console-mockup.html:991, 993, 765, 783`).

Meanwhile the record asserts "`policy.py` and `graph.py` unchanged" (record line 117; repeated at `console-mockup.html:461`), and no task among the 11 adds the semantic to the graph. Task 5 is written as "Dispatch pool on `engineer_build`" (record line 145) — i.e. the behaviour would be keyed off the node's *name*. This repo merged, three commits ago, "fix: a name is evidence only if it constrains what happens" (commit `8dd23e0`, CHG-20260823-10). Keying pool semantics off `id == "engineer_build"` is that defect class again — the coarse check answering "pool" about something it never examined.

Could a node be configured with three models and silently ask one? **Yes, structurally, today.** The engine has no concept of a node's model count: routing lives entirely in the session factory (`engine.py:268-280`), and the non-seat path opens exactly one session per node (`engine.py:701-709`). If the server (task 10) holds `GET/PUT /config/nodes` model lists and the walk is not taught to fan out on verdict nodes, three configured models is one ask and silence. The only existing guard, `_note_panel_diversity`, runs solely on the `role == "seat"` path (`engine.py:687-700`). Task 4's done-when ("N voices, N sessions, adjudicated", record line 144) states the happy path but does not pin the failure mode: nothing says *a mismatch between configured count and opened sessions is refused or disclosed*. The record names this exact risk (lines 161-162) and then leaves it out of the done-when — the one place it would bind.

---

## Q5 — The re-run carry. **Verdict: sound for a same-question multi-model panel; conflated for the seat panel, and the record does not draw the line it needs.**

For N models on **one question** (task 4's panels), the reasoning holds: round 1 is blind, so the independent verdicts exist and are recorded (`console-mockup.html:1046-1080` shows round-1 adjudication happening before any carry); round 2 trades independence for information, both sides carried with attribution (`console-mockup.html:1070-1077` — `objections=results.map(...)`, carrying `v:"pass"` rows too, matching the record's correction at lines 88-90); and the limit ends at a person for the stated sharper reason (record lines 96-97). Anchoring is real, named, and accepted with a reason. That is a legitimate design decision, honestly recorded.

For the **seats** it is a different object, and the record conflates them in one concrete place: the re-run configuration lives on the Review panel tab — `/config/panel` carries "re-run-on-undecided and its limit" (record line 134; `console-mockup.html:436-441`) — which means the mechanism is specified *for the seat panel*, and §3 of the record ("An undecided panel may be re-run", lines 83-97) never excludes the seats. Two facts make the seat case not the same thing:

1. Each seat has its **own question** — the mock-up says so itself: "four seats is four different questions" (`console-mockup.html:443-445`; `policy.py:550-562`). Carrying every seat's reasons to every seat feeds the conformance seat the risk seat's argument: cross-question contamination, not a second opinion on the same question.
2. Seat independence is a stated invariant of the governance, not a tunable: "The count is the user's to set; the independence is not" (`engine.py:16`), enforced culturally by `_note_panel_diversity` (`engine.py:533-552`) and by `halt_independent` (`policy.py:115`). §3 quietly makes seat independence configurable from round 2, which contradicts the engine's own docstring.

The record accepts the anchoring cost "knowingly" (line 92) — but it argues the acceptance only for the information-starved same-question case, and then ships the switch on the seats' tab. Required change: exclude the seat panel from carry (blind re-run or straight to a person), or argue the seat case explicitly on its own terms.

---

## Q6 — What is missing from the 11 tasks. **Verdict: five specific tasks, beyond the three unsettled items the record names.**

1. **A task adding the multi-model semantic to `graph.py` nodes** (`verdict` / `pool` / `follows` / `work`, plus `main` and `follows` references), with `graph.validate()` extended to check them — and the record's "graph.py unchanged" claim (line 117) corrected to match. Without it, tasks 4 and 5 can only be built on name-inference (Q4). The mock-up already contains the full field design (`console-mockup.html:569-587`); it just has nowhere to live in the repo.
2. **A task routing `undecided` through the walk.** `lead_review` branches only on `pass`/`fail` (`graph.py:114-118`) and `engine._adjudicate` returns only `"pass"`/`"fail"` (`engine.py:572`). A tie is not a gate — it has no gate name for `confirmed` to spend (`engine.py:666-673`) — so neither the Task 1 Approver (gates) nor Task 2 (policy return value) actually wires "block here until `POST /run/decide`, then take the branch the person chose, recorded". The mock-up behaviour at `console-mockup.html:1136-1207` is a design for it; no task owns it.
3. **A run-state snapshot** (`GET /run` or defined SSE replay). Task 10's done-when "a reload mid-run rebuilds the view" (record line 150) has no endpoint behind it — the list has only the event stream (record lines 132-135). Also: the record's endpoint list includes `GET /flow` and `POST /run/resume`, the mock-up's table has neither (`console-mockup.html:477-491`, grep for `resume` in the file returns nothing) — the two specifications of the API already disagree.
4. **An identity model** for `POST /run/gate` / `POST /run/decide` — who approved, and enforcement of `halt_independent`'s independence (Q1). Even a minimal "the server is single-operator and records that name from its own config, never from the request" would do; at present "recorded with who decided" is unimplementable except on the browser's word.
5. **A rule for attachment paths entering the target scanner.** Task 9 puts attachments on **every** node's `input_artifacts` (record lines 42-44, 149). `input_artifacts` is a `_TARGET_FIELDS` member (`engine.py:385`) read by `_spoken_halt` through `policy.derive` (`engine.py:409-422`), whose deploy rule matches bare `prod(uction)` path segments (`policy.py:219`). A user attaching a file whose stored path contains e.g. `.production.` trips a **permanent halt on every node of every run** — unrelaxable by design (`engine.py:439-456`). Either attachments are exempted with a written reason, or stored under names that cannot collide; nobody has decided, and no task names it.

Also unowned, smaller: the gate prompt's "Reject — send back" (`console-mockup.html:1223`) is a flow edge (`merge` → back to where?) that `graph.py` does not have and no task designs — the mock-up's reject just resets the sim.

---

## Q7 — Does the record tell the truth about itself? **Verdict: mostly, and better than its predecessor — but it contains one assertion that is false as written today, one that is false against the repo's own copy of the mock-up, and it triples the sweep burden it was designed to reduce.**

Read as an adversary:

- **False as written, today:** "Back end — the existing runner. `policy.py` and `graph.py` unchanged" (record line 117; repeated `console-mockup.html:461`) sits eleven lines above "Plus one policy change: `adjudicate` gains an `undecided` outcome" (record lines 127-128), and Task 2 (line 142) changes `policy.py`. Both cannot be true. A reader reconciling the record against itself fails before touching the repo. (And per Q4, `graph.py` cannot stay unchanged either if task 5 is to be built honestly.)
- **False against the repo:** "The mock-up … built on the real 23 nodes, 10 gates and 4 seats" (record lines 35-36). The 10 gates check out — the mock-up's `GATES` (`console-mockup.html:589-593`) is value-for-value identical to `policy.GATES` (`policy.py:99-124`) — and the 4 seats match (`console-mockup.html:594-597` vs `policy.py:550-562`). But the mock-up's `NODES` array has **18** entries (`console-mockup.html:569-587`), of which one (`next_module2`, line 580) is invented, and six real nodes are absent: `fix_pass`, `re_review`, `halt_second_fail`, `review_failed`, `acceptance_failed`, `feedback`-as-decision. It is the happy path, not the 23 nodes.
- **Unverifiable from the repo:** the hand-run claim — "19 nodes, 14 asks, stopped at `merge`, resumed after a killed session … refused a `git push origin +main:main`" (record lines 30-33). No journal, transcript, or report of that run is committed. Not substantiated either way; as evidence for "the engine is not what is missing", it rests on the author's word. Likewise the external artifact URL (line 35) can drift from the committed `console-mockup.html` with no repo-side trace, and "correcting the design four times" (line 7) is untraceable.
- **Where it goes stale first:** the design-only claim is asserted in **four** places — Type (line 6, "Nothing in `src/` is written for it"), the tasks header ("Tasks — none started", line 137), Rollback ("none of it is written yet", line 163), and Status (line 167). The moment Task 1 lands, all four are false until each is swept. CHG-20260822-04 went stale with the claim in fewer places (record lines 12-15); this record identifies the recurrence risk correctly and then multiplies the surface. The first to rot will be line 137's header — a builder ticking the table's State column will update `[ ]` → `[x]` beside a header still saying "none started". The Status section is good; the redundant copies of its claim are the hazard.

Credit where due: the "Not claimed" section (lines 189-193), the explicit unsettled list (lines 179-188), and recording what each decision was corrected *from* (lines 55-107) are exactly the honesty the previous failure demanded.

---

## Overall

The four design decisions are well-argued and the front/back split is drawn in the right place. But the record contradicts itself on what stays unchanged, the pool/panel distinction has no home in the node data it claims not to touch, the `undecided` path has policy and prose but no route through the walk, and the seat panel is quietly included in a carry mechanism that erodes the one property the seats exist for.

**DESIGN: sound with changes**

Before Task 1 may start:

1. Resolve the record's internal contradiction: strike or qualify "`policy.py` and `graph.py` unchanged" (record line 117; `console-mockup.html:461`) — Task 2 changes `policy.py`, and change 2 below changes `graph.py`.
2. Add a task: declare the multi-model semantic (`verdict`/`pool`/`follows`/`work`, with `main`/`follows` references) as node data in `graph.py`, validated by `graph.validate()`; forbid inferring it from a node's id (`graph.py:59-75`, `console-mockup.html:569-587`).
3. Tighten Task 4's done-when: a node configured with N models that opens fewer than N sessions is refused (or at minimum disclosed in the report, as `_note_panel_diversity` discloses) — the silent-one-ask path at `engine.py:701-709` must be made impossible, not just avoided.
4. Add a task: the walk's `undecided` route — `engine._adjudicate` must stop collapsing non-pass to `fail` (`engine.py:572`), and the block-until-`/run/decide` wiring must be owned by a task, since a tie is not a gate and Task 1's Approver does not cover it.
5. Decide Task 1's shape explicitly against the alternative: a stopped-report-plus-resume design reuses tested machinery (`engine.py:234-239, 622-642`, `tests/test_resume.py`) and preserves "every stop is a return"; if the callable Approver is kept, its done-when must pin refusal-on-any-non-answer and an externally reconstructable blocked state, and an endpoint (`GET /run`) must exist for Task 10's "reload rebuilds the view".
6. Exclude the seat panel from the round-2 carry (or argue its inclusion explicitly): carry across seats mixes per-seat questions (`console-mockup.html:443-445`) and contradicts the engine's stated independence invariant (`engine.py:16`); move the setting off `/config/panel` if it applies only to multi-model nodes.
7. Specify the identity behind `POST /run/gate` and `POST /run/decide` — "recorded with who decided" and `halt_independent` (`policy.py:115`) are unenforceable on a browser-supplied name.
8. Decide the attachment/target-scan interaction for Task 9: attachment paths land in `input_artifacts` on every node and are scanned by `_spoken_halt`/`policy.derive` (`engine.py:385, 409-422`; `policy.py:219`), so a filename can permanently halt every run.
9. Correct the record's mock-up claim (18 happy-path nodes, not "the real 23", record line 35) and reconcile the two endpoint lists (`GET /flow` and `POST /run/resume` appear in the record only); collapse the four copies of the design-only claim (record lines 6, 137, 163, 167) into one Status reference so the sweep the record itself worries about has one place to happen.
