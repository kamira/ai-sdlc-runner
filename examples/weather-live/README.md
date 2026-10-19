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
| what is in the directory | an agent, a plan, a `runner.yaml`, scenarios | **only what a person gives the runner**: a brief, a plan, a `runner.yaml` |
| what the suite runs | all of it | what the repository holds; never the real backend |

**There is no `agent.py` here and no page code written in advance.** The runner builds the page: it
is whatever a real run produces in `site/`. Nothing under this directory is a `.js` or `.html` file,
and a test says so.

## What is here

| file | what it is |
|---|---|
| `brief.md` | what a person types into the console: the page, the data sources, the ten modules, the limits |
| `plan.json` | the plan `runner serve` is started with — 24 node specs and their operations, derived from `weather-spa`'s |
| `runner.yaml` | the real backend: `claude -p`, `claude-sonnet-5-5`, effort `medium`, and only the tools a build needs |
| `drive.py` | the person at the console, as a script: types the brief, starts, approves each gate, waits |
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
confirmed here**. They are checked against the API's documentation and a live call at the measurement
(CHG-20261019-01, task 1a). If the API cannot be called from a page, the CWA is left out and the
record says so, rather than adding a server that would hold the key.

### The recorded response

`fixtures/open-meteo-taipei-2026-10-19.json` is a **real** response from `api.open-meteo.com`,
recorded 2026-10-19 10:10 UTC with the query above. At 18:00 Asia/Taipei it reports 27.9 °C and 75 %
humidity, 7 daily entries and 168 hourly ones. It exists so the built page can be opened **offline**
and its numbers compared with a known response (labelled as a recording, with its date). It is a
fixture, not a fallback: the page itself must never ship numbers.

## How `plan.json` differs from `weather-spa`'s

Same 24 node specs, the same `operations` and the same `decisions` (`next_module: frontier`,
`feedback: done`), at `risk: low`, so the run stops for a person only where `weather-spa`'s does — at
`merge`. What changed is text in the specs:

- **scope, objective, done criteria, acceptance predicate, expected outputs** name ten files, the
  live data and the error state, where `weather-spa`'s say "four modules" and "no network request of
  any kind".
- **`instructions`** adds that the brief carries the ten modules and the no-key rule.
- **`pm_plan`** is told to declare the brief's ten file names, in order, as `modules`.
- **`engineer_build`** is told to build the first file in the brief's list that does not yet exist and
  answer with its name, or `{"module": ""}` when all ten do. A scripted agent knows its own order; a
  real model has to be told it, and the runner's frontier needs the name.
- **`fix_pass`** is told to fix only what the review named.

## `runner.yaml`

`claude -p --model claude-sonnet-5-5 --effort medium`, on every node, so the time of one ask is
comparable with another's. `Write Edit Read Glob Grep` are pre-granted — nobody is at the keyboard to
approve more — and `Bash`, `WebFetch` and `WebSearch` are refused explicitly: a work order asks for a
file and an answer, and the page fetches its own data. `agent_timeout: 1800` is the ceiling for one
ask; `agent_retries: 0` so a measured run counts each ask once. The file comments say why of each.

## Run it

```bash
python3 examples/weather-live/drive.py --keep-serving
```

From anywhere. It copies `plan.json`, `runner.yaml` and `brief.md` into a new temporary directory
(`--workdir` chooses another), starts `runner serve` there on a free port, types the brief, starts the
run and approves each gate it stops at. It prints a line per node with the UTC time, then the run id,
the final node and where `site/` is. With `--keep-serving` it stays up and prints the console URL and
the **path** of the operator token file (never the token), so the run can be watched in the console.

| option | |
|---|---|
| `--runner-yaml PATH` | build with another backend |
| `--workdir DIR` | run in `DIR` |
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
