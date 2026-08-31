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


HEADER = "- Project: x\n- Branch: b\n- Date: 2026-09-01\n- Risk: low\n"

#: A change claiming to be closed, and an acceptance saying the check that closed it never held.
DONE_CHANGE = f"# CHG\n{HEADER}\n## Status\n\n**Accepted**\n"
VOID_ACCEPTANCE = "# ACC\n- Conclusion: **VOID.** the fix never worked\n"


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
    assert "Reopen the change" in problems[0], "a refusal has to say what to do next"


def test_a_change_superseded_by_a_later_one_is_not_reopened_by_its_acceptance(tmp_path):
    """`superseded` is history, not a contradiction, so it must not trip the rule above."""
    repo = _repo(tmp_path, DONE_CHANGE,
                 acc="# ACC\n- Conclusion: **Superseded** by a later change\n")

    assert ledger_check.check(repo) == []


def test_a_change_that_says_why_a_void_acceptance_does_not_close_it_passes(tmp_path):
    """The escape hatch. A status that is not `done` is not claiming to be closed on anything."""
    repo = _repo(tmp_path,
                 f"# CHG\n{HEADER}\n## Status\n\n**Superseded** — the fix was redone\n",
                 acc=VOID_ACCEPTANCE)

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


@pytest.mark.parametrize("status", ["accepted", "completed", "merged", "完成", "done", "shipped",
                                    "closed", "已驗收", "released"])
def test_every_way_of_saying_finished_needs_an_acceptance(tmp_path, status):
    """The finding this closes: the lint knew only the word "built", so a change whose status said
    "accepted" or "完成" passed with no ACC at all — a false green written in one word."""
    repo = _repo(tmp_path, HEADER + f"\n## Status\n\n{status}\n")
    problems = ledger_check.check(repo)
    assert any("nothing saying it was checked" in p for p in problems), status


@pytest.mark.parametrize("status", ["draft", "in progress", "blocked", "草稿", "進行中",
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


def test_a_verdict_that_reads_both_ways_is_refused(tmp_path):
    repo = _repo(tmp_path, HEADER + "\n## Status\n\n**Under review.**\n",
                 acc="- Target CHG: CHG-20260901-01\n- Conclusion: **Pass / withdrawn.**\n")
    assert any("reads as both" in p for p in ledger_check.check(repo))


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
