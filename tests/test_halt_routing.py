"""Who a permanent halt reaches (CHG-20260827-19).

`PERMANENT_HALT_KINDS` names six things nothing automates: production deploy, data migration, hard
delete, moving money, changing access, publishing publicly. Past the size where one person owns all
six, those are six different people's decisions — and until this change every one of them stopped in
front of whoever happened to start the run.

## The property that matters, and the one this file exists to defend

**Routing narrows who is told first. It never narrows who is told.**

A routing table is a new way for a halt to go missing, which is the whole risk in adding one. So
every path here is checked for the fallback: an unmapped kind, a kind this runner has never heard
of, an empty table, a blank recipient. None of them may lose the operator, and none of them may
raise — a routing lookup that can refuse is one that can swallow a halt.

## The asymmetry in what is validated

A wrong **kind** is refused when it is typed. A wrong **recipient** is never refused.

That is not an inconsistency. `{"deploys": "release"}` would sit in the store looking configured and
route nothing for ever, with the operator believing the `deploy` halt goes to release. A recipient
this runner does not recognise still reaches somebody, because the operator is on every halt — and
organisations name their own functions, so a table accepting only the five shipped here would be
unusable by the organisations it exists for.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_sdlc_runner import engine, graph, policy, store  # noqa: E402


def _db(tmp_path):
    return store.connect(tmp_path / "config.sqlite")


# ── the fallback, from every direction ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("routing", [None, {}, {"money": ""}, {"money": "   "}])
def test_an_unrouted_halt_still_reaches_the_operator(routing):
    """The one sentence this change must not break. Four ways of saying "nothing configured", and
    none of them may lose the person who is always answerable."""
    assert policy.DEFAULT_RECIPIENT in policy.recipients("money", routing)


def test_a_kind_this_runner_has_never_heard_of_reaches_the_operator():
    """Not an error. A routing lookup that raises is a routing lookup that can swallow a halt, and
    the halt is the thing that matters."""
    who, source = policy.routed_to("something-invented-later")
    assert (who, source) == (policy.DEFAULT_RECIPIENT, "default")
    assert policy.recipients("something-invented-later") == (policy.DEFAULT_RECIPIENT,)


def test_every_shipped_kind_routes_somewhere_and_still_reaches_the_operator():
    for kind in policy.PERMANENT_HALT_KINDS:
        told = policy.recipients(kind)
        assert policy.DEFAULT_RECIPIENT in told, kind
        assert told[0] != policy.DEFAULT_RECIPIENT, (
            f"{kind} has no owner; every red line this runner ships an opinion about should name "
            f"the function whose decision it is")


def test_a_project_table_wins_and_says_so():
    assert policy.routed_to("deploy") == ("release", "policy")
    assert policy.routed_to("deploy", {"deploy": "sre-oncall"}) == ("sre-oncall", "project")
    assert policy.recipients("deploy", {"deploy": "sre-oncall"}) == ("sre-oncall", "operator")


# ── what is validated, and what deliberately is not ─────────────────────────────────────────────

@pytest.mark.parametrize("typo", ["deploys", "deploy ", "DEPLOY", "delete-data"])
def test_a_kind_with_a_typo_is_refused_when_it_is_typed(typo, tmp_path):
    """Configuration time, loudly. The alternative is a row that looks configured and routes
    nothing, for ever, with nobody able to see why the halt never reached them."""
    with pytest.raises(policy.PolicyError) as exc:
        store.set_halt_recipient(_db(tmp_path), typo, "somebody")
    assert typo in str(exc.value)


def test_a_recipient_nobody_recognises_is_accepted(tmp_path):
    """The other half of the asymmetry. `sre-oncall` is not in `RECIPIENTS` and must still work:
    an organisation's roster is a fact about that organisation, not about this flow."""
    db = _db(tmp_path)
    store.set_halt_recipient(db, "deploy", "sre-oncall")
    assert store.halt_routing(db) == {"deploy": "sre-oncall"}
    assert policy.recipient_label("sre-oncall") == "sre-oncall"
    assert policy.recipient_label("release") == policy.BY_RECIPIENT["release"].label


def test_clearing_a_route_returns_the_kind_to_the_policy_table(tmp_path):
    db = _db(tmp_path)
    store.set_halt_recipient(db, "deploy", "sre-oncall")
    store.set_halt_recipient(db, "deploy", None)
    assert store.halt_routing(db) == {}
    assert policy.routed_to("deploy", store.halt_routing(db)) == ("release", "policy")


def test_the_store_survives_a_reopen(tmp_path):
    """Schema 3 migrates once and the routing is still there."""
    path = tmp_path / "config.sqlite"
    store.set_halt_recipient(store.connect(path), "access", "dba")
    again = store.connect(path)
    assert again.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
    assert store.halt_routing(again) == {"access": "dba"}


# ── a recipient is not a role, and the difference is enforced ────────────────────────────────────

def test_a_recipient_is_not_a_role():
    """The first draft of this change put release / data / finance / security / comms into `ROLES`
    and `test_policy.py` refused it: every role must be one some node names. Nothing dispatches work
    to these functions, and `Role`'s three capability flags describe what a **work order** may do —
    answering all three `False` five times is a shrug shaped like a description.

    A recipient is told; a role is dispatched.
    """
    assert set(policy.BY_RECIPIENT) & set(policy.BY_ROLE) == set()
    assert set(graph.roles_used()) == set(policy.BY_ROLE)
    assert policy.DEFAULT_RECIPIENT not in policy.BY_RECIPIENT, (
        "the operator is the person running this, not a function in the organisation — keeping it "
        "out of the roster means editing the roster can never delete the fallback")


# ── end to end: the halt says who it is for ─────────────────────────────────────────────────────

def _halt_for(operation, routing=None):
    node = graph.BY_ID["engineer_build"]
    cfg = engine.RunConfig(node_specs={}, decisions={}, operations={node.id: [operation]},
                           halt_routing=routing or {})
    report = engine.RunReport()
    return engine._permanent_halt(node, cfg, report), report


def test_a_halt_names_the_function_whose_decision_it_is():
    reason, report = _halt_for({"description": "deploy to production", "kind": "deploy"})
    assert reason is not None
    assert "release" in reason and "operator" in reason
    assert report.halts and report.halts[0]["told"] == ["release", "operator"]
    assert report.halts[0]["kinds"] == ["deploy"]


def test_a_project_route_reaches_the_project_s_own_function():
    reason, report = _halt_for({"description": "deploy to production", "kind": "deploy"},
                               routing={"deploy": "sre-oncall"})
    assert "sre-oncall" in reason
    assert report.halts[0]["told"] == ["sre-oncall", "operator"]


def test_an_operation_crossing_two_kinds_reaches_both_owners():
    """`secrets/prod.env` is a credentials file *and* sits in something called production. Naming
    one owner and stopping would name the operation wrongly while still stopping it — the kind of
    half-truth that erodes trust in a stop."""
    reason, report = _halt_for(
        {"description": "rotate the key", "kind": "ordinary", "targets": ["secrets/prod.env"]})
    told = report.halts[0]["told"]
    # Exact, not membership. A mutation that reversed the owners left every assertion here green:
    # `"release" in told and "security" in told and told[-1] == "operator"` is true of
    # `['security', 'release', 'operator']` as well, and the list is documented as owners in the
    # order their kinds were crossed. `crossed` returns ('deploy', 'access') for this target, so
    # the order is not arbitrary and the test should say which one it is.
    assert report.halts[0]["kinds"] == ["deploy", "access"]
    assert told == ["release", "security", "operator"], told
    assert reason is not None


def test_the_halt_record_survives_for_an_audit():
    """Recorded, not only printed. "Who was told" is a question asked months later, and a line on
    somebody's terminal is not a record."""
    _, report = _halt_for({"description": "wire money", "kind": "money"})
    entry = report.halts[0]
    assert set(entry) == {"node_id", "kinds", "told", "description"}
    assert entry["node_id"] == "engineer_build"
    assert entry["description"] == "wire money"


# ── end to end, through the real CLI ─────────────────────────────────────────────────────────────

AGENT = """
import json, sys
order = json.load(sys.stdin)
node, seat = order["node_id"], order.get("seat")


def say(obj):
    print(json.dumps(obj))
    raise SystemExit(0)


if seat:
    if node == "intake_review":
        say({"missing": [], "problems": [], "unsafe": []})
    say({"verdict": "pass", "why": "nothing found"})
if node == "pm_plan":
    say({"modules": ["alpha"]})
if node == "engineer_build":
    say({"module": "alpha"})
branch = {"pm_confirm": "yes", "pm_signoff": "yes", "lead_task_review": "pass",
          "re_review": "pass", "qa_accept": "pass"}.get(node)
say({"verdict": branch} if branch else {"summary": (node or "?") + " done"})
"""


def test_a_routed_halt_reaches_the_projects_own_function_through_the_cli(tmp_path):
    """The seam nothing else covers: `store.halt_routing(db)` reaching `cfg.halt_routing`.

    Every other end-to-end check in this file calls `_permanent_halt` with a `RunConfig` built by
    hand, which is one layer below the wiring. A later edit could drop the store read entirely and
    all of them would stay green.

    So: configure `deploy -> sre-oncall` in a real store, give a node a real `deploy` operation, run
    the real CLI, and require the halt to name that project's own function.
    """
    import json
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    project = tmp_path
    (project / "agent.py").write_text(AGENT, encoding="utf-8")
    (project / "runner.yaml").write_text(
        'agent_command: ["python3", "agent.py"]\nagent_timeout: 60\n', encoding="utf-8")

    plan = json.loads((root / "examples/minimal/plan.json").read_text(encoding="utf-8"))
    plan["operations"] = dict(plan.get("operations") or {})
    plan["operations"]["engineer_build"] = [
        {"description": "ship it to production", "kind": "deploy", "targets": []}]
    (project / "plan.json").write_text(json.dumps(plan), encoding="utf-8")

    config = project / "config.sqlite"
    store.set_halt_recipient(store.connect(config), "deploy", "sre-oncall")

    proc = subprocess.run(
        [sys.executable, "-m", "ai_sdlc_runner.cli",
         "--config", str(project / "runner.yaml"),
         "run", "--plan", str(project / "plan.json"),
         "--risk", "low", "--confirm", "merge",
         "--assignment-store", str(config),
         "--ask-journal", str(project / "asks")],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONPATH": str(root / "src"), "PYTHONUTF8": "1"}, timeout=900)
    out = (proc.stdout or "") + (proc.stderr or "")

    assert "permanent halt" in out, f"the deploy operation did not stop the run:\n{out[-900:]}"

    # Read the `for:` line, not the whole output. The first draft asserted `"release" not in out`
    # and failed on a run that was entirely correct: `PERMANENT_HALT_KINDS["deploy"]` reads
    # "production deploy or release", so the word is in the KIND's description and says nothing
    # about who was told. A substring check against a word that means two things — which is the
    # defect class this repository names most often, in a test written for this change.
    told_lines = [ln for ln in out.splitlines() if ln.strip().startswith("for:")]
    assert told_lines, f"the run did not say who the halt was for:\n{out[-900:]}"
    told = told_lines[0]

    assert "sre-oncall" in told, (
        f"the store routes `deploy` to sre-oncall and the run did not say so, which means "
        f"`store.halt_routing` may not be reaching `cfg.halt_routing`: {told!r}")
    assert "operator" in told, f"the operator must be told whatever else is configured: {told!r}"
    assert policy.BY_RECIPIENT["release"].label not in told, (
        f"the project's own routing was ignored in favour of the policy default: {told!r}")
