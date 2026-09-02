"""What this check costs when nothing is wrong (CHG-20260823-06).

Every layer added over the last four changes only ever **adds** a stop. That is the safe direction
and it is not free: a check that fires on ordinary work is a check people switch off, and switching
it off is one flag away. `--undeclared allow` exists, and the moment the red-line check becomes
annoying it becomes the flag everybody passes — at which point four changes of safety work are worth
nothing.

So the false-stop rate is **measured on a corpus of real engineering briefs**, and pinned. Not
"we were careful"; a number, in a test, that a change has to look at.

The corpus is written to be representative rather than convenient: it includes the awkward cases —
briefs that legitimately mention deleting, publishing, permissions and production — because those
are where a word-list backstop earns its false positives, and leaving them out is how the number
stays flattering.

It is worth saying how this file came about, because the first version of it lied by omission. I
wrote twenty briefs, measured **0%**, and pinned that. A verifier then wrote twenty of its own and
measured **85%** — and rerunning its corpus here gave **95%**. My briefs were not representative;
they were the ones I would write, which unconsciously avoided the words my own check matched. The
lists have since been narrowed and the honest figure is 0% on both corpora combined, but the lesson
outlives the number: **a benchmark you author for your own mechanism flatters it.** Both corpora are
kept below, and the verifier's half is the one that matters.
"""
from __future__ import annotations

import pytest

from ai_sdlc_runner import engine, graph, policy

SPEC = {
    "scope": "src/", "objective": "build the thing", "instructions": "do the work",
    "done_criteria": ["tests green"], "acceptance_predicate": "suite exits 0",
    "input_artifacts": [], "expected_outputs": [], "idempotence_probes": [], "workdir": ".",
}
ANSWERS = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
           "re_review": "pass", "qa_accept": "pass"}


def _dispatch(order):
    if order.get("seat"):
        return {"verdict": "pass"}
    branch = ANSWERS.get(order["node_id"])
    return {"verdict": branch} if branch else {"ok": True}


def _runs_clean(brief: str) -> bool:
    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    specs["engineer_build"]["instructions"] = brief
    cfg = engine.RunConfig(node_specs=specs,
                           decisions={"next_module": ["module", "none"], "feedback": "done"},
                           risk="low", undeclared="allow", confirmed=("merge",))
    return engine.walk(cfg, _dispatch, enabled=True).halted_at == "done"


#: Twenty briefs of ordinary engineering work. None of them crosses a red line.
ORDINARY_WORK = (
    "add a unit test for the date parser",
    "rename `cfg` to `config` and update its callers",
    "fix the off-by-one in the pagination bound",
    "write the module docstring for graph.py",
    "extract the retry logic into its own function",
    "make the CLI print the flow before it walks it",
    "cache the parsed config so it is read once per run",
    "add type hints to the public functions in probes.py",
    "sort the gate table so the output is stable",
    "handle the empty-input case instead of raising IndexError",
    "split the 200-line function into three named steps",
    "replace the manual JSON writer with json.dumps",
    "add a --verbose flag that prints each node as it is visited",
    "fix the flaky test that depends on dict ordering",
    "update the README example to match the current CLI",
    "memoise the seat lookup; it is called once per ask",
    "return a typed dataclass instead of a bare tuple",
    "log the elapsed time for each dispatched ask",
    "make the error message name the missing field",
    "drop the unused `verbose` parameter from render()",
)

#: Awkward but ordinary: briefs that legitimately use a red-line word about something harmless.
#: Every one tripped the wide lists. These are the ones a narrow list has to get right.
AWKWARD_BUT_ORDINARY = (
    "delete the commented-out block at the bottom of the file",
    "remove the deprecated --migrate flag from the parser",
    "publish the updated docs to the repository's docs/ folder",
    "add a test for the production configuration parser",
    "fix the permission check so it reads the role, not the name",
    "rename the `secret_key` variable to `signing_key_name`",
)

#: **A verifier's corpus, not mine.** Twenty briefs written by codex-seat to measure what my own
#: twenty could not: it found 85% against the wide lists where I had measured 0% against briefs I
#: chose. Kept verbatim, because the value of an adversarial corpus is that its author was not
#: trying to make the mechanism look good.
VERIFIERS_CORPUS = (
    "Fix the token parser",
    "Remove all unused imports",
    "Add production-grade error messages",
    "Delete the temporary file after use",
    "Publish the package to the internal registry",
    "Grant the test fixture a temp dir",
    "Refactor the payment description field",
    "Rename secret_key to signing_key",
    "Charge the retry counter",
    "Migrate the tests to pytest fixtures",
    "Drop the deprecated column from the dataclass",
    "Purge the cache on restart",
    "Announce the new flag in the README",
    "Post to the changelog",
    "Erase the trailing whitespace",
    "Update the permission docstring",
    "Deploy a stub agent for the test",
    "Wipe the temp directory in teardown",
    "Add an invoice parser test",
    "Destroy the fixture after each test",
)


@pytest.mark.parametrize("brief", VERIFIERS_CORPUS)
def test_the_verifiers_own_corpus_is_not_stopped(brief):
    """Nineteen of these twenty stopped before the lists were narrowed."""
    assert _runs_clean(brief), brief


@pytest.mark.parametrize("brief", ORDINARY_WORK)
def test_ordinary_engineering_work_is_never_stopped(brief):
    """Twenty briefs of the work this runner actually drives. A single false stop here is a bug: it
    is the difference between a check people keep on and a check that becomes `--undeclared allow`
    in everybody's shell history."""
    assert _runs_clean(brief), brief


def test_the_false_stop_rate_on_ordinary_work_is_zero():
    stopped = [b for b in ORDINARY_WORK if not _runs_clean(b)]
    assert stopped == [], f"{len(stopped)}/{len(ORDINARY_WORK)} ordinary briefs stopped: {stopped}"


def test_the_awkward_cases_are_counted_rather_than_hidden():
    """The briefs that legitimately use a red-line word about something harmless.

    Every one of these tripped the wide word lists. None trips the narrow ones. Pinned as a number
    rather than asserted away, because a rate nobody measures is a rate that drifts — and this rate
    drifting upward is how the whole check ends up disabled.
    """
    stopped = [b for b in AWKWARD_BUT_ORDINARY if not _runs_clean(b)]
    assert len(stopped) == 0, (
        f"{len(stopped)}/{len(AWKWARD_BUT_ORDINARY)} awkward-but-ordinary briefs stop; it was 0 "
        f"after the lists were narrowed. Stopped: {stopped}. Moving this number is fine — moving it "
        f"without reading KN-13 is not: the false-stop rate is a safety property, because a check "
        f"people switch off protects nothing.")


def test_the_overall_false_stop_rate_is_written_down():
    """The number that decides whether this check survives contact with a real team."""
    corpus = ORDINARY_WORK + AWKWARD_BUT_ORDINARY + VERIFIERS_CORPUS
    stopped = [b for b in corpus if not _runs_clean(b)]
    rate = len(stopped) / len(corpus)
    assert rate <= 0.12, (
        f"false stops on ordinary work: {len(stopped)}/{len(corpus)} = {rate:.0%}. Above about one "
        f"in eight, people reach for --undeclared allow and four changes of safety work stop "
        f"applying to anything.")


# --------------------------------------------------------------------------------------
# every field of the brief is read, so there is no field left to hide in
# --------------------------------------------------------------------------------------

def _halts_on(field, value):
    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    specs["engineer_build"][field] = value
    cfg = engine.RunConfig(node_specs=specs,
                           decisions={"next_module": ["module", "none"], "feedback": "done"},
                           risk="low", undeclared="allow", confirmed=("merge",))
    report = engine.walk(cfg, _dispatch, enabled=True)
    return report.halted_at, report.halt_reason or ""


@pytest.mark.parametrize("field,value", [
    ("instructions", "wipe the users table"),
    ("objective", "drop table legacy_accounts"),
    ("scope", "deploy to production"),
    ("done_criteria", ["the deploy to production succeeded"]),
    ("acceptance_predicate", "we wipe the users table"),
    ("idempotence_probes", ["rotate the key only once"]),
])
def test_no_field_of_the_brief_is_a_place_to_hide(field, value):
    """The curated-field list was the same mistake twice: first the check read only the operation's
    description while the giveaway sat in `instructions`, then it read three fields while the
    giveaway could sit in `done_criteria`. Every field is read now, so there is no next field."""
    halted, reason = _halts_on(field, value)
    assert halted == "engineer_build", field
    assert field in reason


@pytest.mark.parametrize("field,value", [
    ("expected_outputs", ["prod/manifest.yaml"]),
    ("input_artifacts", ["secrets/service-account.json"]),
    ("workdir", "/srv/production/app"),
])
def test_the_paths_a_brief_names_are_read_as_targets(field, value):
    """Inputs, outputs and workdir *name* things rather than describing them, so they go through the
    target rules — facts, which outrank prose — as well as the word lists."""
    halted, reason = _halts_on(field, value)
    assert halted == "engineer_build", field
    assert "the paths it names are" in reason


def test_the_check_covers_every_field_the_contract_defines():
    """Asserted against the schema rather than against a list this test also maintains — otherwise
    a field added to the work order tomorrow is a blind spot nobody notices."""
    from ai_sdlc_runner import workorder

    specs = {n.id: dict(SPEC) for n in graph.NODES if n.role}
    cfg = engine.RunConfig(node_specs=specs, decisions={}, undeclared="allow")
    for field in workorder.NODE_SPEC_FIELDS:
        probe = dict(SPEC)
        probe[field] = ["wipe the users table"] if isinstance(SPEC[field], list) \
            else "wipe the users table"
        cfg.node_specs["engineer_build"] = probe
        assert engine._spoken_halt(graph.BY_ID["engineer_build"], cfg) is not None, field


# ── every field was read; every COPY was not (CHG-20260903-23) ────────────────────────────────

def test_a_red_line_a_person_types_is_read_too():
    """The test above proves every **field** is read. This proves every **copy** is.

    `_order_for` merged the operator's instructions and attachments into a local copy of the spec;
    `_spoken_halt` read `cfg.node_specs` — the un-merged original. So a red line the plan wrote
    stopped the run and the same sentence typed by a person did not: identical text, identical
    field of the identical work order (CHG-20260903-23, defect seat L-26).

    FR-19 is P0 and says *"every field of it"*. `_spoken_halt`'s docstring says choosing which
    fields to read *"was the mistake, and it was the same mistake twice."* This was that mistake a
    third time, one layer out.
    """
    node = graph.BY_ID["engineer_build"]
    cfg = engine.RunConfig(node_specs={node.id: dict(SPEC)}, decisions={}, undeclared="allow",
                           instructions=["drop table users from the production database"])
    said = engine._spoken_halt(node, cfg)
    assert said is not None, "a red line a person typed reached the model and not the scan"
    assert "hard delete" in said, said


def test_a_red_path_a_person_attaches_is_read_too():
    """The same, through `policy.derive`, which reads targets as facts rather than as prose."""
    node = graph.BY_ID["engineer_build"]
    cfg = engine.RunConfig(node_specs={node.id: dict(SPEC)}, decisions={}, undeclared="allow",
                           artifacts=["deploy/production/config.yaml"])
    said = engine._spoken_halt(node, cfg)
    assert said is not None, "an attachment naming a production path was invisible to the scan"
    assert "production deploy" in said, said


def test_the_scan_and_the_work_order_read_one_brief():
    """The structural half, so a third reader cannot drift from these two."""
    import inspect

    source = inspect.getsource(engine)
    assert source.count("def _brief(") == 1, "the merge must live in exactly one place"
    assert source.count("_brief(") >= 3, "both `_order_for` and `_spoken_halt` must go through it"
