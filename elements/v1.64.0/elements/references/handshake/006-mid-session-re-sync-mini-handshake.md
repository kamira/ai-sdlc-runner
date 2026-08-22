## Mid-session re-sync (mini-handshake)

The full handshake happens at entry — but long sessions lose context to compaction, and "the docs are the truth" only holds if you actually re-read them. Re-read the Guideline + the active CHG (+ knowledge when directives are in play) and emit a 2-line mini-ack:

```
[re-sync] CHG-…: step <n>/<m> done; branch <b>; next: <one line>
constraints re-confirmed: <key knowledge / guideline points / none>
```

Triggers: **every autonomy gate**; **before starting acceptance**; **on signs of compaction** (you can't precisely recall an earlier decision — don't guess from memory, re-read); and periodically in long sessions (suggest every ~20 turns).

