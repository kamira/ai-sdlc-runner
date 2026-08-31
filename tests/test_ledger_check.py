"""Our own ledger lint (CHG-20260823-01).

Replaces a gate that lived inside the vendored skill. Two of its three checks exist because the old
one got them wrong here, so both failures are reproduced rather than assumed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ledger_check  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _repo(tmp_path, chg_body, acc=None):
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "acceptance").mkdir(parents=True)
    (tmp_path / "docs" / "changes" / "CHG-20260901-01.md").write_text(chg_body, encoding="utf-8")
    if acc:
        (tmp_path / "docs" / "acceptance" / "ACC-20260901-01.md").write_text(acc, encoding="utf-8")
    return tmp_path


#: `chr(10)` rather than an escape, for the few fixtures assembled by concatenation
#: rather than written as one literal. The inline form is this file's norm and stays that way;
#: this is for the cases where a literal would be unreadable.
NEWLINE = chr(10)

HEADER = "- Project: x\n- Branch: b\n- Date: 2026-09-01\n- Risk: low\n"

#: A change claiming to be closed, and an acceptance saying the check that closed it never held.
DONE_CHANGE = f"# CHG\n{HEADER}\n## Status\n\n**Accepted**\n"
VOID_ACCEPTANCE = "# ACC\n- Conclusion: **VOID.** the fix never worked\n"

#: The same change, not claiming to be closed — the escape hatch a void acceptance leaves open.
SUPERSEDED_CHANGE = f"# CHG\n{HEADER}\n## Status\n\n**Superseded** — the fix was redone\n"

#: A change still asking the question its acceptance may or may not have answered — the only
#: fixture on which `check` says something different for a pass than it does for a refusal.
AWAITING_CHANGE = SUPERSEDED_CHANGE.replace("**Superseded** — the fix was redone",
                                            "**Under review**")


def test_this_repos_own_ledger_passes():
    assert ledger_check.check(REPO) == []


def test_a_change_reported_built_without_an_acceptance_record_fails(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nbuilt and shipped.\n")
    problems = ledger_check.check(repo)
    assert any("no matching ACC" in p or "nothing saying it was checked" in p for p in problems)


def test_the_same_change_passes_once_it_has_one(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nbuilt and shipped.\n", acc="# ACC\n")
    assert ledger_check.check(repo) == []


def test_a_change_closed_on_a_void_acceptance_is_reported(tmp_path):
    """The missing twin of the no-acceptance check.

    That one asks whether an acceptance *exists*; this asks whether it still says anything. A change
    closed on an acceptance whose verdict was never true is closed on nothing — the same false green
    this lint exists to catch, one field over.

    Scoped to `void` rather than to every refusal: `superseded` means the change was replaced, which
    is history and not a contradiction, and two acceptances sit under done changes that way
    (CHG-20260830-09, ruled by the round-5 conformance seat).
    """
    repo = _repo(tmp_path, DONE_CHANGE, acc=VOID_ACCEPTANCE)

    problems = ledger_check.check(repo)

    assert len(problems) == 1, problems
    assert "never true" in problems[0]
    assert "Change the status word itself" in problems[0], (
        "a refusal has to say what to do next, and only what actually works")
    assert "will not clear this" in problems[0], (
        "the refusal has to say that explaining it after the status word does nothing")


def test_a_change_superseded_by_a_later_one_is_not_reopened_by_its_acceptance(tmp_path):
    """`superseded` is history, not a contradiction, so it must not trip the rule above."""
    repo = _repo(tmp_path, DONE_CHANGE,
                 acc="# ACC\n- Conclusion: **Superseded** by a later change\n")

    assert ledger_check.check(repo) == []


def test_a_change_whose_status_word_is_no_longer_done_passes(tmp_path):
    """The escape hatch, named for what it actually is.

    Its first name was `..._that_says_why_a_void_acceptance_does_not_close_it_passes`, and the
    refusal offered that as an alternative — but `_status_word` reads only the head of the line,
    so `**Accepted** — here is why the void ACC does not reopen it` still parses as `accepted`
    and still fails. The body always set `**Superseded**`, so the clause was pinned by a test
    that would have stayed green if it were deleted (CHG-20260831-01, risk seat).
    """
    repo = _repo(tmp_path, SUPERSEDED_CHANGE, acc=VOID_ACCEPTANCE)

    assert ledger_check.check(repo) == []


def test_a_draft_needs_no_acceptance_record(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\ndraft — nothing built yet.\n")
    assert ledger_check.check(repo) == []


def test_prose_about_acceptance_does_not_change_a_documents_status(tmp_path):
    """The failure this lint was rewritten to stop. The previous gate scanned the whole document, so
    writing the word in a paragraph flipped the classification — three times in one session, twice
    inside the sentence explaining the first time. Status is a field; this reads the field."""
    body = (HEADER +
            "\n## Independent review\n\nThe first round was not accepted, and every task is built.\n"
            "\n## Status\n\ndraft — nothing built yet.\n")
    assert ledger_check.check(_repo(tmp_path, body)) == []


def test_a_missing_required_field_is_reported(tmp_path):
    repo = _repo(tmp_path, "- Project: x\n- Date: 2026-09-01\n\n## Status\n\ndraft.\n")
    problems = ledger_check.check(repo)
    assert any("Risk" in p and "Branch" in p for p in problems)


def test_the_field_rule_is_prospective(tmp_path):
    """A lint that fails on history it cannot change teaches people to ignore the lint."""
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "acceptance").mkdir(parents=True)
    (tmp_path / "docs" / "changes" / "CHG-20260101-01.md").write_text(
        "- Project: x\n- Date: 2026-01-01\n- Risk: low\n\n## Status\n\ndraft.\n", encoding="utf-8")
    assert ledger_check.check(tmp_path) == []


def test_a_change_with_no_status_section_is_reported(tmp_path):
    assert any("no Status section" in p
               for p in ledger_check.check(_repo(tmp_path, HEADER)))


# --------------------------------------------------------------------------------------
# the vocabulary of "finished" is closed
# --------------------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.mark.parametrize("status", ["completed", "merged", "done", "shipped",
                                    "closed", "已驗收", "released"])
def test_every_way_of_saying_finished_needs_an_acceptance(tmp_path, status):
    """The finding this closes: the lint knew only the word "built", so a change whose status said
    "accepted" or "完成" passed with no ACC at all — a false green written in one word."""
    repo = _repo(tmp_path, HEADER + f"\n## Status\n\n{status}\n")
    problems = ledger_check.check(repo)
    assert any("nothing saying it was checked" in p for p in problems), status


@pytest.mark.parametrize("status", ["in progress", "blocked", "草稿", "進行中",
                                    "superseded", "pending"])
def test_an_unfinished_change_needs_nothing(tmp_path, status):
    repo = _repo(tmp_path, HEADER + f"\n## Status\n\n{status}\n")
    assert ledger_check.check(repo) == []


def test_a_status_nobody_wrote_down_is_a_problem_not_a_pass(tmp_path):
    """The escape hatch itself: treating an unrecognised word as "not finished" is how the previous
    version let four different words through. An unknown status is now a failure that names the fix.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nfine\n")
    problems = ledger_check.check(repo)
    assert any("not a recognised one" in p for p in problems)
    assert any("ledger_check.py" in p for p in problems)


def test_the_commentary_after_the_status_does_not_decide_the_status(tmp_path):
    """`draft — all 9 tasks built` is a draft. The status is the head of the line; the rest is
    prose, and prose has changed this repo's document classification before."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**草稿 / draft — all 9 tasks built.**\n")
    assert ledger_check.check(repo) == []


def test_a_finished_status_with_commentary_still_needs_its_acceptance(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\naccepted (see the ACC) — everything green.\n")
    assert any("nothing saying it was checked" in p for p in ledger_check.check(repo))


def test_a_status_that_reads_both_ways_is_refused(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\ndraft done\n")
    assert any("cannot act on it" in p for p in ledger_check.check(repo))


def test_the_two_lists_do_not_overlap():
    """A word on both lists would make every status using it ambiguous, forever."""
    assert not set(ledger_check.DONE) & set(ledger_check.IN_PROGRESS)


# ── the other direction, which nothing walked (CHG-20260828-02) ─────────────────────────────────

def test_an_acceptance_for_a_change_that_does_not_exist_is_refused(tmp_path):
    """Every check above starts at a CHG, so an ACC naming no change was invisible.

    The ledger reported `passed` while an acceptance vouched for nothing. Traceability is the whole
    reason both files are kept, and it only holds if it holds both ways.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nProposed.\n")
    (repo / "docs" / "acceptance" / "ACC-19990101-01.md").write_text(
        "# ACC-19990101-01\n\n- Target CHG: CHG-19990101-01\n", encoding="utf-8")
    problems = ledger_check.check(repo)
    assert any("ACC-19990101-01" in p and "no change" in p for p in problems), problems


def test_an_acceptance_filed_against_the_wrong_change_is_refused(tmp_path):
    """A record filed under one id while claiming another points two ways, and a reader following
    either lands somewhere the other contradicts."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\n- Target CHG: CHG-20260714-09\n")
    problems = ledger_check.check(repo)
    assert any("Target CHG" in p for p in problems), problems


def test_an_acceptance_that_names_no_target_is_not_a_problem(tmp_path):
    """Absence is not disagreement. Older records predate the field, and requiring it would turn a
    traceability check into a formatting one — which is how a useful check gets switched off."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\nNo target line at all.\n")
    assert ledger_check.check(repo) == []


def test_a_matching_pair_is_still_accepted(tmp_path):
    """The check must not fire on the normal case — it would refuse every real acceptance."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\nAccepted.\n",
                 acc="# ACC-20260901-01\n\n- Target CHG: CHG-20260901-01\n")
    assert ledger_check.check(repo) == []


# ── two changes wearing one number (CHG-20260828-06) ────────────────────────────────────────────

HEADER_06 = "- Project: x\n- Branch: b\n- Date: 2026-09-01\n- Risk: low\n"


def _git_repo(tmp_path, title):
    """A repository with one change on `main`, so a branch can be compared against it."""
    import subprocess
    root = tmp_path / "repo"
    (root / "docs" / "changes").mkdir(parents=True)
    (root / "docs" / "acceptance").mkdir(parents=True)
    (root / "docs" / "changes" / "CHG-20260901-01.md").write_text(
        f"# {title}\n\n{HEADER_06}\n## Status\n\nProposed.\n", encoding="utf-8")

    def git(*args):
        subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "T")
    git("config", "user.email", "t@example.invalid")
    git("add", "-A")
    git("commit", "-q", "-m", "one change")
    return root


def test_a_second_change_taking_a_taken_id_is_refused(tmp_path):
    """The collision that happened, and that nothing could see.

    A number is claimed by writing the file, and nothing reserves one. Two sessions pick from the
    same free list, and `check` cannot notice: two files with one name cannot coexist in a tree, so
    it surfaces only as a merge conflict — after both branches have gone green separately.

    CHG-20260828-04 was claimed at 12:23 by an unmerged branch and again at 13:00 by a change that
    merged. Two records, one number, both passing every check that existed. The second was
    renumbered by hand afterwards; this check is what makes that unnecessary next time.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    (root / "docs" / "changes" / "CHG-20260901-01.md").write_text(
        f"# CHG-20260901-01 — a completely different change\n\n{HEADER_06}\n## Status\n\nProposed.\n",
        encoding="utf-8")

    problems = ledger_check.check_ids_are_not_claimed_twice(root, "main")
    assert problems, "two changes wearing one number went unnoticed"
    assert "wearing one number" in problems[0]
    assert "a completely different change" in problems[0], "it must name both titles"


def test_editing_an_existing_record_is_not_a_collision(tmp_path):
    """Editing a record is not claiming one, and this fires on every PR that touches a CHG.

    CHG-20260827-21 gained two whole sections after it was accepted — task 5a and task 6 — and a
    check that called that a collision would refuse the ordinary way this ledger is kept.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    path = root / "docs" / "changes" / "CHG-20260901-01.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n## A section added later\n\nMore.\n",
                    encoding="utf-8")

    assert ledger_check.check_ids_are_not_claimed_twice(root, "main") == []


def test_a_genuinely_new_id_is_not_a_collision(tmp_path):
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    (root / "docs" / "changes" / "CHG-20260901-02.md").write_text(
        f"# CHG-20260901-02 — the next one\n\n{HEADER_06}\n## Status\n\nProposed.\n",
        encoding="utf-8")

    assert ledger_check.check_ids_are_not_claimed_twice(root, "main") == []


def test_a_ref_that_does_not_resolve_checks_nothing_rather_than_passing_quietly(tmp_path, capsys):
    """On a shallow checkout there is nothing to compare against, and saying so is the point.

    A check that quietly does nothing is worse than one scoped out loud — this repository's own
    finding about `--sandbox`, applied to a lint.
    """
    root = _git_repo(tmp_path, "CHG-20260901-01 — the first change")
    assert ledger_check.check_ids_are_not_claimed_twice(root, "origin/nonexistent") == []

    # And through `main`, which has to find nothing to compare against — so a plain directory,
    # not the repository above: that one has a `main` and would be checked normally, which is the
    # correct behaviour and the wrong test.
    plain = _repo(tmp_path / "plain", HEADER + "\n## Status\n\nProposed.\n")
    ledger_check.main(["--repo", str(plain)])
    said = capsys.readouterr().out
    assert "was NOT checked" in said, said
    assert "Fetch the default branch" in said, "it must say how to get the check back"


# ── a passing acceptance is a decision the change cannot still be waiting for (CHG-20260828-16) ──
#
# Both directions above check that a record *exists*. Neither read what either record said, so five
# changes carried a passing acceptance while their own status still read "under review" or
# "proposed" — and this lint reported the ledger passed, while the handshake gate reading the same
# two files named those same five as unclosed.

PASSED = "- Target CHG: CHG-20260901-01\n- Conclusion: **Pass.** 9 cases.\n"


def test_a_change_under_review_whose_acceptance_passed_is_reported(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n", acc=PASSED)
    problems = ledger_check.check(repo)
    assert any("already made" in p for p in problems), problems


def test_a_proposed_change_whose_acceptance_passed_is_reported(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Proposed.**\n", acc=PASSED)
    assert any("already made" in p for p in ledger_check.check(repo))


def test_the_message_names_the_change_the_status_and_the_record(tmp_path):
    """A reader has to be able to act on it without opening both files to work out which two."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n", acc=PASSED)
    said = next(p for p in ledger_check.check(repo) if "already made" in p)
    assert "CHG-20260901-01" in said
    assert "ACC-20260901-01" in said
    assert "under review" in said


def test_closing_the_change_settles_it(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Accepted** — see ACC-20260901-01.\n",
                 acc=PASSED)
    assert ledger_check.check(repo) == []


def test_a_change_superseded_after_it_was_accepted_is_not_a_contradiction(tmp_path):
    """The distinction the check turns on, and the reason it is not simply "ACC exists → done".

    A change can pass acceptance and *later* be superseded, halted or withdrawn. An acceptance
    sitting behind one of those is history. Only the statuses that say the decision has not been
    made yet can contradict a record of it having been made.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Superseded** in part by CHG-20260901-02.\n",
                 acc=PASSED)
    assert ledger_check.check(repo) == []


def test_a_halted_change_that_had_passed_is_not_a_contradiction(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Halted.**\n", acc=PASSED)
    assert ledger_check.check(repo) == []


def test_an_acceptance_that_did_not_pass_leaves_the_change_open(tmp_path):
    """`ACC-20260823-50` is exactly this: both seats returned `not sound`, so it was withdrawn."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n",
                 acc="- Target CHG: CHG-20260901-01\n- Conclusion: **Withdrawn.** Both seats "
                     "returned `not sound`.\n")
    assert ledger_check.check(repo) == []


def test_the_sentence_after_the_verdict_does_not_argue_with_it(tmp_path):
    """`ACC-20260827-23` reads `Pass, on a reduced scope that the operator approved`.

    Reading the whole line would let the explanation change the verdict, which is the failure
    `_status_word` exists to prevent, one document over.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n",
                 acc="- Target CHG: CHG-20260901-01\n- Conclusion: **Pass, on a reduced scope "
                     "that the operator approved and that is not the original one.**\n")
    assert any("already made" in p for p in ledger_check.check(repo))


def test_prose_about_passing_is_not_a_verdict(tmp_path):
    """The verdict is a field, and a record that merely *discusses* passing has not stated one.

    Absence is not itself a problem — older records predate the field, and requiring it here would
    turn a traceability check into a formatting one, which is the argument `_target_chg` already
    makes. What must not happen is prose deciding a verdict.
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n",
                 acc="# ACC\n\nEvery check passed and the suite is green.\n")
    assert ledger_check.check(repo) == []


def test_an_unrecognised_verdict_is_a_problem_rather_than_a_pass(tmp_path):
    """The same closed-vocabulary argument as `DONE`/`IN_PROGRESS`, one document over."""
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n",
                 acc="- Target CHG: CHG-20260901-01\n- Conclusion: **Inconclusive.**\n")
    problems = ledger_check.check(repo)
    assert any("not a recognised verdict" in p for p in problems), problems
    assert any("ACC_PASS or to ACC_NOT_PASS" in p for p in problems), "it must say how to fix it"


# 未通過 and `Pass / withdrawn` had a standalone test each. They are rows of `VERDICT_CASES`
# now, which is where a later boundary rule has to satisfy every head at once; the standalone copies
# asserted less against a fixture that could not tell a refusal from a pass at all, which is finding
# 9 of the same round (CHG-20260831-03, idiom seat).


def test_this_repos_own_changes_are_all_closed_or_openly_open():
    """The five this change found are closed in the same commit that added the check.

    Left for a later pass, the lint would have shipped red, and a lint that ships red is a lint
    people learn to skip.
    """
    assert not [p for p in ledger_check.check(REPO) if "already made" in p]


# ── a record naming a test that does not exist is vouching for nothing (CHG-20260828-20) ───────
#
# The point of writing `pinned by ``test_foo``` is that a later reader can go and look. When
# `test_foo` has been renamed or deleted the sentence still reads like evidence and is not — and
# 97 such references had accumulated here, most to an architecture (`executors.py`, `dashboard.py`,
# `workspace.py`) that no longer exists. Nothing noticed, because nothing looked.


def _ledger(tmp_path, record_name, body, tests=("def test_a_real_one(): pass\n",)):
    (tmp_path / "docs" / "changes").mkdir(parents=True)
    (tmp_path / "docs" / "acceptance").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    for n, source in enumerate(tests):
        (tmp_path / "tests" / f"test_subject{n or ''}.py").write_text(source, encoding="utf-8")
    folder = "changes" if record_name.startswith("CHG") else "acceptance"
    (tmp_path / "docs" / folder / f"{record_name}.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_recent_record_naming_a_test_that_does_not_exist_is_reported(tmp_path):
    repo = _ledger(tmp_path, "ACC-20260901-01", "Pinned by `test_a_ghost`.\n")
    problems = ledger_check.check_named_tests_exist(repo)
    assert any("test_a_ghost" in p for p in problems), problems


def test_the_message_says_what_to_do_about_it(tmp_path):
    repo = _ledger(tmp_path, "ACC-20260901-01", "Pinned by `test_a_ghost`.\n")
    said = ledger_check.check_named_tests_exist(repo)[0]
    assert "ACC-20260901-01" in said
    assert "fix the name" in said and "since removed" in said


def test_a_test_that_exists_is_not_reported(tmp_path):
    repo = _ledger(tmp_path, "ACC-20260901-01", "Pinned by `test_a_real_one`.\n")
    assert ledger_check.check_named_tests_exist(repo) == []


def test_naming_the_module_counts_as_naming_a_test(tmp_path):
    """Both spellings are in use: `test_flow` names a file, `test_a_halt_is_final` names a case.

    A rule that knew only functions would report every file reference as a ghost, which is how a
    lint teaches people to stop reading it.
    """
    repo = _ledger(tmp_path, "ACC-20260901-01", "See `test_subject`.\n")
    assert ledger_check.check_named_tests_exist(repo) == []


def test_a_record_older_than_the_cutoff_is_left_alone(tmp_path):
    """Prospective, for the reason `BRANCH_REQUIRED_FROM` gives.

    The 97 existing references are history. Rewriting them would be inventing a past rather than
    fixing one, and a lint that fails on history it cannot change teaches people to ignore it.
    """
    repo = _ledger(tmp_path, "ACC-20260617-03", "Pinned by `test_a_ghost`.\n")
    assert ledger_check.check_named_tests_exist(repo) == []


def test_prose_mentioning_a_test_is_not_a_pointer(tmp_path):
    """Only backticked names. These records discuss tests constantly, in sentences."""
    repo = _ledger(tmp_path, "ACC-20260901-01",
                   "We considered writing test_a_ghost and decided against it.\n")
    assert ledger_check.check_named_tests_exist(repo) == []


def test_changes_are_checked_as_well_as_acceptances(tmp_path):
    repo = _ledger(tmp_path, "CHG-20260901-01", "Done-when: `test_a_ghost` passes.\n")
    assert any("test_a_ghost" in p for p in ledger_check.check_named_tests_exist(repo))


def test_the_check_runs_as_part_of_the_ledger(tmp_path):
    """It has to be wired in, not merely written. This repository has shipped an unwired guard."""
    repo = _ledger(tmp_path, "CHG-20260901-01",
                   HEADER + "\n## Status\n\nProposed.\n\nPinned by `test_a_ghost`.\n")
    assert any("test_a_ghost" in p for p in ledger_check.check(repo))


def test_this_repositorys_own_recent_records_name_only_tests_that_exist():
    """Zero today, which is why the cutoff is where it is: the rule ships green."""
    assert ledger_check.check_named_tests_exist(REPO) == []


#: Verdict heads that have each been classified wrongly at some point, with what they must mean.
#: The Chinese ones are the reason this table exists: `\b` is defined against `\w`, CJK characters
#: are `\w`, and Chinese typography does not space Latin words — so every boundary rule tried so far
#: has been wrong about one of these while looking right on the English ones
#: (CHG-20260831-02, conformance seat).
VERDICT_CASES = [
    ("**未通過**", "refusal", "a word containing another is one word, not two opinions"),
    ("**通過／未通過**", "both", "two words side by side are a real disagreement"),
    ("**Pass / withdrawn.**", "both", "the English form of the same thing"),
    ("**通過failed**", "both", "a Latin word against Chinese text is still that word"),
    ("**驗收pass**", "pass", "and so is this one"),
    ("**Avoided**", "unrecognised", "`void` inside `avoided` is not a verdict"),
    ("**Pass.** fine", "pass", "the ordinary case"),
]


@pytest.mark.parametrize("head,means,why", VERDICT_CASES,
                         ids=[c[0].strip("*") for c in VERDICT_CASES])
def test_a_verdict_head_means_one_thing(tmp_path, head, means, why):
    r"""Every boundary rule tried here has been right about English and wrong about Chinese.

    `\b` let `通過failed` read as a **pass** and made `已void` unrecognised; matching the vocabulary
    entries against each other could not tell 未通過 (one word) from 通過／未通過 (two). Both were
    measured after shipping, so the cases live in a table that a later rule has to satisfy whole.
    """
    # The change is **awaiting a decision**, so a pass and a refusal are distinguishable: a pass
    # closes the question the status is still asking and `check` says so; a refusal leaves it open
    # and says nothing. Against `SUPERSEDED_CHANGE` both landed in one `assert not problems`, so the
    # `refusal` rows asserted exactly what the `pass` rows did and the table pinned six heads while
    # claiming seven. Proved by moving 未通過 into `ACC_PASS`: the table stayed green
    # (CHG-20260831-03, conformance and idiom seats).
    repo = _repo(tmp_path, AWAITING_CHANGE, acc=f"# ACC\n- Conclusion: {head}\n")
    problems = ledger_check.check(repo)
    said = problems[0] if problems else ""

    if means == "both":
        assert "reads as both" in said, f"{why}: {said or 'clean'}"
    elif means == "unrecognised":
        assert "not a recognised verdict" in said, f"{why}: {said or 'clean'}"
    elif means == "pass":
        assert "already made" in said, f"{why}: {said or 'clean'}"
    else:
        assert not problems, f"{why}: {said}"


#: Status heads and what each must mean. The Chinese negations are the reason: 未完成 and 尚未完成
#: contain 完成, so a substring matcher read "not finished" as **finished** — silently, over a
#: 127-change ledger, in the language it is written in (CHG-20260831-02, risk seat).
STATUS_CASES = [
    ("完成", "done"), ("已完成", "done"), ("已收尾", "done"), ("accepted", "done"),
    ("未完成", "open"), ("尚未完成", "open"), ("未收尾", "open"),
    ("abandoned", "open"), ("draft", "open"),
    # English negates with a space, so no ASCII boundary falls inside `not done` and there was no
    # vocabulary entry for the `done` to nest in. **All ten** English DONE words read as *finished*
    # when negated, across both prefixes — the exact inverse of the finding the round above
    # recorded, which was that every boundary rule so far had been right about English
    # (CHG-20260831-03; the count corrected in -04, idiom seat).
    ("not done", "open"), ("not yet complete", "open"), ("not merged", "open"),
    ("not accepted", "open"), ("not yet shipped", "open"),
    # And the forms the first generator missed, all measured as **finished** before
    # (CHG-20260831-04, risk seat). `isn't done` is still not covered: the apostrophe form negates
    # the verb rather than the state, and a prefix list cannot reach it.
    ("never merged", "open"), ("no longer done", "open"), ("not-done", "open"),
    ("un-merged", "open"),
]


@pytest.mark.parametrize("status,means", STATUS_CASES, ids=[c[0] for c in STATUS_CASES])
def test_a_status_head_falls_on_one_side(tmp_path, status, means):
    """A status that means *not finished* must not require an acceptance, and vice versa.

    `abandoned` is the English case of the same bug — it contains `done`, so a word this file lists
    under `IN_PROGRESS` read as both and could not be used.
    """
    repo = _repo(tmp_path, f"# CHG\n{HEADER}\n## Status\n\n**{status}**\n")
    problems = ledger_check.check(repo)

    if means == "done":
        assert any("nothing saying it was checked" in p for p in problems), f"{status}: {problems}"
    else:
        assert problems == [], f"{status} means not finished, so nothing is required: {problems}"


def test_a_never_true_verdict_is_a_refusal_and_the_refusal_names_all_three(tmp_path):
    """The two tuples are hand-written and must agree in **both** directions.

    An import-time `assert set(ACC_NEVER_TRUE) <= set(ACC_NOT_PASS)` stood here for one round and
    constrained the containment that has never drifted. The drift it was written for runs the other
    way: `Voided.` was refused as unrecognised, the operator did what the refusal said and added it
    to `ACC_NOT_PASS` alone, and the void rule went silently inert — which that `<=` reports as
    fine. It is a test for a second reason too: `python -O` deletes an `assert`, and CI runs
    `ledger_check.py` as a script (CHG-20260831-03, conformance, risk and idiom seats).
    """
    missing = sorted(set(ledger_check.ACC_NEVER_TRUE) - set(ledger_check.ACC_NOT_PASS))
    assert not missing, (
        f"{missing} would be reported as an unrecognised verdict, and the message would send the "
        f"operator to a list that reopens nothing. Add them to ACC_NOT_PASS as well")

    # The other direction cannot be checked by comparing the tuples: whether a word *means* "never
    # true" is a question about English, and `rstrip("d")` on both sides — what stood here for one
    # round — compares nothing at all, so `ACC_NEVER_TRUE = ("void",)` alone left the whole table
    # green (CHG-20260831-04, defect seat). What actually prevents the drift is the refusal an
    # operator follows, so that is what this asserts: the message that sends someone to add a word
    # must name all three lists, or following it disarms the void rule exactly as `Voided.` did.
    said = ledger_check.check(_repo(
        tmp_path, SUPERSEDED_CHANGE, acc="# ACC" + NEWLINE + "- Conclusion: **Nullified.**" + NEWLINE))

    assert said and "not a recognised verdict" in said[0], said
    for tuple_name in ("ACC_PASS", "ACC_NOT_PASS", "ACC_NEVER_TRUE"):
        assert tuple_name in said[0], (
            f"the refusal names {tuple_name!r} nowhere, so an operator who follows it can add a "
            f"never-true verdict to ACC_NOT_PASS alone and silently switch the void rule off")


def test_the_awaiting_matcher_reads_words_not_substrings(tmp_path):
    """The third vocabulary scan in the file, and the last one still written as `w in status`.

    Two of the three were converted to `_standing` and this one was left, in the same function as
    the docstring that names `[w for w in WORDS if w in status]` as the bug. It tripped on nothing
    in the real ledger, which is why it survived a round: it was exposure, not a live defect, and
    the next word added to `AWAITING_DECISION` would have inherited it (CHG-20260831-03,
    conformance, risk and idiom seats).
    """
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Redrafted**\n",
                 acc="# ACC\n- Conclusion: **Pass.**\n")
    problems = ledger_check.check(repo)

    # `draft` sits inside `Redrafted` and is not a word there. The status is unrecognised and that
    # is its own problem, correctly raised; what must not be raised is the second sentence telling
    # the operator their change is waiting for a decision the acceptance already made.
    assert not any("already made" in p for p in problems), problems
    assert any("nobody wrote down" in p or "not a recognised" in p for p in problems), problems


#: What a record may say about a test that is gone, and whether the lint accepts it. The remedy
#: `check_named_tests_exist` offers is "say in the record that the test was since removed and why".
#: For one round nothing tested whether saying so worked: the rule was held up only by the accident
#: that one real acceptance happened to use the one phrasing that did, so rewording that blockquote
#: would have left the fix untested (CHG-20260831-04, conformance seat, VETO).
GHOST_EXCUSES = [
    ("`test_gone` was removed in CHG-20260901-01.", True, "the advertised case"),
    ("`test_gone_a` and `test_gone` were removed in CHG-20260901-01.", True, "a list of two"),
    ("removed in CHG-20260901-01: `test_gone`.", True, "the reverse order"),
    ("Pinned by `test_this_repos_own_ledger_passes`, and `test_gone` was removed in "
     "CHG-20260901-01.", True, "a live test cited first does not block it"),
    ("`test_gone` — removed in CHG-19700101-99.", False, "a change id nobody can open"),
    ("`test_gone` is the evidence." + NEWLINE + NEWLINE + "Other things were removed in "
     "CHG-20260901-01.", False, "an unrelated removal a paragraph away"),
    ("`test_gone` was deleted at some point.", False, "no change named at all"),
    # The refusal says "say in the record that the test was since removed and why" and names no
    # phrasing, so it has to accept the ones a person writes. All five of these were refused
    # (CHG-20260831-05, defect seat) — the markdown-link form worst of all, in a markdown ledger,
    # because `]` is not a digit.
    ("`test_gone` was deleted in CHG-20260901-01.", True, "deleted"),
    ("`test_gone` was dropped in CHG-20260901-01.", True, "dropped"),
    ("`test_gone` was renamed in CHG-20260901-01.", True, "renamed"),
    ("`test_gone` was removed by CHG-20260901-01.", True, "removed *by*, not *in*"),
    ("`test_gone` was removed in [CHG-20260901-01](../changes/CHG-20260901-01.md).", True,
     "the markdown-link form"),
    # A paragraph break ends the window — and a line carrying one space is a paragraph break. The
    # A paragraph break ends the window — and a line carrying one space is a paragraph break.
    # A two-character newline literal missed it, so any editor leaving trailing whitespace
    # laundered a ghost across the break.
    ("`test_gone` is the evidence." + NEWLINE + "   " + NEWLINE
     + "Other things were removed in CHG-20260901-01.", False,
     "a paragraph away, with a space on the blank line"),
    # What the window may **not** cross. Replacing the span with `.*?` — the previous round's
    # over-broad form — leaves every other row green, so this is the row that pins it.
    ("`test_gone` is pinned by `some_helper`, which was removed in CHG-20260901-01.", False,
     "a backtick that is not a test name"),
    # How far the phrase may sit from the name, in characters. `EXCUSE_WINDOW` was disclosed as
    # "at most 200 characters" and was 200 *repetitions* of an alternation whose second branch
    # swallows a whole backticked name — the round-10 conformance seat measured 3150, and nothing
    # here noticed when the bound was removed entirely (CHG-20260831-05, VETO).
    ("`test_gone` " + ("and a great deal of unrelated prose in between " * 12)
     + "was removed in CHG-20260901-01.", False, "further away than the window allows"),
    ("`test_gone` " + ("and a little prose in between " * 3)
     + "was removed in CHG-20260901-01.", True, "and inside it"),
]


@pytest.mark.parametrize("sentence,accepted,why", GHOST_EXCUSES,
                         ids=[c[2] for c in GHOST_EXCUSES])
def test_the_remedy_the_ghost_refusal_offers_actually_works(tmp_path, sentence, accepted, why):
    """A refusal that names a remedy has to accept a record that follows it.

    The second of the three refusals CHG-20260831-03 was about. Its acceptance claimed "the tests
    added for all three read the message"; no test was added for this one at all.
    """
    repo = _repo(tmp_path, SUPERSEDED_CHANGE)
    # `check_named_tests_exist` returns [] outright when the repo has no `tests/` — deliberately,
    # so it cannot fire on a tree it cannot read. Without this the whole table passed on an empty
    # list and the negative rows asserted nothing, which is the defect one file over.
    (repo / "tests").mkdir()
    (repo / "tests" / "test_alive.py").write_text(
        "def test_this_repos_own_ledger_passes():" + NEWLINE + "    pass" + NEWLINE,
        encoding="utf-8")
    acc = repo / "docs" / "acceptance" / "ACC-20260901-01.md"
    acc.write_text("# ACC" + NEWLINE + "- Conclusion: **Pass.**" + NEWLINE + NEWLINE + sentence,
                   encoding="utf-8")

    problems = [p for p in ledger_check.check_named_tests_exist(repo) if "test_gone" in p]

    if accepted:
        assert not problems, f"{why}: the remedy was followed and the record was still refused"
    else:
        assert problems, f"{why}: this excuses nothing and must not be accepted"
        assert "removed and why" in problems[0], "and the refusal has to say what to do"


#: Every spelling of "this acceptance's finding was never true". Each must reopen its change.
NEVER_TRUE_HEADS = ["**Void.** the fix never worked", "**Voided.** the fix never worked",
                    "**VOID.** the fix never worked", "已void"]


@pytest.mark.parametrize("conclusion", NEVER_TRUE_HEADS)
def test_every_never_true_spelling_reopens_its_change(tmp_path, conclusion):
    """The tuples were held by a containment check in one direction and a claim in the other.

    `tools/ledger_check.py`'s comment said the two "must stay **equal** on their never-true words,
    in both directions — pinned by" the refusal-wording test. It is not: dropping `"voided"` from
    `ACC_NEVER_TRUE` while it stays in `ACC_NOT_PASS` left the whole file green, and a DONE change
    whose acceptance concluded `**Voided.**` then stayed closed with no problem reported at all
    (CHG-20260831-05, defect seat).

    Whether a word *means* "never true" is a question about English and cannot be compared between
    tuples — the `rstrip("d")` attempt that stood here for one round compared nothing. What can be
    checked is the behaviour, one spelling at a time, which is what this does.
    """
    repo = _repo(tmp_path, DONE_CHANGE,
                 acc="# ACC" + NEWLINE + "- Conclusion: " + conclusion + NEWLINE)
    problems = ledger_check.check(repo)

    assert any("never true" in p for p in problems), (
        f"{conclusion!r} did not reopen its change: {problems}")
