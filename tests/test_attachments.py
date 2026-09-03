"""Tasks 9, 17 and 19 — what the operator hands over, and why its *name* never becomes a path.

Task 9 puts attachments on every node's work order. Task 17 is the interaction that makes 9
dangerous, and task 19 is the validation. They are one file because separating them would let 9 ship
and 17 arrive later, which is the order in which the bug happens.

## The interaction, restated

`input_artifacts` is a field `_spoken_halt` **scans for red lines**. Put attachment paths there and a
file stored at `…/production/spec.pdf` raises an unrelaxable permanent halt, on every node of every
run. An independent seat found this before a line was written.

The tempting fix — exempt `input_artifacts` from the scan — is worse than the bug: a brief that
genuinely names a production target would stop halting. One direction of a safety check traded for
the other, which is this repository's oldest mistake in new clothes.

So the fix is neither direction: **stored names are content hashes**, and the operator's filename
stays in the manifest as data. `test_both_directions_of_the_scan_survive` is the one that matters
here, because it is the only test that would fail for *either* wrong answer.
"""
import ast
import hashlib
import pathlib
import shutil
import tempfile

import pytest

from ai_sdlc_runner import attachments, engine, graph, paths, policy


def _store(tmp_path):
    return attachments.Store(tmp_path / "attachments")


# --- task 17: the safety interaction ---------------------------------------------------------

def test_a_stored_path_is_a_hash_and_carries_nothing_the_operator_typed(tmp_path):
    store = _store(tmp_path)
    a = store.add("production/spec.pdf".replace("/", "_"), b"a spec")
    stored = store.path_for(a.id)
    assert stored.name == hashlib.sha256(b"a spec").hexdigest()[:attachments._NAME_CHARS]
    assert a.id == hashlib.sha256(b"a spec").hexdigest(), "the id stays the full digest"
    assert "production" not in str(stored)
    assert "spec" not in stored.name


@pytest.mark.parametrize("filename", [
    "production.md", "prod.md", "deploy-to-prod.md", "prod spec.pdf", "PRODUCTION.PDF",
])
def test_a_filename_that_would_have_tripped_the_scanner_does_not(tmp_path, filename):
    """The exact defect: an ordinary spec whose *name* looked like a deployment target."""
    store = _store(tmp_path)
    store.add(filename, b"content for " + filename.encode())
    for path in store.order_paths():
        assert not policy.derive([path]), f"{filename} still trips the scanner via {path}"


def test_both_directions_of_the_scan_survive(tmp_path):
    """The one test that fails for *either* wrong answer, which is why it is the important one.

    Exempting `input_artifacts` would fix the false positive and create a false negative. Leaving it
    scanned would keep the false positive. Only hashing the stored name does both jobs.
    """
    store = _store(tmp_path)
    store.add("production-plan.md", b"just a plan")

    # 1. the attachment must not halt anything
    assert not policy.derive(store.order_paths())

    # 2. and a brief that genuinely names a production target must still halt
    assert "deploy" in policy.derive(["kubectl apply -f prod/"])


def test_the_filename_is_kept_where_a_person_can_read_it(tmp_path):
    """Kept as data, not thrown away — somebody has to be able to tell which document this is."""
    store = _store(tmp_path)
    a = store.add("wireframes.png", b"\x89PNG fake")
    assert a.filename == "wireframes.png"
    assert store.all()[0].filename == "wireframes.png"


def test_a_directory_in_the_name_is_reduced_to_the_name(tmp_path):
    store = _store(tmp_path)
    a = store.add("docs/specs/api.md", b"x")
    assert a.filename == "api.md", "a path in the name is a path somebody could later join onto"


def test_an_id_that_is_not_a_stored_name_is_refused(tmp_path):
    store = _store(tmp_path)
    for bad in ("../../etc/passwd", "spec.pdf", "", "0" * 31):
        with pytest.raises(attachments.AttachmentError, match="not a stored attachment name"):
            store.path_for(bad)


# --- task 19: validation ------------------------------------------------------------------------

def test_the_same_bytes_twice_are_one_attachment(tmp_path):
    """Content-addressed, so "the same spec" means the same bytes rather than the same name."""
    store = _store(tmp_path)
    first = store.add("spec.md", b"the spec")
    second = store.add("spec-copy.md", b"the spec")
    assert first.id == second.id
    assert len(store.all()) == 1


def test_changed_content_is_a_different_attachment(tmp_path):
    """Which is also the answer to "what if an attachment changes mid-run": it cannot.

    A new version is a new id, and orders already sent still name what they were sent with.
    """
    store = _store(tmp_path)
    first = store.add("spec.md", b"version one")
    second = store.add("spec.md", b"version two")
    assert first.id != second.id
    assert len(store.all()) == 2


def test_an_empty_attachment_is_refused(tmp_path):
    with pytest.raises(attachments.AttachmentError, match="not a brief"):
        _store(tmp_path).add("spec.md", b"")


def test_something_too_large_is_refused(tmp_path):
    with pytest.raises(attachments.AttachmentError, match="limit is"):
        _store(tmp_path).add("huge.pdf", b"x" * (attachments.MAX_BYTES + 1))


@pytest.mark.parametrize("filename", ["run.exe", "script.sh", "thing", "notes.docx"])
def test_a_type_this_runner_cannot_describe_is_refused(tmp_path, filename):
    with pytest.raises(attachments.AttachmentError, match="does not accept"):
        _store(tmp_path).add(filename, b"content")


def test_a_missing_file_is_reported_rather_than_silently_dropped(tmp_path):
    """A brief that has quietly lost a document is worse than one that says so."""
    store = _store(tmp_path)
    a = store.add("spec.md", b"the spec")
    assert store.missing() == []
    (store.dir / attachments.stored_name(a.id)).unlink()
    assert store.missing() == [a.id]


def test_a_malformed_manifest_is_an_error(tmp_path):
    store = _store(tmp_path)
    store.manifest_path.write_text("{oops", encoding="utf-8")
    with pytest.raises(attachments.AttachmentError, match="not valid JSON"):
        store.all()


# --- task 9: they reach every node ---------------------------------------------------------------

def test_attachments_reach_every_node_not_just_the_first(tmp_path):
    """A reviewer working from a different brief than the engineer is not reviewing the change."""
    store = _store(tmp_path)
    store.add("spec.md", b"the spec")
    seen = {}

    def dispatch(order):
        seen[order["node_id"]] = list(order["input_artifacts"])
        if order.get("seat"):
            return {"verdict": "pass"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    from test_flow import DECISIONS, SPEC
    engine.walk(engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions=dict(DECISIONS), risk="low", undeclared="allow",
        artifacts=tuple(store.order_paths())), dispatch, enabled=True)

    assert len(seen) > 5, "the run should have asked several nodes"
    for node_id, artifacts in seen.items():
        assert any(attachments.stored_name(store.all()[0].id) in a for a in artifacts), \
            f"{node_id} was asked without the attachment"


def test_a_nodes_own_inputs_are_kept_alongside_the_attachments(tmp_path):
    """Appended, never replacing — dropping either makes one of the two invisible."""
    store = _store(tmp_path)
    store.add("spec.md", b"the spec")
    seen = []

    def dispatch(order):
        if order["node_id"] == "pm_plan":
            seen.extend(order["input_artifacts"])
        return {"ok": True}

    from test_flow import DECISIONS, SPEC
    spec = dict(SPEC)
    spec["input_artifacts"] = ["README.md"]
    try:
        engine.walk(engine.RunConfig(
            node_specs={n.id: dict(spec) for n in graph.NODES if n.role},
            decisions=dict(DECISIONS), risk="low", undeclared="allow",
            artifacts=tuple(store.order_paths())), dispatch, enabled=True)
    except engine.EngineError:
        pass                                   # the run stops later; pm_plan is what is under test
    assert "README.md" in seen
    assert any(attachments.stored_name(store.all()[0].id) in a for a in seen)


# --- the blueprint arriving in pieces ------------------------------------------------------------

def test_every_instruction_reaches_the_order_numbered(tmp_path):
    """The blueprint is rarely finished when a run starts.

    A second instruction is an event, not an edit of the first — and a work order that can say
    *when* something was asked for is most of what makes a late change reviewable.
    """
    seen = []

    def dispatch(order):
        if order["node_id"] == "pm_plan":
            got = order["instructions"]
            seen.append(got if isinstance(got, str) else " ".join(got))
        return {"ok": True}

    from test_flow import DECISIONS, SPEC
    try:
        engine.walk(engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions=dict(DECISIONS), risk="low", undeclared="allow",
            instructions=("build the thing", "also make it dark", "and add a keyboard shortcut")),
            dispatch, enabled=True)
    except engine.EngineError:
        pass

    joined = " ".join(seen)
    assert "instruction 1 of 3: build the thing" in joined
    assert "instruction 2 of 3: also make it dark" in joined
    assert "instruction 3 of 3: and add a keyboard shortcut" in joined


def test_the_attachment_records_which_instruction_it_arrived_with(tmp_path):
    """So a later brief can say where a document came from, rather than just that one exists."""
    store = _store(tmp_path)
    first = store.add("spec.md", b"the original spec", instruction=1)
    later = store.add("revised.md", b"the revision", instruction=3)
    assert first.instruction == 1
    assert later.instruction == 3


# --- the loop when the blueprint grows -----------------------------------------------------------

def _frontier_run(planned_per_call, built_calls):
    """Walk with `next_module` decided by the frontier, and a PM whose plan can grow."""
    from test_flow import SPEC

    calls = {"pm_plan": 0, "engineer_build": 0}

    def dispatch(order):
        node = order["node_id"]
        if node == "pm_plan":
            i = min(calls["pm_plan"], len(planned_per_call) - 1)
            calls["pm_plan"] += 1
            return {"modules": planned_per_call[i]}
        if node == "engineer_build":
            i = calls["engineer_build"]
            calls["engineer_build"] += 1
            return {"module": built_calls[i]} if i < len(built_calls) else {"summary": "none"}
        if order.get("seat"):
            return {"verdict": "pass"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(node)
        return {"verdict": branch} if branch else {"ok": True}

    return engine.walk(engine.RunConfig(
        node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
        decisions={"next_module": engine.FRONTIER, "feedback": "done"},
        # `merge` stops even at low risk -- it is the one-way door. Confirmed here so the test can
        # be about the loop rather than about the gate.
        risk="low", undeclared="allow", confirmed=("merge",)), dispatch, enabled=True), calls


def test_the_loop_ends_when_the_frontier_is_empty():
    report, calls = _frontier_run([["a", "b"]], ["a", "b"])
    assert report.state == engine.FINISHED
    assert calls["engineer_build"] == 2, "one build per planned module, and then it stops"


def test_a_blueprint_that_grows_between_walks_keeps_looping(tmp_path):
    """The defect a late instruction produced, and the reason `frontier` exists.

    Two things had to be true for a growing blueprint to work, and neither was:

    1. A fixed ``["module", "module", "none"]`` is a claim about how many modules there will be,
       written before the first is built. A second instruction arrives, the PM plans two more, and
       the sequence describes a plan that no longer exists — which stopped a live run with
       *"reached 5 time(s) but only 4 decision(s) were supplied"*.
    2. Worse, and quieter: the journal reused `pm_plan`'s answer by **ask id**, so the PM was never
       told about the new instruction at all. The blueprint could not grow because the node that
       grows it was never asked again.

    This drives both: one walk with one instruction, then a second walk with two, sharing a journal.
    """
    from test_flow import SPEC

    journal = engine.AskJournal(tmp_path / "asks")
    seen = {"pm_plan": 0, "engineer_build": []}

    def run(instructions, plan):
        # Per-walk, not across walks: an engineer builds the next unbuilt module *in this run*, and
        # a dispatcher that remembered the previous run would be answering for a walk that is not
        # happening.
        built_here = []

        def dispatch(order):
            node = order["node_id"]
            if node == "pm_plan":
                seen["pm_plan"] += 1
                return {"modules": plan}
            if node == "engineer_build":
                remaining = [m for m in plan if m not in built_here]
                if not remaining:
                    return {"summary": "nothing left"}
                built_here.append(remaining[0])
                seen["engineer_build"] = list(built_here)
                return {"module": remaining[0]}
            if order.get("seat"):
                return {"verdict": "pass"}
            branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                      "re_review": "pass", "qa_accept": "pass"}.get(node)
            return {"verdict": branch} if branch else {"ok": True}

        return engine.walk(engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={"next_module": engine.FRONTIER, "feedback": "done"},
            risk="low", undeclared="allow", confirmed=("merge",),
            instructions=instructions, resume=True, journal=journal), dispatch, enabled=True)

    first = run(("build a and b",), ["a", "b"])
    assert first.state == engine.FINISHED
    assert seen["engineer_build"] == ["a", "b"]
    assert seen["pm_plan"] == 1

    # A second instruction arrives. Every work order now carries a different brief.
    second = run(("build a and b", "also c and d"), ["a", "b", "c", "d"])
    assert second.state == engine.FINISHED
    assert seen["pm_plan"] == 2, (
        "the PM was not asked again — the journal reused an answer to a question that had changed, "
        "so the new instruction never reached the node that plans the work")
    assert seen["engineer_build"] == ["a", "b", "c", "d"], \
        "the modules added by the later instruction were never built"


def test_an_unchanged_brief_still_reuses_the_journal(tmp_path):
    """The other direction, so the fix does not quietly become "never resume".

    Re-asking everything on every resume is what the journal exists to prevent. Only a question that
    actually changed may be asked again.
    """
    from test_flow import SPEC

    journal = engine.AskJournal(tmp_path / "asks")
    asked = []

    def dispatch(order):
        asked.append(order["node_id"])
        if order.get("seat"):
            return {"verdict": "pass"}
        if order["node_id"] == "pm_plan":
            return {"modules": ["a"]}
        if order["node_id"] == "engineer_build":
            return {"module": "a"}
        branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
                  "re_review": "pass", "qa_accept": "pass"}.get(order["node_id"])
        return {"verdict": branch} if branch else {"ok": True}

    def run():
        return engine.walk(engine.RunConfig(
            node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
            decisions={"next_module": engine.FRONTIER, "feedback": "done"},
            risk="low", undeclared="allow", confirmed=("merge",),
            instructions=("build a",), resume=True, journal=journal), dispatch, enabled=True)

    run()
    first_pass = len(asked)
    assert first_pass
    run()
    assert len(asked) == first_pass, "the same brief re-asked everything; the journal did nothing"


def test_a_frontier_with_no_plan_is_refused_rather_than_assumed_empty():
    """An empty frontier and an unstated one are not the same thing."""
    with pytest.raises(engine.EngineError, match="no plan has named any modules"):
        _frontier_run([{}], [])


# ── every write went through the long-path layer and every read went around it ─────────────────
#
# `LongPathsEnabled = 0` is the Windows default. Measured on `main`, with a 252-character store
# directory: `add()` returned successfully, `all()` read `[]`, `order_paths()` returned 0 — which
# `server.py:503` feeds into `input_artifacts` for **every** work order — and `missing()`, the
# detector written for exactly this, agreed that nothing was wrong. At 235 characters the failure
# inverted and `missing()` reported every attachment gone while the directory listing showed all of
# them present (CHG-20260903-28, found by the defect seat).
#
# Thirty-nine fixtures in this file use `tmp_path`, which is about sixty characters. None of them
# could see it.


def _deep(target_len):
    """A directory whose path is `target_len` characters, nested the way a real checkout gets deep."""
    base = pathlib.Path(tempfile.gettempdir()) / "aslr_deep"
    d = base / ("x" * 30)
    while len(str(d)) < target_len - 31:
        d = d / ("y" * 30)
    pad = target_len - len(str(d)) - 1
    if pad > 0:
        d = d / ("z" * pad)
    return base, d


@pytest.mark.parametrize("length", [235, 252])
def test_a_store_on_a_long_path_holds_what_it_says_it_holds(length):
    """Both lengths, because the failure inverted between them and one alone would miss half."""
    base, directory = _deep(length)
    if len(str(base)) > 120:                       # a temp dir this deep cannot reach the case
        pytest.skip("temp directory is already too deep to construct the case")
    shutil.rmtree("\\\\?\\" + str(base), ignore_errors=True)
    try:
        store = attachments.Store(directory)
        store.add("spec.md", b"the spec")
        store.add("plan.md", b"the plan")

        # `add()` reported success for both. The store must agree.
        assert sorted(a.filename for a in store.all()) == ["plan.md", "spec.md"]
        # The one `server.py` puts on every work order.
        assert len(store.order_paths()) == 2
        # The detector, which was wrong in both directions.
        assert store.missing() == []
        # And the bytes come back, through the same reader that used to say "not in this store".
        assert pathlib.Path(paths.real(store.path_for(store.all()[0].id))).exists()
    finally:
        shutil.rmtree("\\\\?\\" + str(base), ignore_errors=True)


def test_every_filesystem_read_in_this_module_goes_through_the_long_path_layer():
    """The rule, not one instance of it — and the half a Linux runner can still check.

    The behavioural test above is only a real test on Windows; on a runner with no `MAX_PATH` it
    passes either way. This one fails everywhere the moment a bare `Path.exists()` or
    `.read_text()` comes back, which is how the five got there in the first place: every write in
    this module was wrapped and every read was not.
    """
    tree = ast.parse(pathlib.Path(attachments.__file__).read_text(encoding="utf-8"))
    bare = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"exists", "read_text", "read_bytes", "is_file", "iterdir"}
        and not (isinstance(node.func.value, ast.Name) and node.func.value.id == "paths")
    ]
    assert bare == [], f"filesystem reads not going through paths.*: {bare}"
