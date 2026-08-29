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

**In which unit**, and **against what limit**, are the two parts this module got wrong — see
`measure` and `name_max`. Windows counts UTF-16 code units; ext4 counts UTF-8 bytes; macOS
normalises to NFD before storing, so the bytes it counts are not the bytes you passed. The limit
itself is asked of the filesystem where POSIX allows it, rather than assumed to be 255.

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
import sys
import unicodedata
from pathlib import Path
from typing import List, Tuple

#: Windows' extended-length prefix. Lifts `MAX_PATH` to ~32,767 for the call it is passed to.
PREFIX = "\\\\?\\"

#: The UNC form. `\\server\share\x` cannot simply take the prefix — it becomes `\\?\UNC\server\...`.
UNC_PREFIX = "\\\\?\\UNC\\"

#: The fallback limit, used where the filesystem cannot be asked — Windows, which has no
#: `pathconf`, and any POSIX path whose ancestors have all vanished. 255 is right for NTFS, ReFS,
#: exFAT, ext4 and APFS; it is a **default, not a fact about every filesystem**, and `name_max()`
#: prefers the answer the filesystem gives.
NAME_MAX = 255


class PathTooLong(OSError):
    """A path this machine will not take, refused by name before anything is written."""


def name_max(near: str | Path | None = None) -> int:
    """The longest component this filesystem takes — **asked, where it can be asked**.

    `NAME_MAX = 255` was a constant standing in for a queried constraint, which is this project's
    own defect class written as a module-level assignment. POSIX can be asked directly:
    `pathconf(dir, "PC_NAME_MAX")` answers for the filesystem actually mounted there, which is the
    only thing that knows. A macOS machine can have APFS, HFS+, an SMB share and a FAT stick
    mounted at once, and `os.name` distinguishes none of them.

    Windows has no `pathconf`; 255 is right for NTFS, ReFS and exFAT, and the constant stands there
    with that scope stated rather than implied.

    `near` is a path that may not exist yet, so the nearest existing ancestor is asked — a name is
    checked before its directory is created.
    """
    if os.name == "nt" or not hasattr(os, "pathconf"):
        return NAME_MAX
    probe = Path(os.fspath(near)) if near is not None else Path(".")
    for candidate in [probe, *probe.parents]:
        try:
            found = os.pathconf(str(candidate), "PC_NAME_MAX")
        except (OSError, ValueError, KeyError):
            continue
        if found and found > 0:
            return int(found)
    return NAME_MAX


def measure(part: str) -> Tuple[int, str]:
    """How long this machine considers one name, **in the unit its filesystem actually counts**.

    Wrong twice before, and in the direction that hurts non-Latin names both times.

    **First**: UTF-8 bytes everywhere, so a 100-character CJK name — 300 bytes, 100 UTF-16 units,
    and legal on NTFS — was refused with a message asserting no filesystem would take it.

    **Then**: UTF-16 units on `nt` and bytes everywhere else, which both review seats called out.
    That still conflates the OS with the filesystem, and it gets macOS wrong in a way that
    *under*-refuses:

    - macOS **normalises toward NFD before storing**. `한` is 3 UTF-8 bytes composed and 6
      decomposed, so a name measured as given can pass this check and still be refused by the
      kernel with `ENAMETOOLONG` — the very failure this module exists to pre-empt.
    - **HFS+ counts UTF-16 units**, not bytes at all, and the docstring listed it at "255" beside
      ext4 as though the unit were shared.

    So: NFD on Darwin before counting, because that is what will be stored; UTF-16 units on
    Windows; UTF-8 bytes on Linux. The *limit* comes from `name_max()`, which asks the filesystem.

    Still not claimed: that this is right for every filesystem a machine can mount. An HFS+ volume
    on macOS counts UTF-16 units and is measured here in NFD bytes, which **over**-refuses — a name
    that would fit is called too long. That is the safer direction of the two, it is stated rather
    than hidden, and closing it needs the filesystem type, which nothing here has.
    """
    if os.name == "nt":
        return len(part.encode("utf-16-le")) // 2, "UTF-16 code units"
    if sys.platform == "darwin":
        # What the kernel will store, not what the caller typed.
        return len(unicodedata.normalize("NFD", part).encode("utf-8")), "bytes (NFD)"
    return len(part.encode("utf-8")), "bytes"


def check(path: str | Path) -> None:
    """Refuse what no prefix can fix, and say which component is at fault.

    Only the per-component limit. Total length is handled — on Windows by the prefix, on POSIX by
    the limit being far above anything here — so a refusal from this function is always about one
    name being too long, and it says which.
    """
    limit = name_max(path)
    for part in Path(os.fspath(path)).parts:
        if part in ("/", "\\") or (len(part) == 3 and part[1:] == ":\\"):
            continue                                  # a root or a drive, not a name
        if part.startswith(PREFIX):
            continue                                  # the extended-length prefix, not a name
        size, unit = measure(part)
        if size > limit:
            raise PathTooLong(
                f"{part[:40]}… is {size} {unit} as a single path component, and this filesystem "
                f"takes at most {limit}. The extended-length prefix lifts the total path length "
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

    **A whole path, not a sentence containing one.** The prefix is stripped only from the start,
    which is right for a path and wrong for an error message that quotes one mid-way — see
    `plain_in`, and CHG-20260828-24 for what happened when this one was used for that.
    """
    text = os.fspath(path)
    if text.startswith(UNC_PREFIX):
        return "\\\\" + text[len(UNC_PREFIX):]
    if text.startswith(PREFIX):
        return text[len(PREFIX):]
    return text


def plain_in(text: str) -> str:
    r"""The same stripping, wherever the prefix appears — for a sentence that quotes a path.

    `plain` only strips a **leading** prefix, because that is what a path has. An OS error does not
    hand back a path; it hands back a sentence with one inside it —
    `unable to open database file \\\\?\\C:\\…` — and running that through `plain` returns it
    unchanged.

    Two call sites were doing exactly that (`store.connect` and `conversations`), each with a
    comment explaining that the prefix must not reach the reader, and neither delivered it. The
    guard was a no-op wearing the name of the thing it did not do, which is this repository's most
    recorded defect shape (CHG-20260828-24).

    UNC first, because `\\\\?\\UNC\\server\\share` starts with `\\\\?\\` too and stripping the
    shorter one leaves `UNC\\server\\share`, which is not a path anybody can use.
    """
    return text.replace(UNC_PREFIX, "\\\\").replace(PREFIX, "")


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
