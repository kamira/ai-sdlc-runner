## Live handshake (always written, always current)

The ack is not just spoken into the conversation — **it is a file, and it stays current**. On entry, write the ack to `docs/worklog/handshake-<agent-id>.md`; **update it at every step boundary** (the moment a step completes, together with that step's durable write):

```
branch/role/scope: <…>
doing: CHG-… step <n>/<m>
next: <one line>
last-updated: YYYY-MM-DD HH:MM (UTC+0)
```

This is the last-act discipline applied to the handshake itself: an interruption at **any** moment finds the file current, and the next session's entry handshake reads it as the exact resume point — no reconstruction, no guessing. Solo sequential work keeps one file; parallel agents keep one each (same worklog conventions: archive on close).

