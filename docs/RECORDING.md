# Recording the work

Three recordings, answering three different questions. They are not substitutes for each other, and
the reason to have all three is that each one is silent about what the others show.

| | question it answers | made by |
|---|---|---|
| **Terminal session** | what was actually run, and what came back | `tools/session_record.py` → `tools/render_cast.py` |
| **Run replay** | what the runner did, node by node, and how long each took | `runner export --format playback` |
| **Worklog** | why — what was decided, on what evidence, and what was rejected | written, in `docs/worklog/` |

A terminal capture shows a test failing but not why that test existed. A replay shows a node halting
but not the six commands it took to reproduce. A worklog claims both and proves neither. Together
they are reviewable; separately each is an argument you have to take on trust.

---

## 1 · The terminal session

Wrap any command:

```bash
python3 tools/session_record.py --cast-dir docs/recordings/chg-34 --title "the suite" -- python3 -m pytest tests/ -q
```

It runs the command, passes the output through to your terminal unchanged, and writes one `.cast`
file — a JSON header line then one `[seconds, "o", text]` array per chunk. The shape is asciinema's
v2, deliberately: a format that already exists and can be read by tools that know nothing about this
repository. The *player* is ours, because an external one would be a network fetch.

Then render the directory:

```bash
python3 tools/render_cast.py docs/recordings/chg-34 -o docs/recordings/chg-34.html --title "CHG-34"
```

One page, self-contained, with a step list, a scrubber and a keyboard (`space`, `←`, `→`).

### Two things it does on purpose

**It forces the child unbuffered.** Python line-buffers to a terminal and block-buffers to a pipe,
and a recorder is always a pipe. Left alone, a script that printed steadily for two minutes records
as a single event at the end — every timing gone. Forcing unbuffered changes the child's behaviour
to bring the recording *closer* to what a person at the terminal would have seen.

**It compresses waiting, and says so.** A gap over two seconds plays as two seconds with a marker
naming the real duration. Played at true speed a session is unwatchable; cut silently, a review
cannot tell a slow failure from a fast one.

### What it does not record

Input. There is no pty, so this records what a command *emitted*, plus the command line itself.
`runner` is non-interactive by design and the one place a person acts is a gate — which is recorded
in the conversation store, where it belongs.

---

## 2 · The run replay

```bash
python3 -m ai_sdlc_runner.cli export --project NAME --conversation ID --format playback -o run.html
```

The fifth export format. `json` is lossless, `markdown` reads as a transcript, `csv` is the lossy
one, `html` is a waterfall you scan — and `playback` is the one you press play on.

The left rail is the flow, one entry per **stop**: consecutive turns at one node. A node revisited
is a second stop, so the module loop shows as `visit 2`, `visit 3`. It lights up as the replay
reaches it. The stage accumulates turns with the three voices marked apart — what the runner asked,
what the model answered, what a person decided.

`playback` and `html` share `_stops()`. Two renderings of one run disagreeing about where a stop
begins would make both untrustworthy, and a test asserts they agree.

### The clock is legible, not literal — and says which

Two adjustments, both named on the page itself:

- **A turn plays for at least 0.35s** however fast it really was. The first real export was 3
  seconds for 55 turns: strictly accurate, and unwatchable. The floor compresses the *ratio* rather
  than erasing it — a 40-second seat still lands six times longer than its neighbour.
- **A pause over 2s plays as 2s**, with the real figure shown.

A turn whose timestamp will not parse gets a beat, not an invented duration. `_seconds` returns
`None` rather than "now": a replay whose whole claim is that the timings are real must not
manufacture one.

### Model text goes into a script block, so it is escaped for one

`<`, `>`, `U+2028` and `U+2029` are escaped at the JSON level. The waterfall escapes for markup
because that is where its text lands; this lands inside `<script>`, where a literal `</script>` in
an answer ends the block early and everything after it parses as page content. A model writes that
sequence the moment it is asked about HTML — which the tide example does.

---

## 3 · The worklog

`docs/worklog/CHG-<id>.md`, written as the work happens rather than assembled afterwards.

What belongs in it is what the other two recordings cannot show:

- the question asked of the review panel, and each seat's verdict **in full**
- where the seats disagreed, and what evidence settled it — never an average
- what was tried and abandoned, with the reason
- every defect found in the change's own work, including the ones found by a test failing on
  correct code

What does not belong: a narration of the commands. Those are in the cast, timestamped, and a prose
retelling of them is a second version that can disagree with the first.

---

## Where recordings live

`docs/recordings/<change-id>/` for the casts, `docs/recordings/<change-id>.html` for the rendered
page. Casts are small — text and floats — but a suite run is a few hundred KB, so record the steps
that carry the argument rather than every command.
