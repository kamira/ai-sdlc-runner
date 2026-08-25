# Review — README.md and docs/defect-log.md

You are one of two independent reviewers. The other has the same brief and will not see your answer.
Do not soften a verdict to look agreeable; do not manufacture disagreement to look independent.

## What you are reviewing

Two documents, at commit `d93fcd2`:

* `README.md` — rewritten twice in the last hour (CHG-20260823-14, then corrected by -15)
* `docs/defect-log.md` — every defect recorded while building this, grouped by how it was found

Both are **the front door**. Somebody arriving at this repository reads the README and forms their
whole model of what this is from it. A false sentence there costs more than a false sentence
anywhere else in the repo, because it is the one nobody double-checks against the code.

## The specific worry

The author of these documents is also the author of the code, wrote both in one sitting, and has
**already been caught reproducing, inside the README, a defect an independent seat found in this
project's mock-up** — omitting the failure paths from a flow diagram, in a document that quotes the
finding. That correction is CHG-20260823-15, and it is itself under review here.

Three kinds of claim in the README are now checked by CI (`test_documented_numbers`): the **counts**,
the **flag names**, and whether the **examples parse**. Everything else — every explanation, every
"because", every claim about what the code does — is unchecked prose.

**Your job is the unchecked part.**

## Read

1. `README.md` — all of it
2. `docs/defect-log.md`
3. `src/ai_sdlc_runner/graph.py`, `policy.py`, `engine.py`, `cli.py`, `server.py`, `intake.py`
4. `tests/test_documented_numbers.py` — what is and is not bound
5. `docs/changes/CHG-20260823-14.md` and `-15.md`

## The questions

**R1 — Is every factual claim in the README true?** Not the counts, which CI checks. The sentences.
For each one you check, say whether the code agrees. Particular attention to: the risk table's
"stops at" lists; the claim that a `pool`'s dispatch is reproducible; "one ask, one session"; the
three refusals described as "local only"; the claim that `input_artifacts` reaches every node; the
description of what happens after three unanswered intake asks; and the claim that
`decisions.next_module` may be `"frontier"`.

**R2 — Is the flow diagram right?** Compare it node by node against `graph.py`. Every node present,
every branch labelled with the label the graph uses, every gate marked, every terminal marked. This
is the one thing already got wrong once.

**R3 — What could somebody NOT do after reading this?** Assume a competent engineer who has never
seen the project, with the repo checked out. Walk their path: install, write a plan, run something,
see it stop, answer it. **Where do they get stuck, and what is not on the page that they need?** Be
specific — a missing command, an undefined term, a file they must create with no example.

**R4 — What does it overclaim?** Look for sentences that sound like guarantees. Anything asserting a
property the code does not enforce, or presenting an argument as a finding. The "practice" section is
the likeliest place: it describes how the repository governs itself, and the author is the one who
did the governing.

**R5 — Is the defect log honest?** It groups 32 defects by how each was found and draws conclusions
from the grouping. Are the conclusions supported by the entries? Is anything **missing** that you can
see evidence of in the repo — a defect the change records describe that the log does not? Is the
"no screenshots" explanation candid or is it an excuse?

**R6 — What is the single worst sentence in either document?** One. The one that would most mislead
somebody, weighted by how likely they are to rely on it.

## Answer format

Per question: a verdict word, the reasoning, `file:line` evidence.
End with one line: `README: sound` / `README: sound with changes` / `README: not sound`, then a
numbered list of what must change.

Quote the sentence you are objecting to. If you cannot substantiate a claim from the repository,
write "not substantiated" rather than reasoning from how a project like this usually reads.
