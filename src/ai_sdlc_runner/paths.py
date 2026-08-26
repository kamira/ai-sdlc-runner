r"""paths.py — one place that knows how long a path this machine will actually take.

The defect this closes has bitten three times and been recorded twice:

- `attachments.py` shortened a hash from 64 characters to 32 for it, with three paragraphs of
  explanation;
- an independent seat reproduced it against the conversation store, losing a whole conversation to
  a run that still reported `finished`;
- and it bit again while building a real SPA, at 282 characters against a 260-character limit.

Each time the fix was to make the *path shorter*, or to make the failure *louder*. Neither is the
fix. This is.

## Windows

`MAX_PATH` is 260, and it applies to `mkdir` as much as to `open` — measured:

```
target depth: 294
makedirs, plain:     FileNotFoundError errno=2 winerror=206
makedirs, extended:  ok
file (303 chars)     plain: FileNotFoundError    extended: ok
sqlite               plain: unable to open database file    extended: ok
```

The `\\?\` prefix lifts it to roughly 32,767 — **and it fixes SQLite too**, which matters because
the model store is a database file at whatever depth the operator chose.

The prefix has conditions, and each one is a way to get it wrong:

- the path must be **absolute** — a relative path with the prefix is not resolved, it is refused;
- it must use **backslashes only**, because the prefix turns off the normalisation that would have
  converted them;
- it must contain no `.` or `..`, for the same reason;
- a UNC path takes a different form — `\\server\share` becomes `\\?\UNC\server\share`.

`os.path.abspath` handles the first three. The fourth is handled here.

## POSIX

There is no prefix and none is needed for the total length: `PATH_MAX` is 4096 on Linux and 1024 on
macOS, far above anything this runner builds. What POSIX *does* enforce, and what no prefix on any
platform lifts, is **`NAME_MAX` — 255 bytes for a single component**. Measured on Windows too:

```
200-char name: accepted
255-char name: accepted
300-char name: OSError errno=22
```

**In which unit** is the part this module first got wrong. Windows counts UTF-16 code units; ext4
and APFS count UTF-8 bytes. Counting bytes everywhere refused a 100-character CJK name — 300 bytes,
100 units, and legal — with a message asserting no filesystem would take it. See `measure`.

So the honest split is:

| | fixed by | |
|---|---|---|
| total path length | the `\\?\` prefix on Windows; nothing needed on POSIX | **closed** |
| one component over 255 | **nothing** | **refused by name**, before the write |

A limit that can be lifted is lifted. A limit that cannot is refused with the reason and the
offending component named, rather than arriving as `FileNotFoundError` about a directory that
demonstrably exists — which is how this defect disguised itself all three times.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import List, Tuple

#: Windows' extended-length prefix. Lifts `MAX_PATH` to ~32,767 for the call it is passed to.
PREFIX = "\\\\?\\"

#: The UNC form. `\\server\share\x` cannot simply take the prefix — it becomes `\\?\UNC\server\...`.
UNC_PREFIX = "\\\\?\\UNC\\"

#: The longest single path component any mainstream filesystem accepts. NTFS, ext4, APFS and HFS+
#: all stop at 255, and **no prefix lifts it** — measured on this machine at 255 accepted, 300
#: refused with `errno 22`.
NAME_MAX = 255


class PathTooLong(OSError):
    """A path this machine will not take, refused by name before anything is written."""


def measure(part: str) -> Tuple[int, str]:
    """How long this machine considers one name, **in the unit its filesystem actually counts**.

    This was wrong, and wrong in the worst direction (CHG-20260823-38). The first version counted
    UTF-8 bytes everywhere, so a 100-character CJK name — 300 bytes, and perfectly legal — was
    refused with a message asserting that no filesystem here would take it. Measured on this
    machine:

    ```
    chars: 100 | utf-8 bytes: 300 | utf-16 units: 100
    the filesystem ACCEPTED it -> True
    paths.check REFUSED it
    ```

    A false refusal is worse than the failure it was written to prevent: the original defect was a
    confusing error about a real limit, and this was a confident error about a limit that does not
    exist. It fell hardest on exactly the names least likely to be tested — a Latin name reaches 255
    bytes and 255 characters together, so nothing in the original test set could have caught it.

    - **Windows** counts UTF-16 code units. An astral character (an emoji) costs two, which is what
      the API does too.
    - **ext4 and APFS** count UTF-8 bytes.
    """
    if os.name == "nt":
        return len(part.encode("utf-16-le")) // 2, "UTF-16 code units"
    return len(part.encode("utf-8")), "bytes"


def check(path: str | Path) -> None:
    """Refuse what no prefix can fix, and say which component is at fault.

    Only the per-component limit. Total length is handled — on Windows by the prefix, on POSIX by
    the limit being far above anything here — so a refusal from this function is always about one
    name being too long, and it says which.
    """
    for part in Path(os.fspath(path)).parts:
        if part in ("/", "\\") or (len(part) == 3 and part[1:] == ":\\"):
            continue                                  # a root or a drive, not a name
        size, unit = measure(part)
        if size > NAME_MAX:
            raise PathTooLong(
                f"{part[:40]}… is {size} {unit} as a single path component, and this filesystem "
                f"takes at most {NAME_MAX}. The extended-length prefix lifts the total path length "
                f"and not this — shorten the name.")


def real(path: str | Path) -> str:
    r"""The string to hand the operating system.

    On Windows: absolute, backslashed, and prefixed — unless it is already prefixed, in which case
    prefixing again would produce a path with a literal `\\\\?\\` component in it.

    On POSIX: absolute, and nothing else. Returning the plain path rather than inventing a
    no-op wrapper keeps every error message readable, which is most of what the caller needs when
    something does go wrong.
    """
    text = os.fspath(path)
    if os.name != "nt":
        return os.path.abspath(text)
    if text.startswith(PREFIX):
        # Already prefixed — but only *absolute* prefixed paths are meaningful, because the prefix
        # turns off the resolution that would have made a relative one absolute. Returning it
        # unchanged handed the OS a path it cannot resolve and called it done (CHG-20260823-38);
        # a seat found it. Strip, resolve, re-prefix.
        inner = plain(text)
        if os.path.isabs(inner):
            return text
        text = inner
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):                    # a UNC path: \\server\share\…
        return UNC_PREFIX + absolute[2:]
    return PREFIX + absolute


def plain(path: str | Path) -> str:
    r"""The path without the prefix — for messages, and for anything shown to a person.

    A traceback carrying `\\\\?\\C:\\…` sends the reader looking for a network share.
    """
    text = os.fspath(path)
    if text.startswith(UNC_PREFIX):
        return "\\\\" + text[len(UNC_PREFIX):]
    if text.startswith(PREFIX):
        return text[len(PREFIX):]
    return text


# ── the operations, each taking the long form ─────────────────────────────────────────────────
#
# Every one of these is a call that failed at MAX_PATH in the measurements above. `mkdir` is here
# because it fails *first* — the directory could not be created, so the file's failure arrived as
# "no such file or directory" about a parent that was never made.

def makedirs(path: str | Path) -> None:
    check(path)
    os.makedirs(real(path), exist_ok=True)


def open_(path: str | Path, mode: str = "r", **kwargs):
    check(path)
    return io.open(real(path), mode, **kwargs)


def read_text(path: str | Path, encoding: str = "utf-8") -> str:
    """Read it and close it.

    Here rather than at every call site because the first version of this module wrote
    `paths.open_(marker, "w", …).write(…)` with no context manager, and the handle was never
    flushed: `_project.json` came out **empty**, and `runner conversations` then died on
    `Expecting value: line 1 column 1`. A file that exists and is empty is a worse failure than one
    that was never created, and it was found by running the command rather than by reading the
    diff.
    """
    with open_(path, "r", encoding=encoding) as fh:
        return fh.read()


def write_text(path: str | Path, text: str, encoding: str = "utf-8",
               newline: str = chr(10)) -> None:
    """Write it and close it — see `read_text` for what happens when nothing closes it."""
    with open_(path, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)


def write_bytes(path: str | Path, data: bytes) -> None:
    with open_(path, "wb") as fh:
        fh.write(data)


def exists(path: str | Path) -> bool:
    return os.path.exists(real(path))


def listdir(path: str | Path) -> List[str]:
    return os.listdir(real(path)) if exists(path) else []


def chmod(path: str | Path, mode: int) -> None:
    """Best effort, and it stays best effort — see `conversations.py` on what `0700` buys."""
    try:
        os.chmod(real(path), mode)
    except OSError:
        pass


def unlink(path: str | Path) -> None:
    os.unlink(real(path))
