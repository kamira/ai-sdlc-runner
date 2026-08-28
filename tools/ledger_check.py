#!/usr/bin/env python3
"""ledger_check.py — this repo's own governance lint (CHG-20260823-01).

The gate that used to run this was a script inside the vendored skill. There is no skill, so the
check is ours — which is the same move as `policy.py`: the discipline was never the skill's, only the
implementation was.

Three checks, each on something that has actually gone wrong here:

1. **A change that claims to be finished has an acceptance record.** A CHG marked done with no ACC
   is the false-green this repo keeps catching — work reported complete with nothing saying it was
   checked. The vocabulary of "finished" is **closed**: a status word neither list recognises is a
   problem, not a pass. The previous version knew only "built", so "accepted", "merged" and "完成"
   all escaped it silently.
2. **Every change carries its required fields.** A ledger entry missing its branch, risk or status is
   one the next reader cannot act on.
3. **A change's status is read from its status line, not from its prose.** The previous lint scanned
   the whole document for words like "accepted", so writing *about* acceptance in a paragraph
   flipped the document's classification — it happened three times in one session, twice inside the
   sentence explaining the first time. Status is a field. This reads the field.

Exit 0 when the ledger is consistent, 1 when it is not, with the reason on stdout.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List

#: Required of every change. `Status` is not here: it is a *section*, read below, because reading it
#: as a field is what let prose about status change a document's status.
REQUIRED_FIELDS = ("Project", "Date", "Risk")

#: Required only from this id onward. The convention started partway through this repo's life, and a
#: lint that fails on history it cannot change teaches people to ignore the lint. Prospective, the
#: same way the rules it replaces were.
BRANCH_REQUIRED_FROM = "CHG-20260703-01"

#: Statuses that mean the work is finished. Anything here needs a matching ACC.
DONE = (
    "built", "implemented", "accepted", "complete", "completed", "done", "merged", "shipped",
    "closed", "released",
    "已建置", "已實作", "已驗收", "已完成", "完成", "已合併", "已收尾",
)

#: Statuses that mean the work is not finished yet. Nothing is required of these.
IN_PROGRESS = (
    "draft", "in progress", "wip", "blocked", "halted", "paused", "pending", "under review",
    "proposed", "superseded", "abandoned", "withdrawn",
    "草稿", "進行中", "擱置", "停擺", "待審", "已作廢", "已取代",
)


def _status_line(text: str) -> str:
    """The `## Status` section's first non-empty line, and nothing else.

    Deliberately narrow. A document that discusses its own status in prose must not thereby change
    it, which is exactly the failure this replaces.
    """
    match = re.search(r"^##\s+Status\s*$", text, re.MULTILINE)
    if not match:
        return ""
    for line in text[match.end():].splitlines():
        if line.strip():
            return line.strip()
    return ""


def _status_word(line: str) -> str:
    """The status itself, with the commentary after it cut off.

    A status line here is conventionally ``<status> — <a sentence about it>``, and the sentence is
    where the trouble lives: "draft — all 9 tasks built" is a draft, and reading the whole line makes
    it read as both. The status is the **head** of the line; everything from the first dash, bracket
    or full stop onward is prose, and prose does not decide status. That is the same lesson as
    reading the Status section instead of the whole document, one level further in.
    """
    head = line.strip().strip("*_` ")
    for cut in ("—", "–", " - ", " -- ", "(", "[", ",", ";", ".", "!"):
        index = head.find(cut)
        if index > 0:
            head = head[:index]
    return head.strip().strip("*_` ").lower()


def _field_present(text: str, field: str) -> bool:
    return bool(re.search(rf"^\s*-?\s*{field}\s*[:：]", text, re.MULTILINE | re.IGNORECASE))


def _target_chg(text: str) -> str:
    """The change an acceptance says it is for, or `""` when it does not say.

    Absence is not a problem here: older records predate the field, and inventing a requirement for
    them would turn a traceability check into a formatting one. What is checked is **disagreement**
    — a record that names a target and names the wrong one.
    """
    found = re.search(r"^[-*]\s*(?:\*\*)?Target CHG(?:\*\*)?\s*:\s*(CHG-[\d-]+)", text, re.M)
    return found.group(1) if found else ""


def check(repo: Path) -> List[str]:
    problems: List[str] = []
    changes = sorted((repo / "docs" / "changes").glob("CHG-*.md"))
    if not changes:
        return ["docs/changes/ holds no CHG files — this repo is governed and should"]

    accepted = {p.stem.replace("ACC-", "") for p in (repo / "docs" / "acceptance").glob("ACC-*.md")}

    for path in changes:
        text = path.read_text(encoding="utf-8")
        chg_id = path.stem

        required = list(REQUIRED_FIELDS)
        if chg_id >= BRANCH_REQUIRED_FROM:
            required.append("Branch")
        missing = [f for f in required if not _field_present(text, f)]
        if missing:
            problems.append(f"{chg_id}: missing required field(s): {missing}")

        status = _status_word(_status_line(text))
        if not status:
            problems.append(f"{chg_id}: has no Status section")
            continue

        done = [w for w in DONE if w in status]
        open_ = [w for w in IN_PROGRESS if w in status]

        # The vocabulary is closed on purpose. An unrecognised status used to be treated as
        # not-finished, so a change whose status said "accepted" or "完成" sailed past a lint that
        # only knew the word "built" — the exact false-green this file exists to catch. Now a word
        # nobody wrote down is a problem, and the fix is to add it to one of the two lists above,
        # deliberately, rather than to discover years later which side it silently fell on.
        if not done and not open_:
            problems.append(
                f"{chg_id}: status {status!r} is not a recognised one. Add the word to DONE or to "
                f"IN_PROGRESS in tools/ledger_check.py — an unrecognised status is not a pass")
            continue
        if done and open_:
            problems.append(
                f"{chg_id}: status {status!r} reads as both finished ({done}) and unfinished "
                f"({open_}); the next reader cannot act on it")
            continue

        if done and chg_id.replace("CHG-", "") not in accepted:
            problems.append(
                f"{chg_id}: its status says the work is finished, but docs/acceptance/ has no "
                f"matching ACC — a change reported complete with nothing saying it was checked")

    # ── the other direction, which nothing walked (CHG-20260828-02) ─────────────────────────────
    #
    # Everything above starts at a CHG. An ACC naming a change that does not exist was therefore
    # invisible: the ledger reported "passed" while an acceptance vouched for nothing. Traceability
    # is the point of keeping both files, and it only holds if it holds both ways.
    known = {p.stem.replace("CHG-", "") for p in changes}
    for path in sorted((repo / "docs" / "acceptance").glob("ACC-*.md")):
        acc_id = path.stem
        suffix = acc_id.replace("ACC-", "")
        if suffix not in known:
            problems.append(
                f"{acc_id}: names no change in docs/changes/ — CHG-{suffix} does not exist. Either "
                f"the change was renamed and this record now vouches for nothing, or the id is a "
                f"typo and the acceptance is filed against the wrong change")
            continue
        # A record filed under one id while claiming another target points two ways, and a reader
        # following either one lands somewhere the other contradicts.
        stated = _target_chg(path.read_text(encoding="utf-8"))
        if stated and stated != f"CHG-{suffix}":
            problems.append(
                f"{acc_id}: is filed under CHG-{suffix} but its `Target CHG` says {stated}. One of "
                f"the two is wrong and the pair no longer traces")
    return problems


def main(argv: List[str]) -> int:
    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path(".")
    problems = check(repo)
    if problems:
        print("ledger check failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"ledger check passed ({len(list((repo / 'docs' / 'changes').glob('CHG-*.md')))} changes)")
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main(sys.argv[1:]))
