## Dispatching build and review to different models

`--review-cmd` points the per-task review at a **different command — and therefore a different model — from the builder**. Without it the review falls back to `--agent-cmd`, i.e. builder and reviewer run on the same model, which shares one set of training biases and blind spots (certain errors get missed *systematically, together*). The fallback is **announced, never silent**, so a round's independence is never overstated.

The runner stays no-LLM: it does not parse model names. Which model each command reaches is written into the command template by whoever runs it. Model choice per role follows ai-sdlc `agent-hierarchy` "Choosing a model per dispatch" — judgment density, independence need, cost.

```
runner build|run --chg <CHG.md> --repo . --agent-cmd '<builder>' --review-cmd '<reviewer>'
```

