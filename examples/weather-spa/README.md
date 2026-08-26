# The weather example — driven through the console

`examples/tide-spa` drives `runner run` from a plan file. This one starts `runner serve` and talks
to it the way the **operator console** does: a brief typed into a box, a gate approved by clicking a
button.

That difference is the whole point. A CLI run has no operator in it — nothing a person typed exists
in the record, and the conversation is only ever the model's half. Everything below only happens on
the console path.

```bash
python3 examples/weather-spa/scenarios.py
```

Each scenario gets its own temporary directory, its own free port and its own server, stopped again
afterwards. Nothing is written into the repository.

## What is here

| file | what it is |
|---|---|
| `plan.json` | the plan `serve` is started with — 24 node specs, the operations, the branch decisions |
| `agent.py` | the model the runner dispatches to. It builds a real page: seven days, current conditions in the middle, today's curve. No network call, at build time or in the page |
| `runner.yaml` | two lines: the agent command and a timeout |
| `scenarios.py` | five runs against a live server, each one something that really happened while building this |

## The five runs, measured

| | what it does | outcome |
|---|---|---|
| **A** | types the brief, clicks `start the run`, then `approve merge` | four files built; `finished` at `done` |
| **B** | uses `start the run` for a *follow-up* instead of `add to the brief` | the first instruction is **replaced**, not appended — 1 instruction, not 2 |
| **C** | an agent that picks the next module by which file is missing | `walk exceeded 200 steps — the flow is cycling without progress` |
| **D** | a request with no operator token | shell `200`, every route behind it `401` |
| **E** | a `Host` header that is not loopback, and a cross-origin `Origin` | `403` and `403` |

---

## A · the brief, typed into the console

```
做一個當地一週氣象的單頁網站，地點台北。七天預報要有每天的最高溫、最低溫和降雨機率；
中間要顯示現在天氣，包含現在氣溫和濕度。不要連外網。
```

Walks to `merge` and stops. The page then shows a button reading **`approve merge`** — `merge` is
one of the six kinds never automated, so the run does everything up to it and hands over. Clicking
it finishes the run.

The instruction is recorded as a turn of its own. That is what makes the conversation two-sided:
`runner export --format playback` replays it with what a person typed marked apart from what the
model answered.

Note what every call carries. The server refuses a mutating request that does not name the version
it is answering — *"without it two tabs cannot be told apart, and a double-click spends two
approvals"* — so `Console.act` reads the version immediately before each call, exactly as the page
does.

## B · the two buttons are not the same button

The console has `start the run` and `add to the brief`, and they are different verbs on different
routes: `POST /run` and `POST /run/instruct`.

Using the first for a follow-up **replaces** the brief. Measured:

```
after the first instruction:        1
after `start the run` again:        1     <- not 2
after `add to the brief`:           2
```

This is here because it happened: the first time this project was driven, a second instruction went
in through the wrong button and the original silently vanished from the record. Nothing failed and
nothing warned — it was only visible by reading the conversation afterwards and counting.

It is not filed as a defect. Both verbs are legitimate and the labels say which is which. It is
filed as the thing to check first when a conversation has fewer instructions than you typed.

## C · an agent that cannot tell "done" from "done again"

The agent in this scenario picks the next module by asking **which file does not exist yet**:

```python
nxt = next((m for m in ORDER if NAMES[m] not in have), ORDER[-1])
```

That works exactly once. On a second walk all four files exist, so it answers with the last module
forever, `next_module: frontier` never advances, and the flow goes round.

```
EngineError: walk exceeded 200 steps — the flow is cycling without progress
```

**The step cap is what ends this, not a timeout.** A timeout would have reported a slow run; this
reports the actual shape of the failure, and it is the runner catching a bug in the thing it was
driving rather than in itself.

`agent.py` in this directory does it the other way — it compares content, so a rebuild touches
exactly the modules whose content should change and reports when none should:

```python
if path.exists() and path.read_text(encoding="utf-8") == body:
    continue
```

## D · a request with no operator token

```
shell:  200
/run:   401  — no operator token. It is in .runner\operator.token, readable by you alone.
```

The shell is served without one on purpose, and the reason is in the guard's own comment: *nothing
can present a token before it has loaded the page that stores one.* It is still loopback-checked.
Everything behind it is token-checked.

## E · a `Host` header that is not loopback

```
Host: weather.attacker.example   -> 403  this server answers only to a loopback host
Origin: http://evil.example      -> 403  cross-origin request from http://evil.example refused
```

The socket is bound to loopback, so a name that resolves to `127.0.0.1` reaches it anyway — DNS
rebinding. The `Host` header is the only thing that says which name was asked for, and it is checked
**first, before anything is parsed**: a request that should not be understood does not get as far as
being understood.

---

## Seeing the conversation afterwards

```bash
python3 -m ai_sdlc_runner.cli conversations --store-root <workdir>/conv --project "一週氣象 Taipei"
```

```bash
python3 -m ai_sdlc_runner.cli export --store-root <workdir>/conv --project "一週氣象 Taipei" --conversation <id> --format playback -o run.html
```

`playback` is the format worth using on a console-driven run: the three voices come apart, and the
operator's turns — the instructions typed and the gates approved — are the ones a review is looking
for. See [`docs/RECORDING.md`](../../docs/RECORDING.md).
