## Declaring it

```markdown
### Interaction spec
- kind: gui-web
- cmd: python tools/ui_check.py
- artifacts: artifacts/home.png, artifacts/trace.zip
```

Multiple entries are allowed — declare one per surface. An exemption must carry a reason:
`Interaction-spec: n/a (one-off migration script, not reused)`. **An empty exemption is treated
as no declaration at all** — it would otherwise look like an answer while being none.

