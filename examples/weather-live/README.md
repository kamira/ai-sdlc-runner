# The live weather example — built by the runner, with a real model

> **This one spends model quota.** Read [the cost](#cost) before running it.

`examples/weather-spa` builds a one-week Taipei weather page with a **scripted** agent and no network,
on purpose: its numbers are generated, its five scenarios are about the console, and every figure in
its README is a measurement the suite repeats. This example is the other half.

|  | `weather-spa` | `weather-live` |
|---|---|---|
| who writes the page | `agent.py`, scripted | a real model (`claude-sonnet-5-5`, effort `medium`) through `runner.yaml` |
| the numbers on the page | generated, labelled as a sample curve | **fetched by the page in the browser at run time** |
| modules | four | ten |
| what is in the directory | an agent, a plan, a `runner.yaml`, scenarios | what a person gives the runner (a brief, a plan, `runner.yaml`, `models.json`), `drive.py` to drive `serve` as an operator does, and a recorded response in `fixtures/`; **no agent and no page code** |
| what the suite runs | all of it | what the repository holds; never the real backend |

**There is no `agent.py` here and no page code written in advance.** The runner builds the page: it
is whatever a real run produces in `site/`. Nothing under this directory is a `.js` or `.html` file,
and a test says so.

## What is here

| file | what it is |
|---|---|
| `brief.md` | what a person types into the console: the page, the data sources, the ten modules, the limits |
| `plan.json` | the plan `runner serve` is started with — 24 node specs and their operations, derived from `weather-spa`'s |
| `runner.yaml` | the real backend: `claude -p`, `claude-sonnet-5-5`, effort `medium`, **read-only** (`Read Glob Grep`) |
| `models.json` | one model, `sonnet-writer`: the same command plus `Write Edit`, given to `engineer_build` by `plan.json`'s `node_models` |
| `drive.py` | the person at the console, as a script: types the brief, starts, approves each ordinary gate, hands any stop that needs a person to them, waits |
| `fixtures/open-meteo-taipei-2026-10-19.json` | a real Open-Meteo response, see below |

## The brief

Taipei (25.0330°N 121.5654°E): the current temperature and humidity in the middle, seven days of
high, low and rain chance, and today's hourly temperature curve — with data the **page** fetches in
the browser, not the runner and not its model.

- **Default source: Open-Meteo**, `https://api.open-meteo.com/v1/forecast`, which needs no key.
- **Optional source: the Central Weather Administration (CWA) open-data API only** —
  `https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-D0047-063` (forecast) and `O-A0003-001`
  (observation, station `466920`). It is used only when a person types an authorisation key into a
  password field on the page.
- The page says **which source** the numbers came from and **when** they were fetched.
- A failed request shows a visible **error state naming the source**. It never shows made-up or
  fallback numbers.

### The ten modules

Built one at a time, so the module loop really runs ten times. Each is one file under `site/`:

| # | file | holds |
|---|---|---|
| 1 | `index.html` | the page shell: sections, script tags, the place that says source and time |
| 2 | `styles.css` | layout and style, including the loading and error looks |
| 3 | `sources.js` | the two sources' names, URLs and parameters, and the choice between them |
| 4 | `openmeteo.js` | the Open-Meteo request, returning its raw response |
| 5 | `cwa.js` | the CWA request, reading the key from localStorage, returning its raw response |
| 6 | `normalize.js` | one common shape from either response, and number and time formatting |
| 7 | `now.js` | the middle panel: current temperature and humidity |
| 8 | `week.js` | the seven-day list: high, low, rain chance |
| 9 | `chart.js` | today's hourly temperature curve |
| 10 | `app.js` | the entry point that wires the rest, with the loading and error states |

`pm_plan` answers with the list it actually plans; if it is not ten, that is what was built.

### The CWA key

**No key is ever in a file.** The person running the page types it into a password field; the page
keeps it in that browser's `localStorage` and nowhere else. A test fails the suite if anything under
this directory looks like a CWA key (`CWA-` followed by twenty or more hex characters or dashes).

The CWA's response shape and whether the API answers a browser's cross-origin request are **not
confirmed here**. The measurement (CHG-20261019-01, task 1a) happened, but no key reached that
session, so the CWA was neither confirmed nor left out: `cwa.js` was built from the API's
documentation and has not been run against a live response. A person with a key is the check.

### The recorded response

`fixtures/open-meteo-taipei-2026-10-19.json` is a **real** response from `api.open-meteo.com`,
recorded 2026-10-19 10:10 UTC with the query above. At 18:00 Asia/Taipei it reports 27.9 °C and 75 %
humidity, 7 daily entries and 168 hourly ones. It exists so the built page can be opened **offline**
and its numbers compared with a known response (labelled as a recording, with its date). It is a
fixture, not a fallback: the page itself must never ship numbers.

## How `plan.json` differs from `weather-spa`'s

Same 24 node specs, the same `operations` and the same `decisions` (`next_module: frontier`,
`feedback: done`), at `risk: low`, so the run stops for a person only where `weather-spa`'s does — at
`merge`. What changed is text in the specs, and **each node's spec says what that node judges or does
at its stage of the flow**.

### Why `weather-spa`'s single shared spec does not carry over

`weather-spa` gives every node the same spec — the whole change's scope, done criteria and acceptance
predicate — because its scripted agent never reads it. A real model does. In run 3 `pm_signoff`, the
plan's sign-off gate and the fourth node of the flow, was handed "all ten files exist and parse", found
`site/` empty, and answered no, twice; the walk cycled `pm_plan → pm_confirm → lead_assess →
pm_signoff → pm_plan` and never reached a build. The node had done what its order said. Nothing in
the runner attaches an earlier node's answer to a later order (an order carries its own spec,
`input_artifacts` and, on a re-ask, the reason the run came back), so `pm_signoff` also never sees
`lead_assess`'s answer, and its spec says so rather than asking it to judge one.

### One spec per stage

| stage | nodes | what the spec asks | `acceptance_predicate` | `expected_outputs` |
|---|---|---|---|---|
| plan | `intake`, `intake_review`, `pm_plan`, `pm_confirm`, `lead_assess`, `pm_signoff` | judge **the plan**: the ten-module list, its order, its scope and the data rules. Nothing is built, so an empty `site/` is expected. `pm_plan` declares the ten file names, in order, as `modules`; `lead_assess` judges feasibility and risk; `pm_signoff` judges the plan itself and is told no assessment is attached | the plan names the ten modules, in order, and keeps the data rules | none |
| module | `next_module`, `engineer_build`, `engineer_selfverify`, `lead_task_review`, `record_module`, `fix_pass`, `re_review`, `halt_second_fail` | **one module**. `engineer_build` builds the first file in the brief's list that does not yet exist and answers with its name (`{"module": ""}` when all ten do); the others check, review, fix or re-review the module just built | that module exists under `site/`, parses, holds no key, requests only the two hosts | `engineer_build`: the one module in hand; the rest: none |
| whole change | `lead_review`, `review_failed`, `qa_verify`, `qa_accept`, `acceptance_failed`, `pr`, `merge`, `close_out`, `feedback`, `done` | judge **the built page** against the full predicate | all ten files exist and parse, no file holds a key, only the two hosts, an error state with no made-up numbers | the ten files |

Every spec keeps the brief's rules (no key in any file, no made-up or fallback numbers), and every node
but the build, `engineer_selfverify` and `fix_pass` ends with "Do not create or change any file."
`fix_pass` fixes only what the review named. Tests read these specs through the runner's own plan
loader: no node before the module loop asks for a `site/` file, `engineer_build` names one module, and
the whole-change nodes name all ten.

## `runner.yaml`

`claude -p --model claude-sonnet-5-5 --effort medium`, on every node, so the time of one ask is
comparable with another's. The default command is **read-only**: `Read Glob Grep` are granted, and
`Write`, `Edit`, `Bash`, `WebFetch` and `WebSearch` are refused by name — a work order asks for a
file and an answer, and the page fetches its own data. `agent_timeout: 1800` is the ceiling for one
ask; `agent_retries: 0` so a measured run counts each ask once. Both commands end in
`--output-format json`: claude then prints its cost and tokens in an envelope, which the runner records
as each ask's usage and unwraps back to the model's answer text. **The measured runs (run 4 and before)
ran without the flag, which is why their spend was not recorded.** The file comments say why of each.

### Who can write

`models.json` holds `sonnet-writer`: the same model and effort, plus `Write Edit`. `plan.json`'s
`node_models` gives it to `engineer_build` (a pool of one), and `drive.py` copies `models.json` to
`models.json` in the state directory (below), where `serve` reads it. Every other node uses the
read-only default, and each node's spec says so: `engineer_build` builds only the first missing file
and touches no other; every other node, one line, must not create or change a file.

`fix_pass` and `engineer_selfverify` are `follows engineer_build` in the runner's flow, so the engine
dispatches them with the model that answered the build, which is `sonnet-writer`. They can write.
**`engineer_selfverify` is the known exception to "only build nodes write"**: its spec says it may
only correct the module just built and must not create another file, but nothing stops it. It cannot
be closed from here, because a `follows` node takes the build's model (`engine._followed_model`) and
`node_models` is not consulted for it; closing it takes a change in `src/`. So it is *measured*
instead: `docs/measurements/CHG-20261019-01/measure.py WORKDIR --state-dir STATE` has a "writes" check that attributes
each file under `site/` to the ask whose interval holds its modification time and flags any file
written by a node other than `engineer_build`/`fix_pass`, or by `engineer_selfverify` for a file
other than the module its build just built.

**What the boundary is.** The tool list, not paths. `Read`, `Glob` and `Grep` reach anything the
process user can read, and `Write`/`Edit` (on `sonnet-writer`) are not scoped to a path unless the
runner's sandbox (bwrap) confines the process. Without it, the person directory being outside the
workdir rests on `claude`'s own permission behaviour for a write outside its start directory, which
this change did not test. That is why `drive.py` refuses a `--workdir` that is
not empty, and why the end of its output says whether the asks ran unsandboxed.

`--models PATH` chooses another registry; with no `models.json` beside `--runner-yaml`, the plan's
`node_models` are dropped and `agent_command` answers every node.

## Run it

```bash
python3 examples/weather-live/drive.py --keep-serving
```

From anywhere. `--workdir` (default a new temporary directory; must be new or empty, or it is refused and
nothing is copied) is where `serve` runs and the page is built. Everything else `serve` reads or writes is in
a **state directory outside the workdir**, printed once at the start: it copies `plan.json`, `runner.yaml`,
`models.json` and `brief.md` there, and `serve` keeps `settings.json` (re-read at every walk), the operator
token, `config.sqlite`, `attachments/`, the conversation store `conv/` and the ask journal `asks/` there too,
because the build model can write inside the workdir and must not be able to change them. `--state-dir`
chooses it and is refused if it is inside the workdir. It starts `runner serve` on a free port, types the brief, starts the
run and approves each ordinary gate it stops at (`merge`). A stop that needs a person to read something
(a seat called the requirement unsafe, an incomplete requirement, a tied panel) is never answered by the
script: it writes the server's text to `<NNN>-<node>.md` in a new temporary directory **outside the workdir** (the build
model can write inside it, so it must not be able to answer; the path is printed at start), prints
`AWAITING-PERSON <path>` and waits for `<NNN>-<node>.proceed` (or `.stop`) beside it. `--person-dir` chooses
the directory and is refused if it is inside the workdir; a `.proceed` that exists before the stop is
written is refused, not taken as the answer. `--on-node` is split like a shell command line, so quote a path with spaces (on Windows one pair of surrounding quotes is stripped from each token); a hook that cannot start is reported on one line and the walk goes on. It prints the server's own startup lines (how many models are registered and how many leave this machine; the
token line is left out) and a line naming the program each work order goes to (`agent_command: claude — leaves this
machine`). It prints a line per node with the UTC time, then the run id,
the final node, where `site/` is, and the conversation's `relaxation` turns (the engine records
"N ask(s) ran unsandboxed" there) or `no relaxation recorded`. With `--keep-serving` it stays up and prints the console URL and
the **path** of the operator token file (never the token), so the run can be watched in the console.

| option | |
|---|---|
| `--runner-yaml PATH` | build with another backend |
| `--models PATH` | the registry `node_models` names (default: `models.json` beside `--runner-yaml`) |
| `--workdir DIR` | run in `DIR`, which must be new or empty |
| `--state-dir DIR` | where `serve` keeps its settings, token, stores and journal; must be outside `--workdir` |
| `--keep-serving` | stay up after the end |
| `--on-node CMD` | run `CMD <node-id> <utc-time>` on every node change, e.g. to take a screenshot |
| `--dry-run` | check the plan, `runner.yaml` and brief, start nothing, spend nothing |

Node changes come from the ask journal, which records each question before it is asked; runner nodes
that ask nobody (`next_module`, `module_built`, …) leave no line there, and are counted in the final
`nodes walked`.

Then open `site/index.html` in a browser. It needs the network, to reach Open-Meteo.

## Cost

A ten-module run is about 44 asks (`CHG-20260827-21`, task 6), each one `claude -p` session. At
`claude-sonnet-5-5`, effort `medium`, on a small repository that is roughly $0.10–$0.40 per session at
API-equivalent prices, so **about $5–$20 and well under an hour**. On a subscription it draws on the
same account quota the review panels use.
