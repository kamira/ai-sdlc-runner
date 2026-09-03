"""Record a command and what it actually printed, so the work can be watched afterwards.

    python3 tools/session_record.py --cast-dir docs/recordings/chg-34 -- pytest tests/ -q

Runs the command, streams its output through to your terminal unchanged, and writes a *cast* — a
timestamped record of every chunk that came out. `render_cast.py` turns a directory of casts into a
page you can press play on.

## Why not just keep the log

A log tells you what happened. A cast tells you **when**, and the gaps are most of the information:
a suite that goes quiet for ninety seconds and then fails is a different thing from one that fails
immediately, and a review that cannot see the pause cannot tell them apart.

## One cast per command, not one per session

Appending every command to a single growing file needs a lock the moment anything runs
concurrently, and a half-written event at the end of a killed process corrupts the whole session
rather than one command. A directory of small files has neither problem, and the renderer puts them
back in order by name.

## What is not recorded

Input. There is no pty here — on Windows there is no pty at all — so this records what the command
*emitted*. The command line itself is **not** an event: it is `header["command"]`, which
`render_cast.py` reads and shows. This said "as the first event", which invites emitting it into
the stream — and that would print it **twice** on every rendered page (CHG-20260903-43). A session where someone types into a
prompt is not something this can capture, and it does not pretend to: `runner` is non-interactive by
design, and the one place a person acts is a gate, which is recorded in the conversation store where
it belongs.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: Cast format version. Deliberately the asciinema v2 shape — a JSON header line then one JSON
#: array per event — because it is a format that already exists, is documented, and can be read by
#: tools that have nothing to do with this repository. The player here is our own (an external one
#: would be a network fetch), but the *data* is not a private invention.
VERSION = 2

#: Chunk reads. Small enough that a slow trickle of output is recorded as a trickle rather than
#: arriving as one lump when the pipe buffer flushes.
CHUNK = 4096


def _slug(argv, limit=48):
    text = "-".join(argv)
    keep = [c if (c.isalnum() or c in "-_.") else "-" for c in text]
    out = "".join(keep).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return (out[:limit] or "command").rstrip("-")


def _next_index(cast_dir: Path) -> int:
    existing = [p.name for p in cast_dir.glob("*.cast")]
    numbers = [int(n.split("-", 1)[0]) for n in existing if n.split("-", 1)[0].isdigit()]
    return max(numbers) + 1 if numbers else 0


def record(argv, cast_dir: Path, title=None, note=None, cwd=None):
    """Run `argv`, tee its output, and write the cast. Returns the command's exit code."""
    cast_dir.mkdir(parents=True, exist_ok=True)
    index = _next_index(cast_dir)
    path = cast_dir / f"{index:03d}-{_slug(argv)}.cast"

    started = time.time()
    header = {
        "version": VERSION,
        "width": int(os.environ.get("COLUMNS", 100)),
        "height": int(os.environ.get("LINES", 30)),
        "timestamp": int(started),
        "title": title or " ".join(argv),
        # Ours, alongside the standard keys. A reader that does not know them ignores them; a
        # reader that does gets the command as data rather than having to parse it back out of the
        # title.
        "command": list(argv),
        "cwd": str(cwd or Path.cwd()),
        "note": note or "",
    }

    # Python line-buffers when stdout is a terminal and block-buffers when it is a pipe — and a
    # recorder is always a pipe. Left alone, a script that printed steadily for two minutes records
    # as **one event at the end**: every timing this file exists to capture, gone. Forcing
    # unbuffered brings the recording back to what a person watching the terminal would have seen.
    # It does change the child's behaviour; that is the trade, and it is the right way round.
    #
    # `PYTHONIOENCODING` for the same reason one level over. The decoder below reads UTF-8, and
    # until now nothing made that true: a Python child on Windows writes its stdout in the machine's
    # ANSI codepage, so on a cp950 or cp932 box every non-ASCII character arrived as `�` —
    # decoded without error, wrong in every glyph, and indistinguishable from the chunk-boundary
    # corruption this file's own test exists to catch. Asking for UTF-8 is what makes reading UTF-8
    # correct rather than assumed.
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")

    events = []
    proc = subprocess.Popen(
        argv, cwd=str(cwd) if cwd else None, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        # errors="replace" and an explicit codec, because `text=True` alone decodes with the
        # caller's locale and this repository's own messages are full of em-dashes. A recorder that
        # dies on the output it is recording is worse than no recorder.
        bufsize=0)

    assert proc.stdout is not None
    decoder_buffer = b""
    while True:
        chunk = proc.stdout.read(CHUNK)
        if not chunk:
            break
        decoder_buffer += chunk
        try:
            text = decoder_buffer.decode("utf-8")
            decoder_buffer = b""
        except UnicodeDecodeError:
            # A multi-byte character split across two reads. Hold the tail rather than replacing it
            # — otherwise every chunk boundary that lands mid-character corrupts a glyph.
            for back in range(1, 4):
                try:
                    text = decoder_buffer[:-back].decode("utf-8")
                    decoder_buffer = decoder_buffer[-back:]
                    break
                except UnicodeDecodeError:
                    continue
            else:
                text = decoder_buffer.decode("utf-8", "replace")
                decoder_buffer = b""
        events.append([round(time.time() - started, 4), "o", text])
        sys.stdout.write(text)
        sys.stdout.flush()

    if decoder_buffer:
        events.append([round(time.time() - started, 4), "o",
                       decoder_buffer.decode("utf-8", "replace")])
    code = proc.wait()
    elapsed = round(time.time() - started, 4)

    header["duration"] = elapsed
    header["exit_code"] = code

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    return code, path


def main():
    parser = argparse.ArgumentParser(
        description="Record a command's output with timings, for later playback.")
    parser.add_argument("--cast-dir", required=True,
                        help="directory the cast is written into. One file per command, numbered.")
    parser.add_argument("--title", help="what this step is, in a few words. Shown in the player.")
    parser.add_argument("--note", help="why this step was run. Shown under the title.")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="the command, after --")
    args = parser.parse_args()

    argv = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not argv:
        parser.error("no command given; put it after --")

    code, path = record(argv, Path(args.cast_dir), args.title, args.note)
    print(f"\n[recorded {path} · exit {code}]", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
