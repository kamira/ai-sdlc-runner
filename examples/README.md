# Examples

Three, and they answer different questions. Each has its own README; this page is only the way in.

| | what it shows | read |
|---|---|---|
| **minimal** | the smallest plan this runner accepts, and the **answer contract** — which node must answer what | [`minimal/README.md`](minimal/README.md) |
| **tide-spa** | one brief run five times, each differing by a single field, to show **where a run stops and why**. A real single-page app comes out of the first one | [`tide-spa/README.md`](tide-spa/README.md) |
| **weather-spa** | the **console** path: a brief typed by a person, a gate approved by clicking, and the refusals that only exist there | [`weather-spa/README.md`](weather-spa/README.md) |

Read them in that order if you are new to this. Each assumes the one before it.

## Running them

```bash
python3 -m ai_sdlc_runner.cli --config examples/minimal/runner.yaml run --plan examples/minimal/plan.json --risk low
```

```bash
python3 examples/tide-spa/scenarios.py
```

```bash
python3 examples/weather-spa/scenarios.py
```

The two scenario drivers write nothing into the repository: each run gets its own temporary
directory, and `weather-spa` also gets its own port and its own server, stopped again afterwards.

## The pages they build

[`demo/index.html`](demo/index.html) — the products, each inlined into one self-contained file.

They are **generated from the agents that build them**, by `demo/build.py`, and the suite
regenerates and compares. A demo page copied by hand is a screenshot with an `.html` extension; it
goes stale the first time the agent changes and nothing notices.

```bash
python3 examples/demo/build.py
```

## What the three have in common

Every example here is driven end to end against the real runner, and every number in every README is
a measurement rather than a claim — `tests/test_example_tide_spa.py` and
`tests/test_example_weather_spa.py` run the drivers and check them. A README is the one place in
this project where something can quietly stop being true.
