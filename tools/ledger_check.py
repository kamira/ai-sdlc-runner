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
    # The negated forms, so `_standing` has something to nest 完成 inside. Without them
    # 未完成 matched only 完成 and read as finished — the rule needs both words present to
    # tell "not finished" from "finished" (CHG-20260831-02, risk seat).
    "未完成", "尚未完成", "未收尾",
) + tuple(
    # And the English ones, generated rather than typed, because the round that added the Chinese
    # negations recorded "every boundary rule so far was right about English" — and here it was the
    # inverse. English negates with a **space**, so the ASCII boundary rule fires between `not` and
    # `done`, and there was no vocabulary entry for `_standing` to nest the `done` inside. Measured:
    # every one of the twenty phrases — both prefixes against all **ten** ASCII `DONE` words —
    # classified as **DONE**. The round-8 risk seat said nine of ten and I repeated it in three
    # places without measuring; it is ten of ten, and the nine-item list it gave covered only eight
    # distinct words (CHG-20260831-04, idiom seat). Generated from `DONE`, so a word added there
    # cannot acquire the defect by being typed into one tuple and not the other.
    f"{prefix}{word}" for word in DONE if word.isascii()
    # The round-9 risk seat measured the gap in the first list: `never merged`, `no longer done`,
    # `not-done` and `un-merged` all still read as **finished**, because only these exact two
    # prefixes were generated. `isn't done` is still not covered and cannot be by a prefix list —
    # the apostrophe form puts the negation on the verb, not the state (CHG-20260831-04).
    for prefix in ("not ", "not yet ", "never ", "no longer ", "not-", "un-")
)


#: An acceptance's verdict, read from its `Conclusion` field the same way a change's status is read
#: from its `## Status` section — as a field, with the sentence after it cut off. The vocabulary is
#: closed for the same reason the two above are: a word nobody wrote down is a question, not a pass.
ACC_PASS = ("pass", "passes", "passed", "通過")
ACC_NOT_PASS = (
    "fail", "failed", "not sound", "rejected", "withdrawn", "superseded", "abandoned",
    # An acceptance whose verdict was never true, as against `superseded`, which says the change was
    # replaced. `void` and not `wrong`: these words are matched against the head of the Conclusion
    # field, and `wrong` is a general-purpose adjective that four acceptances already carry in that
    # **line** — they read as `pass` only because `_status_word` cuts at the punctuation before
    # reaching it, so what keeps them green is where the match happens, not the word.
    # `void` is verdict-shaped like every other entry — and it is inside *avoid*, which is why
    # `_matches` matches whole words rather than substrings.
    #
    # This word has teeth: `check` refuses a DONE change whose acceptance is void — see
    # `_never_held`. It fires on nothing in this ledger today and is prospective, like
    # `BRANCH_REQUIRED_FROM` above.
    #
    # Three rounds of corrections to the paragraphs that used to sit here are in CHG-20260830-08,
    # -09 and CHG-20260831-01. They belong in the records; a comment that carries its own changelog
    # stops being read, and this one had grown to the largest in the repository while still
    # asserting the substring matching its own change had removed (CHG-20260831-02, idiom seat).
    "void", "voided",
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


#: Verdicts that say the acceptance's own finding never held, as against `superseded`, which says
#: the change was replaced. Only these reopen a change — see the second half of `check`'s DONE test.
ACC_NEVER_TRUE = ("void", "voided")

#: Every never-true word must also be a refusal, or `check` calls it unrecognised and sends the
#: operator to a list that reopens nothing — pinned by
#: `test_a_never_true_verdict_is_a_refusal_and_the_refusal_names_all_three`. The **other**
#: direction is not a comparison between tuples at all: whether a word *means* "never true" is a
#: question about English. It is pinned one spelling at a time, behaviourally, by
#: `test_every_never_true_spelling_reopens_its_change` — because for one round this comment claimed
#: the pair was held "in both directions" and dropping `voided` from here left the file green with
#: a `**Voided.**` acceptance silently closing its change (CHG-20260831-05, defect seat).
#: It was an import-time `assert` for one round, and it constrained the containment that has never
#: drifted: the drift it was written for runs the other way. `Voided.` was refused as unrecognised,
#: the operator did what the refusal said and added it to `ACC_NOT_PASS` alone, and the void rule
#: went silently inert — an addition the `<=` assert reports as fine (CHG-20260831-03, conformance,
#: risk and idiom seats). It is a test now for a second reason: `python -O` deletes an `assert`, and
#: CI runs this file as a script.


def _never_held(repo: Path, chg_id: str) -> bool:
    """Does this change's acceptance record a verdict that was never true?"""
    acc = repo / "docs" / "acceptance" / f"ACC-{chg_id[4:]}.md"
    try:
        verdict = _verdict(acc.read_text(encoding="utf-8"))
    except OSError:                                   # pragma: no cover - the caller checked it
        return False
    return bool(_matches(verdict, ACC_NEVER_TRUE))


def _matches(verdict: str, words) -> List[tuple]:
    """Every `(start, end, word)` where one of these words appears *as a word*.

    Spans, not booleans, because the caller has to tell a word nested inside another word from two
    words sitting side by side, and only positions can do that — see `check`.

    The boundary is **ASCII word characters**, not `\\b`. `\\b` is defined against `\\w`, and CJK
    characters are `\\w`, so no boundary falls between Chinese text and an adjoining Latin word —
    which Chinese typography does not space. Measured, with `\\b`: `通過failed` read as a **pass**
    (the `failed` was invisible), and `已void` was not a recognised verdict at all. Two false greens
    in the lint that exists to catch false greens (CHG-20260831-02, conformance seat).

    Substring matching is what made `wrong` unusable, and `void` had the same defect one letter
    deeper — it is inside *avoid*, *avoided*, *unavoidable*.
    """
    found = []
    for word in words:
        pattern = (rf"(?<![A-Za-z0-9_]){re.escape(word)}(?![A-Za-z0-9_])"
                   if word.isascii() else re.escape(word))
        found += [(m.start(), m.end(), word) for m in re.finditer(pattern, verdict)]
    return found


def _standing(text: str, *vocabularies) -> List[List[str]]:
    """Which words of each vocabulary the text actually says, with nested matches dropped.

    Shared, because the status matcher and the verdict matcher are the same problem and only one of
    them had the rule. `done = [w for w in DONE if w in status]` read 未完成 and 尚未完成 — "not
    finished" — as **finished**, because they contain 完成 and nothing else matched to nest it in;
    a change that was not done was silently done, in the language this ledger is written in, over
    127 records with this lint wired into CI (CHG-20260831-02, risk seat).

    A match inside another match's span is the same text read short. Two matches at different places
    are a real disagreement and both stand — that is what makes 未通過 (one word) different from
    通過／未通過 (two).
    """
    hits = _matches(text, [word for words in vocabularies for word in words])
    standing = {word for start, end, word in hits
                if not any((s, e) != (start, end) and s <= start and end <= e
                           for s, e, _ in hits)}
    return [[word for word in words if word in standing] for words in vocabularies]


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

        done, open_ = _standing(status, DONE, IN_PROGRESS)

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
        elif done and _never_held(repo, chg_id):
            # The missing twin of the check above. That one asks whether an acceptance *exists*;
            # this asks whether it still says anything. A change closed on an acceptance whose
            # verdict was never true is closed on nothing — the same false green this file exists
            # to catch, one field over (CHG-20260830-09, ruled by the round-5 conformance seat).
            #
            # Scoped to `ACC_NEVER_TRUE`, not to every refusal: `superseded` means a change was
            # replaced, which is history and not a contradiction, and two acceptances sit under
            # done changes that way today. `void` means the verdict itself never held, and exactly
            # one pair was in that state when the seat ruled, and zero are now — this commit's
            # predecessor changed that one's status. Either way it needs no grandfathering, unlike
            # `BRANCH_REQUIRED_FROM` and `TESTS_MUST_EXIST_FROM`.
            problems.append(
                f"{chg_id}: its status says the work is finished, but ACC-{chg_id[4:]} records a "
                f"verdict that was never true — a change cannot be closed on a check its own "
                f"acceptance withdraws. Change the status word itself: `superseded` if a later "
                f"change redid the work, or one of: {', '.join(IN_PROGRESS[:4])}. "
                f"Explaining it after the word will not clear this, because `_status_word` reads "
                f"only the head of the line")

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
        # A match sitting *inside another match's span* is not a second opinion, it is the same
        # text read short: the 通過 in 未通過 is those characters, not a separate word. Two matches
        # at different places are a real disagreement — "Pass / withdrawn", or its Chinese form
        # 通過／未通過 — and must still be refused.
        #
        # By span, not by word. Dropping on `w in o` compared the *vocabulary entries*, so it could
        # not tell 未通過 (nesting) from 通過／未通過 (juxtaposition) at all: both look like "one
        # entry contains the other", and the second went clean. Measured (CHG-20260831-02).
        passed, refused = _standing(verdict, ACC_PASS, ACC_NOT_PASS)
        if not passed and not refused:
            problems.append(
                f"{acc_id}: conclusion {verdict!r} is not a recognised verdict. Add the word to "
                f"ACC_PASS or to ACC_NOT_PASS in tools/ledger_check.py — and to ACC_NEVER_TRUE as "
                f"well if it means the finding never held, or it will not reopen its change. An "
                f"unrecognised verdict "
                f"is not a pass")
            continue
        if passed and refused:
            problems.append(
                f"{acc_id}: conclusion {verdict!r} reads as both a pass ({passed}) and a refusal "
                f"({refused}); the next reader cannot act on it")
            continue
        if not passed:
            continue

        # `_standing`, like the other two. This was the one raw `w in status` left in the file,
        # in the same function as the docstring naming that construction as the bug (CHG-20260831-03,
        # conformance, risk and idiom seats). Nothing in the ledger tripped it wrongly — it was
        # exposure, and the next word added to `AWAITING_DECISION` would have inherited it.
        waiting, = _standing(_status_word(_status_line(texts[f"CHG-{suffix}"])), AWAITING_DECISION)
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


#: A paragraph break ends the window: an explanation belongs in one paragraph with the name.
#: A **whitespace-only** line is one — `"\\n\\n"` as a literal missed a line carrying a single space
#: or a tab, so any editor that leaves trailing whitespace laundered a ghost across a paragraph
#: break (CHG-20260831-05, defect seat).
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")

#: How far from the name the phrase may sit, in **characters**, checked after the match. `{0,200}`
#: bounds *repetitions* of an alternation whose second branch swallows a whole backticked name, so
#: the "at most 200 characters" this acceptance disclosed measured 3150 in the round-10
#: conformance seat's hands — fifteen times the number a reader was given to judge by
#: (CHG-20260831-05, VETO).
EXCUSE_WINDOW = 400

#: Ordinary raw strings, like the five other regexes in this file. The `chr(92)` spelling that
#: stood here for one round justified itself as "this file is edited through tooling that eats a
#: lone backslash" — and `_tests_that_exist`, six lines above, matches `test_\\w+` with a plain
#: backslash and always has. The tooling that ate them was the author's, not the file's
#: (CHG-20260831-05, idiom seat).
TICK_LITERAL = chr(96)
_QUOTED_TEST = r"`(test_\w+)`"
#: What counts as saying it is gone. Four verbs, because the refusal says "say in the record
#: that the test was **since removed** and why" and does not name a phrasing — `deleted in`,
#: `dropped in` and `renamed in` were all refused, and so was the markdown-link form
#: `[CHG-…](../changes/CHG-….md)`, in a ledger written in markdown, because `]` is not a digit
#: (CHG-20260831-05, defect seat).
_REMOVED_BY = (r"(?:removed|deleted|dropped|renamed)\s+(?:in|by)\s+"
               r"\[?((?:CHG|ACC)-\d{8}-\d{2})\]?")

#: What the window may cross: anything that is not a backtick, or another backticked test name.
#: The second branch is what makes "`test_a`, `test_b` and `test_c` were removed in CHG-X" work,
#: and it is also what leaves the bystander case open — see `_excused`.
_SPAN = r"(?:[^`]|`test_\w+`)*?"


def _excused(text: str, name: str, ledger_ids) -> bool:
    """Does this record say, next to the name itself, that this test was removed and by what?

    The refusal below offers *"say in the record that the test was since removed and why"* as a
    remedy, and for one round the check did not honour it at all: a record that did exactly that
    was still refused, because the sentence saying the test is gone contains the name. The first
    fix honoured it and then over-honoured it — `.*?` from the first backticked name swallowed the
    span, so a sentence naming two removed tests still failed; a *live* test cited earlier on the
    same line was excused as a bystander; and `removed in CHG-19700101-99`, an id that has never
    existed, laundered anything beside it (CHG-20260831-04, defect and risk seats).

    Three things bound it, and the third is the one that was claimed and not held: the window stays
    in one paragraph, the change id must be a record that exists, and the whole match must be at
    most `EXCUSE_WINDOW` characters. Supporting the list form is what leaves the bystander case
    open — a live test named inside such a run is excused with it — and that is bounded here rather
    than closed, because a list and a bystander are the same sentence to a regex.
    """
    quoted = TICK_LITERAL + re.escape(name) + TICK_LITERAL
    for pattern in (quoted + _SPAN + _REMOVED_BY, _REMOVED_BY + _SPAN + quoted):
        for found in re.finditer(pattern, text):
            said = found.group(0)
            if (len(said) <= EXCUSE_WINDOW and not _PARAGRAPH_BREAK.search(said)
                    and found.group(1) in ledger_ids):
                return True
    return False

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
    ledger_ids = {p.stem for p in (repo / "docs" / "changes").glob("CHG-*.md")}
    ledger_ids |= {p.stem for p in (repo / "docs" / "acceptance").glob("ACC-*.md")}
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
        text = path.read_text(encoding="utf-8")
        named = sorted(set(re.findall(_QUOTED_TEST, text)))
        ghosts = [name for name in named
                  if name not in known and not _excused(text, name, ledger_ids)]
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
