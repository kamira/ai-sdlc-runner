## The dual verdict (one read, one pass)

Judge both in a single reading of the diff:

- **spec** — does the diff deliver the task's `interfaces:` and satisfy its `test:` line? (`pass` / `fail` / `cannot-verify` — the requirement lives outside this diff; a legitimate outcome, not a failure)
- **quality** — idioms of the surrounding code, no drift beyond the task's scope, no weakened tests, no secrets. (`pass` / `fail`)

Output exactly one verdict line (the runner parses it):

```
[task-review] T<n> | spec: pass|fail|cannot-verify | quality: pass|fail | <one-line reason>
```

