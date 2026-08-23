# Round 2 review — CHG-20260823-11 (fable-seat)

Reviewed against the frozen tree at `5aed9b0`. Every claim below was checked against the code, not against the record's description of the code. Working tree confirmed clean before and after review.

---

## R1 — Does each correction answer the finding it claims to answer?

**1. The self-contradiction ("`policy.py` and `graph.py` unchanged") — ANSWERED.**
The false sentence is struck; the blockquote at the Back-end section of `docs/changes/CHG-20260823-11.md` explains both halves, and task 12 gives `graph.py` a declared change-home, task 2 gives `policy.py` one. The diff of `26d1676` confirms the old sentence is gone, not merely annotated. The design now says both files change, which is what it always implied.

**2. The mock-up's node count — PARTLY.**
The factual correction is accurate and I verified it independently: `docs/design/console-mockup.html:569-588` defines 19 node entries, of which `next_module2` (line 580) does not exist in `graph.py`; grep for `fix_pass|re_review|halt_second_fail|review_failed|acceptance_failed` in the mock-up returns nothing, and all five exist in `graph.py:108-126`. So "18 of 23 plus one invented, all failure paths omitted" is true.
But the correction itself says the omitted paths are "exactly the ones an operator most needs a console for" — and then **no task requires the console to cover them**. Task 11's done-when is still "the four-part screen and the four configuration tabs". The correction fixes the record's honesty and leaves the design's actual wound untreated. A correction that names the consequence and produces no task for it has answered the *misstatement*, not the *finding*.

**3. "Ends the process" — ANSWERED.**
Verified: a gate halt sets `halted_at` and *returns* through `_finish` (`engine.py:674-678`); `walk` returns the report; the CLI prints it (`cli.py:375`) and exits (`cli.py:437`, `sys.exit(main())`). The correction is code-accurate, and it did change what the design does: task 1 was rewritten from "`Approver`: a gate blocks and waits" to the suspend/resume shape. One caveat carried to R3: the appended claim that the machinery "already exists and is tested" is stronger than the code — see R3.

**4. The §3 seat exclusion — PARTLY.**
The prose now excludes the seats ("The seats re-run blind or go to a person"), citing `engine.py:16` accurately ("The count is the user's to set; the independence is not" — verified, line 16). But three things stop this from being an answer rather than a restatement:
- **Task 3's done-when was not tightened.** It still reads "configurable count; round 2+ carries both sides attributed; the limit ends at a person" — satisfiable by an implementation that carries to the seats. The exclusion lives only in prose no test will ever read.
- **The interaction spec still contradicts it.** The mock-up — which the record calls "the interaction spec" — keeps the re-run toggle on the seats' tab (`console-mockup.html:428-442`, section `panel-panel`) and documents `GET/PUT /config/panel` as holding "Seat count, high-risk mode, per-seat model, **re-run-on-undecided and its limit**" (`console-mockup.html:483`). No task moves it.
- **"Struck pending task 12's separation" points at a task that cannot carry the separation** — see R2 on task 12.

**5. The collapsed design-only claims — ANSWERED.**
Verified in the current record: the Type field, the Tasks header, the Rollback line, and Status all defer to the State column; the diff shows all four old copies removed. This is the one correction that fully closes its finding.

**6. The three tightened done-whens:**
- **Task 1 — ANSWERED.** "Distinguishable from finished" is a real, observable requirement — and more real than the record knows: today a *finished* run also sets `halted_at` (`engine.py:719-721` set it at every TERMINAL node, including `done`), so halted and finished are currently the same shape. The refusal cases (duplicate, stale, wrong-run, wrong-gate) are watchable failures.
- **Task 2 — ANSWERED.** `engine.py:572` is exactly as quoted (`return "pass" if outcome["outcome"] == "pass" else "fail"`), and the done-when binds fixing it into the same task, plus raise-on-unknown. This forecloses the go-green-change-nothing build.
- **Task 4 — PARTLY.** The count-mismatch refusal is a watchable failure and closes the silently-asked-once hole. But the *other* half of the done-when — "adjudicated by the existing rule" — is not satisfiable by the existing rule as coded: `policy.adjudicate` raises `PolicyError("unknown seat(s): …")` for any voice not in `BY_SEAT` (`policy.py:651`) and reads veto off `BY_SEAT[s].veto` (`policy.py:655`). Model voices are not seats; they have no veto flag. See R3 — this is a live design gap the tightening did not touch.

---

## R2 — Are tasks 12–19 well-formed?

**Task 12 — PARTLY well-formed, and it is the load-bearing one.**
The positive half is watchable: `graph.Node` (`graph.py:50-75`) carries no mode today, `graph.validate()` (`graph.py:159-206`) is a real place to enforce one, and a build without the field fails visibly. Three holes:
1. **The closed set `single/panel/pool/follows` has no value for the seat panel.** The engine today distinguishes the seat path by `node.role == "seat"` (`engine.py:686`, `engine.py:725`). Task 12's own refusal clause forbids inferring mode "from a node's id, **role** or branch shape". So either `lead_review` gets `mode=panel` — and the seat panel becomes indistinguishable from an ordinary multi-model panel, which is precisely the conflation the §3 correction was written to end (seats: no carry, `SEAT_FLOOR`, veto seats; model panels: carry allowed) — or the seat behaviour stays role-keyed, violating the clause. The vocabulary cannot express the distinction the record now depends on.
2. **The reference types of `main` and `follows` are unspecified, and the only interaction spec uses one of each kind:** `main:"lead"` is a *role* (`console-mockup.html:576`), `follows:"engineer_build"` is a *node id* (`console-mockup.html:577`). A builder must guess.
3. **No mode assignment for the 23 existing nodes** and no cross-rules stated for `validate()` (pool requires main; follows requires an existing target; which kinds may be panel). "Validated by `graph.validate()`" without saying what is validated can be satisfied by a validator that checks only that the field exists.

**Task 13 — well-formed.** Its premise checks out: `lead_review` branches on `pass`/`fail` only (`graph.py:114-118`), and a tie is genuinely not a gate — `_gate` fires on the policy verdict (`engine.py:660-678`) while adjudication happens later at branch selection (`engine.py:725-726`), so `confirmed` has nothing to spend on it. Block / record / take-the-chosen-branch is watchable.

**Task 14 — well-formed**, though it states the failure (no snapshot endpoint) more than the contract (snapshot shape unstated). Acceptable at design level; "a reconnecting browser can tell waiting from running" is demonstrable.

**Task 15 — NOT well-formed as written.** "Record *who*" can be satisfied by code that does not do the job: with no identity mechanism anywhere in the design — no login, no session, no user registry, none of the listed endpoints establishes one — "who" is a client-supplied string. That is the button-caption failure (`console-mockup.html:1222`, `"Accept (as verifier)"` — verified) moved one layer down and renamed enforcement. Server-side enforcement of `halt_independent` against an honor-system name field is the same honor system.

**Task 16 — well-formed.** Double-click, stale tab, two browsers, wrong run/node/gate: each is a demonstrable failing input.

**Task 17 — well-formed.** I verified the premise end-to-end: `_TARGET_FIELDS` includes `input_artifacts` (`engine.py:385`), `_spoken_halt` feeds those fields to `policy.derive` (`engine.py:409-419`), `policy.py:219` is exactly `r"(^|[\s/@:.])prod(uction)?([\s/.:]|$)"` under the `deploy` kind, so `…/production/spec.pdf` matches, and `_permanent_halt` runs before the gate, unaffected by confirmations or high-risk mode (`engine.py:652-656` and the docstring at `engine.py:440-447`). Either remedy in the done-when is watchable.

**Task 18 — well-formed.** The premise is verified: every gate in the mock-up offers "Reject — send back" (`console-mockup.html:1223`) routing to `pm_plan` (`console-mockup.html:1231`), and `graph.py` has no such edges. "Either the edge exists or the button does not" is a real dichotomy — though *which* gates get a reject edge, and to where, is a governance decision the task defers rather than makes.

**Task 19 — well-formed** as a bundle; each listed property ("defined behaviour when an attachment changes mid-run" etc.) is individually demonstrable.

---

## R3 — What did the corrections break or newly assert?

**Code claims — all verified true:**
- `engine.py:572` — exact quote confirmed.
- `engine.py:674-678` — `_gate` sets `halted_at` at 674, returns through `_finish` at 678. Confirmed.
- `engine.py:16` — exact quote confirmed.
- `policy.py:219` — the regex, under `_TARGET_RULES["deploy"]` (`policy.py:212-220`). Confirmed.
- `_TARGET_FIELDS` at `engine.py:385` includes `input_artifacts`. Confirmed.
- `graph.py:114-118` for `lead_review`'s pass/fail-only branches. Confirmed.
- `tests/test_resume.py` exists; `RunConfig.resume` exists (`engine.py:234`); `AskJournal` exists (`engine.py:94`). Confirmed.
- codex-seat's "understates what it added": `git show 19e34ea --stat` confirms `docs/design/README.md` was added there. Confirmed.

**Three new assertions the corrections introduced that are wrong or overstated:**

1. **"both value-for-value identical to `policy.GATES` and the seat definitions" — half true, and the false half is new.** The mock-up's GATES table (`console-mockup.html:589-593`) is value-for-value identical to `policy.GATES` (`policy.py:99-124`) — I compared all ten gates, all three grades. But the seat definitions are **not** value-for-value: names and veto flags match (`console-mockup.html:594-597` vs `policy.py:551-562`), while every seat's question is a paraphrase — e.g. mock-up `"Does it do what the order said, and only that?"` vs policy's `"Is this the thing the task asked for? Line by line against what was written down…"`. In a record whose defining defect was overclaiming fidelity to the code ("the real 23 nodes"), the sentence *correcting* that overclaim contains a smaller one of the same species.

2. **"its machinery already exists and is tested" (corrected risk note) — overstated.** `RunConfig.resume` + `AskJournal` resume *asks*. Nothing in the code distinguishes a suspended run from a finished one — `engine.py:719-721` sets `halted_at` on TERMINAL success too, so today `halted_at` is populated by *both* outcomes — and no machinery exists for recording a gate *decision*, refusing a duplicate or stale one, or run identity (no run-id concept exists in `RunReport` or `RunConfig`; verified by reading `engine.py:150-240`). The direction of the correction is right (a stop is already a return); the reassurance is broader than the code.

3. **"The seats re-run blind or go to a person" — newly asserted behaviour that nothing implements or tasks.** It contradicts the still-frozen interaction spec (`console-mockup.html:483`, re-run configured on `/config/panel`), is absent from task 3's done-when, and leans on task 12, whose mode vocabulary cannot carry it (R2). A design assertion with no task, no endpoint change, and a contradicting spec is a wish.

**One contradiction the corrections created between record and code path:** the "three things the engine must learn" table still says multi-model on a node is "the same call with a different set of voices" (`_adjudicate`). The existing call *refuses* a different set of voices: `policy.py:651` raises on any voice not in `BY_SEAT`, and veto is a per-seat property (`policy.py:655`). "A generalisation of code that exists" is the record's stated reason the change is acceptable at all — and the generalisation requires deciding veto semantics for model voices, which nobody has decided or tasked.

---

## R4 — Is the round-1 verdict handling honest?

**The tie rule — honest and consistent.** Split → does not pass mirrors the repository's own `policy.adjudicate` ("a tie does not pass", `policy.py:663`), applied to its own record. The record nowhere claims the corrections cure the verdict — "Not claimed / A second review round" says so explicitly. That paragraph is the most honest thing in the document.

**The both/one separation — NOT SUBSTANTIATED, structurally.** The raw seat verdicts are not committed anywhere — `docs/design/` holds only the brief (`review-round-1-brief.md`) and the README, which says the verdicts "live in the change record's Review round 1 section". That means the only surviving witness to what each seat found is the corrected author's own summary. I cannot check whether a single-seat finding was promoted, a shared one demoted, or a finding dropped. The internal arithmetic does not close either: codex-seat is credited with "7 required changes" yet appears in 6 shared findings plus 4 solo ones; findings and required changes need not be one-to-one, but from the repository alone the numbers are unverifiable. For a repository whose stated history is "disagreement being flattened", committing the brief but not the two verdict documents is precisely the flattening surface.

**One checkable overstatement of independence:** finding 5 presents "both seats named the same safer alternative: the walk returns a suspended report the caller resumes" as independent convergence. The round-1 brief *handed both seats that alternative as its worked example* — `review-round-1-brief.md`, Q2: "If you think a different shape is safer (**e.g. the walk returning a suspended state the caller resumes**…), say which and why." Two primed reviewers converging on the primer is evidence of the primer, not of the alternative. The record does not disclose this. The suspend/resume shape may still be right — the engine evidence supports it — but "both seats found it" is not the strength of claim it is presented as.

No instance found of a single-seat finding presented as shared; the attributions that can be cross-checked (attachment scanner, node count, idempotency, rejection routing) are each internally consistent. Beyond that: not substantiated.

---

## R5 — Is task 1 now specified tightly enough to build safely?

**Nearly — one hole is disqualifying until answered.** What is now pinned is good: distinguishable-from-finished (a real property; today finished and halted both set `halted_at`, `engine.py:719-721`), the report's required fields, exactly-one-decision consumption, and four named refusal cases. A wrong build fails visibly against that.

What is still missing:
1. **The relation between a "recorded decision" and the existing confirmation-spend mechanism.** The engine already has a decision-consumption system: `confirmations` counted per gate and decremented per stop (`engine.py:631-644`, `670-673`), with its own audit trail and unspent-confirmation reporting in `_finish` (`engine.py:575-591`). Task 1 introduces a second one. Whether a resumed decision *is* a confirmation spend (and appears in `report.confirmations`, and is counted by the unspent check) or a parallel mechanism beside it is unspecified — and two overlapping approval mechanisms with subtly different audit semantics is exactly the class of quiet governance bug this repository documents itself shipping. This must be answered before task 1 starts.
2. **Run identity.** "Wrong-run answers are refused" presumes a run id; no such concept exists (`RunReport`, `engine.py:150-197`; `RunConfig`, `engine.py:199-240`), and who mints it and how it binds to the journal directory — currently the only durable run identity — is unstated. Buildable, but the builder decides governance if the record does not.

Neither hole invalidates the shape. Both are one-paragraph decisions. Task 1 may start after they are written down, not before.

---

## R6 — What is still missing, after 19 tasks and two rounds

1. **Task 3's done-when does not encode the seat exclusion** the §3 correction asserts; a build that carries reviewer reasoning to the seats satisfies it. One clause fixes it: "the carry never applies to a node whose voices are review seats; a seat panel re-runs blind or blocks for a person."
2. **Task 12's mode set cannot express seat-panel vs model-panel**, and `main`/`follows` reference types are unspecified while the interaction spec uses a role for one and a node id for the other (`console-mockup.html:576-577`).
3. **No decision on adjudication of non-seat voices.** `policy.adjudicate` validates voices against `BY_SEAT` and applies per-seat veto (`policy.py:651`, `655`). Does any model voice carry veto? Majority-only? The record's "same call, different voices" is currently a `PolicyError`.
4. **No identity mechanism behind task 15** — no task establishes who a person is to the server, so "record who" is a client-supplied string.
5. **No task brings the console to the failure paths** (`fix_pass`, `re_review`, `halt_second_fail`, `review_failed`, `acceptance_failed`) — the correction itself calls these the paths an operator most needs, and task 11's done-when does not mention them.
6. **The raw round-1 verdicts are not committed**, so every future round audits the author's summary of its own correction. Committing both seat documents (or hashes of them) next to the brief closes it.
7. **Task 1's decision-store/confirmations relation and run identity** (R5).

---

Corrections that are honest and code-accurate in every line-level claim I could check; two corrections that fixed the record's truthfulness without changing what the design does (mock-up coverage, seat exclusion); one new overclaim introduced by a correction (seat definitions "value-for-value"); one presented-as-independent convergence that the brief primed; and a set of new tasks of which six are buildable as written, one is load-bearing and under-specified (12), and one is satisfiable by code that does not do the job (15). The verdict rule the record applied to itself was applied correctly. The gaps that remain are specific, small, and every one has a place to live.

**ROUND 2: pass with changes**

Before task 1 may start:
1. Answer R5's hole in the record: whether a resumed gate decision is a spend of the existing `confirmations` mechanism (`engine.py:631-644`, `670-673`) or a new mechanism, and who mints the run id that "wrong-run refused" presumes.
2. Tighten task 3's done-when to encode the seat exclusion: the round-2 carry never applies to seat panels; seats re-run blind or block for a person.
3. Extend task 12: either add a mode value (or orthogonal flag) that distinguishes a seat panel from a model panel without reading `role`, or explicitly exempt the seat path from the inference-refusal clause with a written reason; specify whether `main`/`follows` reference a role or a node id; state the mode of each of the 23 existing nodes and the cross-rules `graph.validate()` enforces.
4. Add to task 4 (or a new task) the adjudication rule for non-seat voices: `policy.adjudicate` currently refuses them (`policy.py:651`) and veto is a seat property (`policy.py:655`) — decide whether model voices can veto, and change the done-when's "the existing rule" to name the generalised rule.
5. Rewrite task 15's done-when so it cannot be satisfied by a client-supplied name: name the identity mechanism (even a minimal one — a server-issued operator token) and the check `halt_independent` performs against it.
6. Either add the five failure-path nodes to task 11's done-when (the console renders and can operate `fix_pass`, `re_review`, `halt_second_fail`, `review_failed`, `acceptance_failed`) or record why the console ships happy-path-only.
7. Correct the record's new "value-for-value identical … seat definitions" sentence to what is true (gates value-for-value; seats: names and veto flags only), and commit the two round-1 seat verdicts (or their hashes) beside `review-round-1-brief.md` so round separation stays auditable.
