## Recording correction directives (req 3)

When you receive a user correction (not a requirement change), **write it into the knowledge base immediately**, not just fix it in the moment:

```markdown
## DIR-<n> — <one-line rule>
- date / branch: YYYY-MM-DD (UTC+0) / <branch>
- context: <when it applies>
- rule: <do / don't>
- reason: <why (user's reason or inferred)>
- confidence: user-confirmed / agent-inferred   ← who established the rule (see priority below)
- status: active
```

