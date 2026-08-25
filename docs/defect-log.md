# Defect log

Every problem hit while building the operator console and its governance — 26 change records, 915
tests, five live projects.

Grouped **not by task but by how each one was found**, because that turned out to be the more useful
fact: the defects that would have shipped silently were almost never the ones the test suite caught.

| Where it came from | Count |
|---|---|
| An independent seat, reading a record or the code | **13** |
| Only by running it on a real project | **9** |
| The test suite, unprompted | **3** (+1 intended collision, below) |
| My own process failures | **10** |
| Putting the README through the same review | **5** |
| Reviewing a **design** before its code existed | **14** |
| Reviewing the **code that answered** that design | **11** |

## On screenshots

There are none for these. The screenshot tool could not composite the browser pane for most of this
work — every attempt returned *"the Browser pane is not displayed, so the page is not compositing
frames"* — and by the time it worked, every defect below was already fixed.

It would have helped less than it sounds: **four of these thirty-five had a consequence visible on a screen**
— the ineffective *add to the brief*, the missing dispatch line, the first-click exception, and the
stale-token 401. The rest were tracebacks, failing assertions, or wrong values in a JSON response.

So the honest version of this section is narrower than the one that stood here first, which said
*"two of thirty-two"* against a table summing to 35 and concluded screenshots "would not have helped
much". Both seats caught the arithmetic. A screenshot would not have shown any of the four *causes*,
but it would have documented what an operator saw, and that is worth something. What is quoted below
is captured output where the entry says so and retrospective prose where it does not.

---

## Found by an independent seat — 13

Two seats reviewed each round with the same brief, neither seeing the other, against a frozen tree.
**Every one was found before the change's code existed** — they are defects in design records and in
claims, caught by reading rather than by anything executing. (Some quote engine code that already
ran; what did not exist was the code the record was proposing. The first version of this sentence
said "before the code existed", which both seats read as false of its own entries.)

### task 2 — adding `undecided` to the policy would have been a no-op that went green

```
return "pass" if outcome["outcome"] == "pass" else "fail"   # engine.py:572
```

The design said *"`adjudicate` gains an `undecided` outcome"*. The engine would have flattened it
straight back to `fail` and routed the work down the fail branch — **an automated decision, where the
entire point of `undecided` is that nobody decided.** Tests green, behaviour unchanged, task ticked.
Both seats found it separately in round 1.

### task 4 — the record's stated reason the change was acceptable was false

```
raise PolicyError(f"unknown seat(s): {sorted(unknown)}")   # policy.py:649-651
```

The record justified "any node can be a panel" as *"a generalisation of code that exists, not new
governance — which is the only reason it is acceptable at all."* That call **raises** on any voice
outside `BY_SEAT`, and veto is a per-seat property. Not a generalisation: a crash. Missed by both
seats in round 1 and by me; caught in round 2.

### task 1 — "distinguishable from finished" did not exist

```python
if node.kind == graph.TERMINAL:
    report.halted_at = node.id      # engine.py:719 — so does `done`
```

A gate halt set `halted_at`. So did every terminal node. **Finished and waiting were the same
shape**, so "is this waiting for me?" had no answer — and the record had graded itself high risk
partly on a property the engine did not have.

### tasks 5 and 12 — pool vs panel was not decidable from the node data

`engineer_build` (a pool) and `engineer_selfverify` (follows the builder) are both `role="engineer"`,
both `STEP`, both branchless. The mock-up had to **invent** `kind`/`main`/`follows` fields. Task 5 as
written keyed behaviour off a node's *name* — three commits after merging *"a name is evidence only
if it constrains what happens."*

### task 17 — an attachment's filename could permanently halt every run

```
_TARGET_FIELDS = ("input_artifacts", ...)          # engine.py:385, scanned
r"(^|[\s/@:.])prod(uction)?([\s/.:]|$)"            # policy.py:219
```

Attachments were to go on **every** node's `input_artifacts`, which is scanned for red lines. A spec
at `…/production/spec.pdf` would raise an unrelaxable permanent halt on every node of every run.
Found by one seat, before a line was written. Nobody had noticed the attachment feature fed the
safety scanner.

### task 15 — `halt_independent` was enforced by a button caption

The design promised decisions *"recorded with who decided"* while no endpoint established who anyone
was. The only enforcement of verifier-independence was a button reading **"Accept (as verifier)"** —
independence asserted by whoever clicked.

### the record contradicted itself eleven lines apart

```
"`policy.py` and `graph.py` unchanged"            # line 117
"Plus one policy change: `adjudicate` gains…"     # line 128
```

A reader reconciling the record against itself failed before reaching the repository. Both seats
found it independently.

### the mock-up claimed 23 nodes and drew 18

Plus one node (`next_module2`) that does not exist. The five omitted — `fix_pass`, `re_review`,
`halt_second_fail`, `review_failed`, `acceptance_failed` — are **all failure paths**, which is what a
console is for.

### the "independent convergence" I reported was my own primer

```
"e.g. the walk returning a suspended state the caller resumes"
                              # review-round-1-brief.md, Q2 — written by me
```

I handed both seats the alternative in the brief, then reported their agreement as independent
convergence. One seat went back and read the brief. **The second time a seat caught me steering a
panel; neither time would I have caught it.**

### I silently dropped `role` from a refusal clause

```
round 1:  "inferring it from a node's id, role or branch shape is refused"
round 2:  "inferring the mode from a node's id or branch shape is refused"
```

No reason given anywhere — **in a commit whose message said "tightened"**. The engine keys the whole
seat path off `role`, so under the narrowed clause a decorative `mode` field with role-keyed dispatch
would have violated nothing.

### a fix for escape hatches introduced an escape hatch

Task 11: *"…or this record says in writing why the console ships happy-path-only."* A paragraph
satisfied it. Added **while fixing** the finding "a correction that names a consequence and produces
no task".

### one seat's agreement reported as two

*"Both agreed the 'Not claimed' section is honest."* Only one did; the other never addressed the
section. Its committed verdict was the proof — **which is what committing them was for**.

### a false citation inside the paragraph about evidence integrity

It pointed at `review-round-2-brief.md` as quoting the primed alternative. That brief does not quote
it. The only source was round 1's.

---

## Found only by running it — 9

Five projects: a one-function library, a three-module SPA, a five-module client/server pair, and two
intake demos. **Not one of these was caught by 800+ tests.** Several had been shipping for several
changes.

### task 10 — two runners could hold the same port, and answer at random

```
listening pids: ['1136', '9960']    # both on 127.0.0.1:8791
```

`ThreadingHTTPServer` sets `allow_reuse_address`, so on Windows a second `serve` binds silently.
Caught by watching the console take answers from **a process that had already been replaced** — a
stale build serving requests, with nothing anywhere saying so. "One project, one runner" was a
sentence nothing checked.

### task 10 — every gate approval re-walked the entire flow

```
lead_task_review -> pass | 2/3 voices passed
lead_task_review -> pass | 2/3     # all three identical — should have been 3/3, 3/3, 2/3
lead_task_review -> pass | 2/3
```

`serve` never required a journal, so `resume` was `False` and every approval re-asked everything. The
trace was almost invisible: on the final replay, every reviewer saw all three modules already built.
**The one-module demo had this exact bug and looked fine.** A real agent would have rebuilt every
module and re-opened every PR, once per gate.

### task 9 — "add to the brief" landed and changed nothing

```
1st instruction  → missing: flow, architecture, requirements, outputs, ui | asked: 1
2nd instruction  → missing: flow, architecture, requirements, outputs, ui | asked: 1
3rd instruction  → missing: flow, architecture, requirements, outputs, ui | asked: 1
```

`/run/instruct` appended, bumped the version, returned the snapshot — and **re-asked nobody**. The
seats went on reporting what the *first* instruction had not said, however much was added afterwards.
The most convincing-looking no-op of the whole build.

### task 5 — a growing blueprint had no way to extend the loop

```
EngineError: node 'next_module' was reached 5 time(s) but only 4 decision(s)
were supplied for it — the run does not guess how the loop ends
```

A late instruction made the PM plan two more modules; `decisions.next_module` was a list written for
three. **Refusing was right** — the fix was to decide the loop from the frontier, reading two
recorded facts instead of a prediction.

### task 9 — Windows reported a too-long path as a missing file

```
dir exists after init: True
FileNotFoundError: [Errno 2] No such file or directory:
  '.runner\attachments\8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4'
```

The directory demonstrably existed. A 64-character content hash on a deep project path crosses the
260-character limit, and Windows reports that as `ENOENT`. **The most misleading error of the
build**, and the one that cost the most time to read correctly.

### task 10 — a handler that raised took the socket with it

```
http.client.RemoteDisconnected: Remote end closed connection without response
```

A failure with no message — which sends whoever is debugging to the network rather than to the
traceback. `do_POST` caught only `ServerError`.

### task 5 — the console could not show where work was dispatched

`dispatches` reached `RunReport.as_dict` but not the **server's** snapshot. "Chosen at random" is
only acceptable because the choice is visible afterwards, and visible has to mean *on the screen
somebody is looking at*.

### task 11 — the start button threw on first click

```
Uncaught TypeError: Cannot read properties of null (reading 'version')
```

It read `state.version` before any snapshot had arrived.

### task 15 — a stale token silently shadowed a fresh link

`sessionStorage` held the previous server's token, so a correct link produced a bare `401` — which
sends people hunting a server bug when the cause is a link opened without its fragment. The page now
distinguishes *refused* from *no token*.

---

## Found by the test suite, unprompted — 3, plus one intended collision

All three came from two tests that exist to catch a **class** of mistake rather than a specific one
— `test_nothing_is_unwired` and `test_documented_numbers`. Both earned their keep here.

The fourth entry below is **not a defect** and is not counted as one: it is a test colliding with a
rule the change was deliberately replacing. It was counted at first, which inflated the column in a
table whose whole point is comparing the groups. Both seats caught it.

### task 8 — a public constant nothing read

```
AssertionError: these exist and nothing in src/ uses them: ['models.py:REACHES']
```

I had defined the closed set of reaches and never validated against it.

### task 10 — the server had no way to be started

```
assert not ['server.py:serve']
```

`serve` existed with no caller. The fix was the `runner serve` subcommand — **the thing that made the
server reachable at all.**

### CHG-13 — four documents claimed 23 nodes after the graph reached 24

```
AssertionError: README.md says 23 nodes; the graph has 24
```

Recomputed from the graph, so it cannot drift. The change records and seat verdicts were
**deliberately left alone** — they are records of what was true when written, and rewriting them
would falsify the history this repository exists to keep.

### task 2 — a test asserted the rule the change was replacing

```
assert outcome["outcome"] == "fail"
E  AssertionError: assert 'undecided' == 'fail'
```

Not a defect — the intended collision. The record had committed to changing this test *"with a reason
written next to it, not because it turned red."* It turned red; the reason is in its docstring.

---

## My own process failures — 10

Kept because they cost real time and two of them are the same mistake the whole project is about.

### backslashes through a bash heredoc, three separate times

```
spec["instructions"] = (
    "
".join([own] + asked) …          # SyntaxError: unterminated string literal
```

`"\n"` arrives as a real newline. **I had this written down as a rule from an earlier session** and
broke it three times before switching to writing scripts to a file.

### the Status line said 3 tasks built while the table ticked 20

Precisely the recurrence the record was written to prevent, **inside the record written to prevent
it**. My sweep looked for a string that had already moved on, reported "status swept", and I believed
it. The count is now a reading of the State column, with a test asserting they agree.

### a button with no handler shipped

*"add to the brief"* sat in the markup for a whole change with nothing listening, because an edit that
should have added the handler failed silently and I did not check. There is now a test that reads the
page and asserts every button it draws has an `onclick`.

### I added a gate that could only ever be decoration

```
212 failed, 612 passed
```

`requirement_read` halting at every grade stopped every run. It was wrong not for the test count but
because **a gate firing on a complete requirement asks a person to approve the absence of a
problem**, and one that never fires is decoration — which `policy.py` says in as many words.

### I wrote a Status that would have needed a lie to support it

```
ledger check failed:
  - CHG-20260823-12: its status says the work is finished, but docs/acceptance/
    has no matching ACC
```

*"Built and driven"* reads as finished, and finished requires an acceptance record. Writing one would
have been false: **I verified it myself, and self-verification is the one thing acceptance is not.**

### the README omitted the failure paths — the same defect a seat found in the mock-up

`review_failed` and `acceptance_failed` were not in the flow diagram. Both are how a run recovers
from a panel or an acceptance saying no.

A seat had found exactly this in the mock-up — *"claimed 23 nodes, drew 18, and every omission was a
failure path, which is what a console is for"* — and I reproduced it three changes later **in a
document that quotes the finding**.

### a README example that would have run against a stub

```bash
runner serve --plan plan.json --port 8765     # no --config
```

`--config` is global and carries `agent_command`. Without it every ask goes to `_Stub` and **the run
completes having asked nobody**, which looks like success rather than like a usage error.

### and one correction of mine that was itself wrong

I recorded that `--seats N` did not exist. It does — it is an alias declared on the same line as
`--review-seats`. I had read `argparse`'s `--help`, which prints only the first option string per
action, and concluded the alias was fictional. **Trusting a tool's summary instead of reading the
source**, which is the same move as every other entry in this section.

### the README mislabelled the feedback node's branches

CHG-20260823-15 recorded this and I did not carry it here, while the README claimed this file records
*every* defect. Both seats caught the omission. `feedback` branches on `more`/`done`; the diagram
implied the node names.

### two fixtures used a proxy for the thing they meant

```
seat_verdicts applies to the **first** panel     # meaning: the review panel
```

A counter stood in for "the review panel". Adding `intake_review` made it the first panel and the
proxy broke — **a miniature of this project's whole recurring lesson**, in my own test double.

---

## Found by putting the README itself through review — 5

Two seats read `README.md` and this file at `d93fcd2` and split — `not sound` and `sound with
changes` — so it did not pass. Beyond the documentation errors listed above, the review found two
things in the **code**.

### a cross-origin check that compared prefixes

```
http://localhost.evil.example  -> ACCEPTED
http://127.0.0.1.evil.example  -> ACCEPTED
```

`origin.startswith("http://localhost")` is true of any domain an attacker registers under that
prefix. Found by a seat *reading* the check; confirmed by running it. **A prefix is not a host** —
the origin is now parsed and required to round-trip exactly.

### the fix for that check crashed on three of five CI jobs

```
ValueError: Invalid IPv6 URL
```

`urlsplit("http://[::1].evil.example")` **raises** under Python 3.9 and 3.13 and returns a hostname
under 3.11 on Windows — so the parsing fix passed locally and took down three jobs. A malformed
origin must be refused, not raise; which inputs raise is not something one interpreter can tell you.

### `halt_independent` enforces nothing

Graded on `acceptance` at high risk, and the README said *"the verifier must not be the builder"*.
`STOPPING` treats it identically to `halt`, there is one operator identity, and nothing records or
compares who confirmed. **The enforcement is the name of a constant.**

This is task 15's finding one layer down: independence was "enforced by a button caption", and the
fix moved the caption into a policy table. Now in *Known gaps* rather than stated as a property.

### a sentence disproved by the commit it shipped in

> *"Changes are reviewed by two independent seats **before they land**."*

CHG-20260823-14 and -15 — **the two changes that wrote that sentence** — were already merged, with
their own Status lines saying nobody independent had read them. A seat reading the reviewed commit
could disprove the claim from the repository itself, and did.

### a plan nobody could run

Both seats walked a newcomer's path and got stuck in the same place: the example was `jsonc` (so
`json.loads` rejects it), carried one node spec of the fifteen required, never mentioned the
`operations` block every acting node needs, and nowhere stated what a dispatched agent must print.
Fixed by shipping `examples/` — a plan that drives all 24 nodes and writes real code.

---

## Found by reviewing a design before its code existed — 14

CHG-20260823-17, the conversation store. The brief went to both seats against a tree with no store
code in it — the first time in this repository that the practice the README describes was actually
followed, one change after a seat struck the claim out for being false.

**Both returned `not sound`, and both named the same keystone sentence.** Not a split: unanimous.

### The design could not produce the document the design defined

> *"The `AskJournal` already writes every ask down… The store is therefore **derived**, not a second
> source of truth."*

Fourteen lines above it, the same brief had defined a conversation as asks **and operator
decisions** — *"a person answering is as much a turn as a model answering"*. The journal has never
held one: `record` and `answered` are its only two writers, and confirmations, rejections and
rulings reach only the in-memory `RunReport`.

I wrote both halves fourteen lines apart and did not notice.

### The journal destroys what it does hold

Confirmed by running it, not by reading:

```
two fresh runs, one journal directory  ->  entries: 1
what survives                          ->  {"brief": "SECOND RUN"}
run_id 1 == run_id 2                   ->  True
```

Ask ids are positional and `record` overwrites unconditionally. The first conversation is not stale
in the store — it is gone from the source the design proposed deriving from.

### A loopback host does not constrain a Mongo client

Both seats refused the analogy with `_loopback_origin`, and fable-seat gave the mechanism:
`MongoClient` performs **topology discovery**. Given a loopback seed that turns out to be a
replica-set member or a `mongos`, the driver reads the topology *from the server* and connects to
every member it learns of, including remote ones, without consulting the URI again.

A host check would have answered "local" about a URI while the driver went off-machine — the
coarse-check defect, in a feature whose entire premise is that the flow is local-only. The fix is
four URI rules **plus `directConnection=true` forced on the client**; only the last binds the
driver rather than the string.

### The ordering would have been inherited, and broken

```
sorted('%03d-x' % n for n in (99,100,101,999,1000))
['099-x', '100-x', '1000-x', '101-x', '999-x']
```

`AskJournal.entries()` sorts filenames. A store presenting "the ordered sequence of turns" would
have gone wrong at the 1000th ask, at a scale where a one-module demo looks fine — which is this
log's own most-repeated lesson.

### And ten more

`run_id` collides across runs and is not a filename; `--project` defaulting to a directory files
everything under *"examples"*; CSV formula injection (`=HYPERLINK(…)` in model-produced text); Excel
truncating silently at 32,767 characters; ``` inside an answer ending a markdown fence; a relaxation
with nowhere to record at export time, because `export` runs outside any walk; *"must not be
silent"* naming no mechanism; three backends guaranteeing nothing in common; `<root>/<project>/<run>`
repeating a hazard `attachments.py` already records; and the answering model appearing in no durable
record at all.

### The one the seats could not find

The Mongo rule shipped in my first draft with **the same hole CI had caught in `server.py` two
changes earlier**: `urlsplit("mongodb://[::1].evil.example")` returns host `::1` and drops the rest,
so the loopback set accepted a domain an attacker registers. A test written for that earlier finding,
pointed at the new function, failed on its first run.

I had written the correct check once already, in another file, two days before. A fix that does not
become a habit is a fix that gets to be found twice.

## Found by reviewing the code that answered the design — 11

Round 2 of CHG-20260823-17. Both seats returned `not sound` again, and **both named the same
function** — `local_mongo_uri`, the one written to answer round 1's finding about it.

### The check written to replace a coarse check was a coarse check

```
ACCEPT  mongodb://127.0.0.1/db?proxyHost=attacker.example&proxyPort=1080
ACCEPT  mongodb://remote.evil.sock
ACCEPT  mongodb://127.0.0.1/?replicaset=rs0
```

All three reproduced by running them. `proxyHost` keeps the seed loopback and routes the connection
through somebody else's SOCKS proxy — I had refused two option names and passed the rest to the
driver. `remote.evil.sock` is a registrable DNS name that my check called a unix socket because the
string ends `.sock`, and which therefore **skipped the loopback test entirely**: the check deciding
*whether* to apply the locality rule was itself the coarse one. And Mongo's options are
case-insensitive while my two refusals were not.

### "Must not be silent" was silent, on a path length this repository already has a constant for

A seat drove the real command with a store root crossing Windows' 260-character limit:

```
state:         finished
(no conversation file written at all)   exit 0
```

Every turn failed, the whole conversation was lost, and the run said `finished`. The design named
three channels for a failed write; the code had a list nobody printed. **Round 1 had found exactly
that defect in the design** — a sentence naming no mechanism — and the code answering it shipped a
field naming no mechanism.

The test guarding it asserted that a dict key existed and called that "never silent".

### Nine more

The ask recorded before the session opened, so three of the four ways an ask can fail left no
outcome beside it; a seat panel's answers recording `model: None` because seats route by name;
`cmd_export` not recording its own relaxation, which was *the* case round 1 raised; a project name
interpolated raw into a markdown header, forging a heading; a formula behind a newline emitted
undefused; a uniqueness guarantee two of three backends did not keep; and a resume that adds
`--project` storing none of what the journal already answered.

### What this group is for

Nothing here was found by the test suite, which was green at 901 passing throughout. Two of the
eleven are this log's own two most-named defects, reproduced **inside the functions written to fix
them one round earlier**. A fix that does not become a habit gets found twice, and this is the page
where that keeps being written down.

## What the grouping says

The four groups are not equally useful, and the difference is the point of keeping this file.

**The seats found things that did not exist yet.** Thirteen defects in records and claims, caught by
reading — including the two that would have made whole tasks into no-ops that went green. No test
could have caught any of them, because there was nothing to run.

**Running it found things no test had.** Nine defects, several of which had been shipping for
changes, and every one invisible to a suite that was passing 800+ at the time. The pattern in all
nine: **a one-module, one-instruction, one-server demo had the same bug and looked fine.** Scale and
repetition are what made them visible, not cleverness.

**The two class-catching tests earned their keep.** `test_nothing_is_unwired` and
`test_documented_numbers` do not know about any particular defect; they know about a *shape* of
mistake. Three of the four suite-caught defects came from them.

**My own failures cluster around believing a report instead of checking one.** The heredoc, the
sweep that said "swept", the edit that failed silently — each is the same move: taking a tool's word
for an outcome I could have verified in one command.
