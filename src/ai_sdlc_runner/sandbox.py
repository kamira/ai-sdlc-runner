"""Bounding what a dispatched process may touch (CHG-20260827-23).

`policy.py`'s capability flags have always been **advisory**. `Role("qa", can_write=False)` carries
the note *"deliberately cannot write, so it cannot fix while verifying"* — a real safety property —
and nothing enforced it. The flags went into the work order, and the process ran in `agent_cwd` with
the operator's full rights. `grep -riE "sandbox|bwrap|seatbelt|landlock" src/` returned nothing.

## Why this is at the operating system and not in the harness

A harness enforces a capability by withholding a tool. This runner cannot: the work order carries no
tool names, by design, and depends on no harness. That portability is what made the flags advisory —
the cost of the invariant, not a bug in it.

The only enforcement that is portable, needs no cooperation from the backend, and puts no
harness-specific field in the order, is the OS.

## Nothing is silent, and only one case is a refusal

A sandbox that quietly does nothing is worse than no sandbox: it is a claim in a report that nothing
backs. So a run this machine cannot bound returns `enforced: False`, and the caller records an
unsandboxed run in the report and the export.

**Refusing whenever no mechanism exists was the proposal, and it does not survive contact with
Windows** — `available()` is `None` there for every run, so every dispatch would raise: fourteen
test files and the runner itself, on the platform it is developed on. That is the failure
`policy.py` already names about the red lines, *a check that gets switched off*.

What is refused is the narrower thing: an operator passed `--sandbox`, asked for a boundary, and
this machine cannot draw one. "Nobody asked and it is written down" and "somebody asked and it
cannot be done" are different, and only the second stops the run.

## What is verified, and where

The argv this module builds is asserted directly, on every platform. Whether `bwrap` then denies the
write is **not** exercised on Windows, where no mechanism exists — see
`tests/test_sandbox.py::test_a_denied_write_actually_fails`, which skips loudly rather than passing
quietly, and `docs/acceptance/ACC-20260827-23.md`, which says so rather than implying coverage.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from . import policy


class SandboxError(Exception):
    """No way to enforce what was asked for. Never downgraded to running without one."""


#: The mechanisms, in the order they are tried, with what each needs to be present.
#:
#: A tuple rather than a dict so the order is the file's rather than a hash's — "which one did it
#: pick" is a question an operator asks, and the answer must not depend on insertion order.
MECHANISMS: Tuple[Tuple[str, str, str], ...] = (
    ("bwrap",        "linux",  "bwrap"),
    ("seatbelt",     "darwin", "sandbox-exec"),
)

#: What an operator passes to *require* one. The default is "enforce where this machine can, and
#: record it where it cannot" — see `wrap`. This flag turns the recording into a refusal, for a run
#: where proceeding unbounded is not acceptable.
REQUIRE_FLAG = "--sandbox"


def available(system: Optional[str] = None,
              which=shutil.which) -> Optional[Tuple[str, str]]:
    """The mechanism this machine can use, as `(name, tool path)`, or `None`.

    `system` and `which` are parameters so the table can be exercised for every platform from any
    platform — a detection function only testable on the machine that runs it is one nobody checks
    the Windows branch of. That branch is the one that matters most here: it is the refusal.
    """
    running = (system or sys.platform).lower()
    for name, needs_platform, tool in MECHANISMS:
        if not running.startswith(needs_platform):
            continue
        found = which(tool)
        if found:
            return name, found
    return None


def describe(system: Optional[str] = None, which=shutil.which) -> str:
    """One line for the run report: which mechanism, or why none. Task 1 is this being reported."""
    found = available(system, which)
    if found:
        return f"{found[0]} ({found[1]})"
    return f"none available on {system or sys.platform} ({platform.system()})"


def wrap(argv: Sequence[str], *, risk: str, can_write: bool = True,
         workspace: Optional[str] = None, required: bool = False,
         system: Optional[str] = None, which=shutil.which) -> Tuple[List[str], Dict[str, object]]:
    """The command to actually run, and the policy it runs under.

    Returns `(argv, policy)`. The policy is returned rather than only applied so the report can say
    what a process was permitted, which is the difference between a claim and a record.

    Raises `SandboxError` when nothing can enforce the policy **and the operator asked for one**
    (`required=True`, from `--sandbox`).

    ## Why not refuse whenever no mechanism exists

    That is what CHG-20260827-23 proposed, and it makes the runner unusable on the platform it is
    developed on: `available()` is `None` on every Windows machine, so an unconditional refusal
    raises on every dispatch — fourteen test files and the runner itself. A rule that stops
    everything is the failure `policy.py` already names about the red lines: *a check that gets
    switched off.*

    So the property is kept in the form that survives. **Nothing is ever silent**: a run that could
    not be sandboxed returns `enforced: False`, and the caller records it as a relaxation the report
    and the export both carry. What is refused is the *specific* case where somebody asked for a
    boundary and this machine cannot draw one — because there, proceeding would answer a question
    that was actually put.

    The distinction is between "nobody asked and it is written down" and "somebody asked and it
    cannot be done". Only the second is a refusal.
    """
    wanted = policy.sandbox_for(risk, can_write)
    mechanism = available(system, which)

    if mechanism is None:
        if required:
            raise SandboxError(
                f"nothing on this machine can enforce the sandbox this run asks for "
                f"(write={wanted['write']}, network={'yes' if wanted['network'] else 'no'}): "
                f"{describe(system, which)}. Install one, run on a platform that has one, or drop "
                f"{REQUIRE_FLAG} — without it the work runs with your own rights, recorded in the "
                f"report as an unsandboxed run rather than passed over in silence.")
        return list(argv), {**wanted, "mechanism": None, "enforced": False}

    name, tool = mechanism
    root = os.path.abspath(workspace or os.getcwd())
    if name == "bwrap":
        wrapped = _bwrap(argv, tool, root, wanted)
    elif name == "seatbelt":
        wrapped = _seatbelt(argv, tool, root, wanted)
    else:  # pragma: no cover - MECHANISMS is closed and every entry is handled above
        raise SandboxError(f"mechanism {name!r} has no command builder")
    return wrapped, {**wanted, "mechanism": name, "enforced": True}


#: The character that ends an sbpl string literal early.
#:
#: CHG-20260828-25 proposed refusing the backslash as well, on the ground that its meaning
#: inside `subpath` was never established. Measured, that refuses a path the suite
#: legitimately produces: `wrap` computes `root` with `os.path.abspath`, which uses the
#: **host's** separators no matter what `system=` says, so `workspace="/w"` becomes a
#: backslashed path on Windows and the macOS-profile test stops being runnable. A blocklist
#: that fires on a legal path is the trade this repository has a record about, so this refuses
#: only what provably breaks the literal (CHG-20260903-30, deviating from the record it
#: adopts, and saying so).
#:
#: A blocklist is not a proof and this one does not pretend to be. Whether sbpl has other
#: metacharacters inside `subpath` was not established by anyone who wrote it down, which is
#: why the refusal names the character it met rather than saying "invalid path".
UNREPRESENTABLE_IN_SBPL = '"'


def _sbpl_path(root: str) -> str:
    """`root`, checked for characters the profile cannot carry — or refused, naming the one it met.

    `_seatbelt` interpolates this into `(allow file-write* (subpath "..."))` and hands the assembled
    profile to `sandbox-exec -p`. macOS paths may contain `"`, and **sbpl has no escape for `"`
    inside a string literal**, so escaping is not on the table the way it would be for a shell or
    for JSON. A path that breaks the literal makes the policy *broken*; a path chosen to break it
    makes the policy **different**:

        root = /tmp/x") (allow network*) (allow file-write* (subpath "/

    renders a profile that allows the network the grade denied. The quoting is the whole of what
    keeps the policy table and the enforced policy the same document.

    **Refused, not encoded**, because that is what this module's neighbour already does: `policy`'s
    sandbox scope refuses a value it does not implement rather than absorbing it. If someone finds a
    representation sbpl accepts for every path, that is a better fix and this should be argued with
    rather than followed (CHG-20260903-30, adopting CHG-20260828-25).

    Not claimed: that this is exploitable today. `root` is the operator's `--workspace` or `cwd`,
    and an operator who wants a wider sandbox can pass a flag. What this fixes is a boundary that
    stops being one if that ever stops being true — a policy alterable by a filename is not a policy.

    `_bwrap` takes the same `root` as an **argv element**, where quoting does not arise. So the two
    mechanisms differ not only in what they enforce but in **which inputs they can represent at
    all**, and a path legal for one is a refusal for the other.
    """
    for character in UNREPRESENTABLE_IN_SBPL:
        if character in root:
            raise SandboxError(
                f"the workspace path contains {character!r}, which cannot be written into a "
                f"seatbelt profile: sbpl has no escape for it inside a string literal, so the "
                f"path would end the literal and the rest would be read as policy. Refused before "
                f"anything starts rather than enforced as something else. Move the workspace, or "
                f"drop {REQUIRE_FLAG} to run unsandboxed and recorded as such. "
                f"(`bwrap` on Linux takes this path unchanged — it passes it as an argument "
                f"rather than into a profile.)")
    return root


def _bwrap(argv: Sequence[str], tool: str, root: str,
           wanted: Mapping[str, object]) -> List[str]:
    """Linux. The host read-only, a **private** tmpfs at `/tmp`, then the workspace bound writable
    if the policy allows it.

    `--tmpfs /tmp` is not a write grant against the host and is why this said "read-only everywhere"
    for as long as it did: the sandbox gets an empty `/tmp` of its own and the machine's is neither
    visible nor writable. It is containment, and it is also not nothing — the sentence is now what
    the argv actually is (CHG-20260903-30, L-36). `_seatbelt` has no equivalent and grants the
    host's `/tmp` instead; its docstring says so.

    `--unshare-net` is the network denial and it is unconditional when the policy says no — there is
    no partial network here, because "some hosts" is a firewall and this is a boundary.
    """
    out = [tool, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--tmpfs", "/tmp"]
    if wanted["write"] == "workspace":
        out += ["--bind", root, root]
    if not wanted["network"]:
        out += ["--unshare-net"]
    out += ["--chdir", root, "--"]
    return out + list(argv)


def _seatbelt(argv: Sequence[str], tool: str, root: str,
              wanted: Mapping[str, object]) -> List[str]:
    """macOS. The profile is generated from the same policy rather than kept as a file, so there is
    one source for what is allowed and no second document to drift.

    **With one exception, stated here because the sentence above is otherwise false.** The `/tmp`
    grant below is unconditional and comes from no policy row: it is written even at `write: none`,
    the scope `policy` describes as the one a verifier gets *"so it cannot fix while verifying"*.
    Tools need somewhere to write temporary files, and denying it would refuse `npm`, `pip` and
    every compiler — but on macOS that is the **host's** `/tmp`, shared with everything else on the
    machine, where `_bwrap`'s `--tmpfs` gives the sandbox a private one instead. The two mechanisms
    are not equivalent here and nothing said so (CHG-20260903-30, L-36).

    Narrowing this to a per-run directory needs `TMPDIR` plumbed into the child's environment, which
    is a separate change. What is fixed here is that the boundary module stops describing a boundary
    it does not draw.
    """
    lines = ["(version 1)", "(deny default)", "(allow process*)", "(allow file-read*)",
             "(allow sysctl-read)"]
    if wanted["write"] == "workspace":
        lines.append(f'(allow file-write* (subpath "{_sbpl_path(root)}"))')
    lines.append('(allow file-write* (subpath "/tmp"))')
    if wanted["network"]:
        lines.append("(allow network*)")
    return [tool, "-p", " ".join(lines), *argv]
