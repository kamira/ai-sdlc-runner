# Examples

Two, and they answer different questions.

| | what it shows |
|---|---|
| **[`plan.json` / `agent.py`](.)** — the minimal one | the smallest plan the runner accepts: one module, `greet(name) -> str`. Start here to see the shape of a plan and what an agent has to return |
| **[`tide-spa/`](tide-spa/)** | one brief run five times, each differing by a single field, to show **where a run stops and why**. A real single-page app comes out of the first one |

The minimal example:

```bash
python3 -m ai_sdlc_runner.cli --config examples/runner.yaml run --plan examples/plan.json
```

The five-scenario one, which writes nothing into the repository:

```bash
python3 examples/tide-spa/scenarios.py
```
