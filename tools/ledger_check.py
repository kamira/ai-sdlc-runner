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
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

#: Required of every change. `Status` is not here: it is a *section*, read below, because reading it
#: as a field is what let prose about status change a document's status.
REQUIRED_FIELDS = ("Project", "Date", "Risk")

#: Required only from this id onward. The convention started partway through this repo's life, and a
#: lint that fails on history it cannot change teaches people to ignore the lint. Prospective, the
#: same way the rules it replaces were.
BRANCH_REQUIRED_FROM = "CHG-20260703-01"

#: Records from this id onward may not name a test that does not exist (CHG-20260828-20).
#:
#: A record's job is to let a later reader check the claim. `pinned by ``test_foo``` is worth
#: exactly as much as `test_foo` being findable, and 97 references in this ledger are not — mostly
#: to an architecture (`executors.py`, `dashboard.py`, `workspace.py`) that no longer exists.
#:
#: Prospective for the reason above: those 97 are history, and rewriting them would be inventing a
#: past rather than fixing one. Zero records from this id onward break the rule today, so it ships
#: green and catches the next typo instead of the last ninety-seven.
TESTS_MUST_EXIST_FROM = "20260828"

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


#: An acceptance's verdict, read from its `Conclusion` field the same way a change's status is read
#: from its `## Status` section — as a field, with the sentence after it cut off. The vocabulary is
#: closed for the same reason the two above are: a word nobody wrote down is a question, not a pass.
ACC_PASS = ("pass", "passes", "passed", "通過")
ACC_NOT_PASS = (
    "fail", "failed", "not sound", "rejected", "withdrawn", "superseded", "abandoned",
    # An acceptance that recorded a pass for something later shown not to work. Distinct from
    # `superseded`, which is about a change being replaced: this one says the verdict itself was
    # never true. Added when ACC-20260828-24 needed it — it had said **Pass** for a `src/` fix that
    # did nothing, and correcting only the prose left `_verdict` still reading `pass`.
    #
    # `void`, not `wrong`, and the difference is not taste. These lists are matched by substring
    # against the head of the Conclusion field, and `wrong` is a general-purpose adjective: five
    # acceptances already contain it in that line, four of which read as `pass` only because
    # `_status_word` happens to cut at punctuation before reaching it. A head with no punctuation —
    # "Pass but the first rule tried was wrong" — would match both lists at once. `void` appears in
    # no Conclusion line in the repository and is verdict-shaped, like every other entry here.
    #
    # What this does **not** do, stated because the first version of this comment claimed otherwise:
    # it changes no machine outcome. `check()` does `if not passed: continue`, so a not-pass verdict
    # imposes nothing, and CHG-20260828-24 still reads `**Accepted**` with a void acceptance under
    # it. Whether a void acceptance should stop satisfying a done change is a governance question
    # this change does not answer (CHG-20260830-08, risk seat).
    "void",
    "未通過", "退回", "已作廢",
)

#: The statuses that say a change is still waiting for the decision an acceptance records.
#:
#: Not every unfinished status belongs here, and the difference is the whole point. A change can be
#: accepted and *later* superseded, halted, paused or withdrawn — an acceptance sitting behind those
#: is history, not a contradiction. These say the decision has **not been made yet**, and an
#: acceptance is that decision, so the two cannot both be true.
AWAITING_DECISION = (
    "proposed", "draft", "under review", "in progress", "wip", "pending",
    "草稿", "進行中", "待審",
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


def _verdict(text: str) -> str:
    """An acceptance's conclusion, cut back to the verdict itself.

    Same discipline as `_status_word`, one document over: the head of the field decides, and the
    sentence explaining it does not. `Pass, on a reduced scope the operator approved` is a pass;
    reading the whole line would let the explanation argue with the verdict.
    """
    found = re.search(r"^[-*]\s*(?:\*\*)?Conclusion(?:\*\*)?\s*[:：]\s*(.*)$", text, re.M)
    return _status_word(found.group(1)) if found else ""


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

    texts = {path.stem: path.read_text(encoding="utf-8") for path in changes}

    for path in changes:
        text = texts[path.stem]
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
        acc_text = path.read_text(encoding="utf-8")
        stated = _target_chg(acc_text)
        if stated and stated != f"CHG-{suffix}":
            problems.append(
                f"{acc_id}: is filed under CHG-{suffix} but its `Target CHG` says {stated}. One of "
                f"the two is wrong and the pair no longer traces")
            continue

        # ── the two files trace to each other; nothing read what they SAID (CHG-20260828-16) ────
        #
        # Both directions above check that a record *exists*. Five changes carried an acceptance
        # whose conclusion was **Pass** while their own status still read "under review" or
        # "proposed", and this lint reported the ledger passed the whole time — while the handshake
        # gate, reading the same two files, named those same five as unclosed and told every new
        # session to close them first. Two readers, opposite answers, and the one wired into CI was
        # the one saying fine.
        #
        # An acceptance is the decision. A change cannot still be waiting for a decision that has
        # already been recorded against it.
        # Absence is not a problem, for the reason `_target_chg` gives: older records predate the
        # field, and inventing a requirement for them turns a traceability check into a formatting
        # one. What is checked is **disagreement** — a record that states a verdict its change
        # contradicts.
        verdict = _verdict(acc_text)
        if not verdict:
            continue
        passed = [w for w in ACC_PASS if w in verdict]
        refused = [w for w in ACC_NOT_PASS if w in verdict]
        if not passed and not refused:
            problems.append(
                f"{acc_id}: conclusion {verdict!r} is not a recognised verdict. Add the word to "
                f"ACC_PASS or to ACC_NOT_PASS in tools/ledger_check.py — an unrecognised verdict "
                f"is not a pass")
            continue
        if passed and refused:
            problems.append(
                f"{acc_id}: conclusion {verdict!r} reads as both a pass ({passed}) and a refusal "
                f"({refused}); the next reader cannot act on it")
            continue
        if not passed:
            continue

        waiting = [w for w in AWAITING_DECISION if w in _status_word(_status_line(texts[f"CHG-{suffix}"]))]
        if waiting:
            problems.append(
                f"CHG-{suffix}: its acceptance concluded {verdict!r}, but its own status still says "
                f"{waiting[0]!r} — the change is recorded as waiting for a decision that "
                f"{acc_id} already made. Close the change, or say in its status why the acceptance "
                f"did not close it")

    problems.extend(check_named_tests_exist(repo))
    return problems


def _tests_that_exist(repo: Path) -> set:
    """Every name a record may legitimately cite: a test function, or a test module.

    Both spellings are in use and both are useful — `test_flow` names a file, `test_a_halt_is_final`
    names one case in it. A rule that knew only functions would report every file reference as a
    ghost, which is how a lint teaches people to stop reading it.
    """
    directory = repo / "tests"
    if not directory.is_dir():
        return set()
    names = set()
    for path in sorted(directory.glob("*.py")):
        names.add(path.stem)
        names.update(re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.MULTILINE))
    return names


def check_named_tests_exist(repo: Path) -> List[str]:
    """A record naming a test that does not exist is vouching for nothing (CHG-20260828-20).

    The whole point of writing `pinned by ``test_foo``` in an acceptance is that a later reader can
    go and look. When `test_foo` has been renamed or deleted, the sentence still reads like
    evidence and is not, and nothing in this repository noticed — 97 such references had
    accumulated, most of them to an architecture that no longer exists.

    Prospective, for the reason `BRANCH_REQUIRED_FROM` gives: the 97 are history, and rewriting them
    would be inventing a past rather than fixing one.
    """
    known = _tests_that_exist(repo)
    if not known:                                   # pragma: no cover - a repo with no tests
        return []
    problems = []
    records = sorted(list((repo / "docs" / "changes").glob("CHG-*.md"))
                     + list((repo / "docs" / "acceptance").glob("ACC-*.md")))
    for path in records:
        stamp = path.stem.split("-")[1] if "-" in path.stem else ""
        if stamp < TESTS_MUST_EXIST_FROM:
            continue
        # Backticked only. Prose that merely mentions a test in passing is not a pointer, and this
        # repository's records discuss tests constantly.
        named = sorted(set(re.findall(r"`(test_\w+)`", path.read_text(encoding="utf-8"))))
        ghosts = [name for name in named if name not in known]
        if ghosts:
            problems.append(
                f"{path.stem}: names {len(ghosts)} test(s) that do not exist — {', '.join(ghosts)}. "
                f"A record pointing at evidence a reader cannot find is not evidence; fix the name, "
                f"or say in the record that the test was since removed and why")
    return problems


def _title(text: str) -> str:
    """A change's headline, which is its identity — `# CHG-20260828-14 — worktree isolation…`.

    The id alone cannot tell two changes apart when two branches claim it; the title can, because
    two people writing two different changes do not write the same sentence.
    """
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _at(repo: Path, ref: str, rel: str) -> Optional[str]:
    """A file's content at a git ref, or `None` if the ref or the file is not there."""
    try:
        done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):    # pragma: no cover - no git on the machine
        return None
    return done.stdout if done.returncode == 0 else None


def check_ids_are_not_claimed_twice(repo: Path, ref: str = "origin/main") -> List[str]:
    """Refuse a change that takes an id another change already has (CHG-20260828-06).

    A number is claimed by writing `docs/changes/CHG-….md`, and nothing reserves one. Two sessions
    working at once pick from the same free list, and `check` above cannot see it: two files with
    one name cannot coexist in a tree, so a collision surfaces only as a merge conflict — after both
    branches have gone green separately, each looking correct.

    That happened: CHG-20260828-04 was claimed at 12:23 by an unmerged branch and again at 13:00 by
    a change that merged. Two records, one number, both passing every check. The second was later
    renumbered to CHG-20260828-14, by hand, which is the resolution this check exists to make
    unnecessary.

    **Editing a record is not claiming one**, and the title is what tells them apart: an edit keeps
    the headline, a collision has a different one. So this compares titles rather than content, and
    a change that merely gains a section is untouched.

    Returns `[]` when `ref` cannot be resolved, and says so through `checked` below rather than
    passing silently — a check that quietly does nothing is worse than one scoped out loud.
    """
    problems: List[str] = []
    for path in sorted((repo / "docs" / "changes").glob("CHG-*.md")):
        rel = f"docs/changes/{path.name}"
        theirs = _at(repo, ref, rel)
        if theirs is None:
            continue                       # new here, or the ref has no such file: nothing to clash
        mine = _title(path.read_text(encoding="utf-8"))
        landed = _title(theirs)
        if mine and landed and mine != landed:
            problems.append(
                f"{path.stem}: this branch calls it {mine!r} and {ref} calls it {landed!r}. Two "
                f"changes are wearing one number — pick the next free id, checking unmerged "
                f"branches too, because nothing reserves one")
    return problems


def _ref_exists(repo: Path, ref: str) -> bool:
    try:
        done = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):    # pragma: no cover
        return False
    return done.returncode == 0


def main(argv: List[str]) -> int:
    repo = Path(argv[argv.index("--repo") + 1]) if "--repo" in argv else Path(".")
    problems = check(repo)

    # The collision check needs something to compare against. Tried in order, and reported when
    # none of them resolve: on a shallow checkout there is nothing to compare and saying so is the
    # whole point.
    against = next((r for r in ("origin/main", "main", "origin/HEAD") if _ref_exists(repo, r)), "")
    if against:
        problems += check_ids_are_not_claimed_twice(repo, against)
    else:
        print("ledger check: no main to compare against, so a change taking an id another change "
              "already has was NOT checked. Fetch the default branch to get that check.")
    if problems:
        print("ledger check failed:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"ledger check passed ({len(list((repo / 'docs' / 'changes').glob('CHG-*.md')))} changes)")
    return 0


if __name__ == "__main__":       # pragma: no cover
    sys.exit(main(sys.argv[1:]))
