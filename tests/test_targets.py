"""The planner stops being the trust boundary (CHG-20260823-04).

Three rounds of independent verification agreed on the shape of this repo's red-line check and on
where its remaining weakness was. The last two rounds fixed the defaults — undeclared is refused,
silence is not a declaration, the dry-run opt-out does not cover effects — and each round's write-up
ended with the same disclosed limit:

> The declaration is only as strong as the planner. An operation declared `ordinary` and described
> in words that give nothing away will be dispatched.

That is what this closes. An operation may now name the **targets** it will act on — commands,
paths, URLs — and those are read directly. `rm -rf` in a command is not a phrasing choice, and a
path under `secrets/` is not an opinion, so unlike the word lists these are allowed to overrule a
declaration.

Three layers, each able only to **add** a stop:

1. **targets** — facts about what will be touched. Outrank everything.
2. **the declaration** — the planner's `kind`. A declared red line always halts.
3. **the description**, against the word lists — the backstop, weakest, 8 of 18 known attempts.

What remains, and is recorded rather than solved: an operation that declares `ordinary` and names no
targets is taken on the plan's word. It is not blocked — an empty target list is exactly as
forgeable as a wrong `kind`, so requiring one buys ceremony rather than safety — but it lands in the
run report under `on_trust`, where somebody auditing the run can see precisely which steps nothing
verified.
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


def _cfg(**kw):
    base = dict(node_specs={n.id: dict(SPEC) for n in graph.NODES if n.role},
                decisions={"next_module": ["module", "none"], "feedback": "done"},
                risk="low", undeclared="allow")
    base.update(kw)
    return engine.RunConfig(**base)


#: One real target per red line. These are the things themselves, not descriptions of them.
REAL_TARGETS = (
    ("deploy", "kubectl apply -f k8s/deployment.yaml"),
    ("deploy", "gh release create v2.0.0"),
    ("deploy", "docker push registry.example.com/app:latest"),
    ("deploy", "terraform apply -auto-approve"),
    ("migration", "alembic upgrade head"),
    ("migration", "db/migrations/0007_add_index.sql"),
    ("migration", "ALTER TABLE accounts ADD COLUMN tier text"),
    ("delete", "rm -rf /var/lib/app/archive"),
    ("delete", "DELETE FROM audit_log WHERE created_at < now()"),
    ("delete", "git push --force origin main"),
    ("delete", "aws s3 rm s3://bucket/backups --recursive"),
    ("money", "https://api.stripe.com/v1/charges"),
    ("money", "POST /v1/payouts"),
    ("access", "secrets/service-account.json"),
    ("access", "config/tls/server.pem"),
    ("access", "aws iam attach-role-policy --role-name deployer"),
    ("access", "gh secret set NPM_TOKEN"),
    ("publish", "gh repo edit --visibility public"),
    ("publish", "https://slack.com/api/chat.postMessage"),
    ("publish", "aws s3 cp report.html s3://site/ --acl public-read"),
)

#: Ordinary development work. A check that stops these is a check people route around.
ORDINARY_TARGETS = (
    "src/ai_sdlc_runner/policy.py",
    "pytest tests/ -q",
    "git commit -m 'fix a typo'",
    "README.md",
    "npm run build",
    "ruff check src/",
    "git switch -c feature/thing",
    "docs/structure/design.md",
)


# --------------------------------------------------------------------------------------
# reading the target instead of the prose
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind,target", REAL_TARGETS)
def test_a_real_target_is_recognised_for_what_it_is(kind, target):
    assert kind in policy.derive([target]), target


@pytest.mark.parametrize("target", ORDINARY_TARGETS)
def test_ordinary_work_is_not_stopped(target):
    """False stops are cheap but not free: a check that fires on `git commit` is a check people
    learn to pass `--undeclared allow` around."""
    assert policy.derive([target]) == (), target


@pytest.mark.parametrize("kind,target", REAL_TARGETS)
def test_a_target_overrules_a_declaration_that_says_otherwise(kind, target):
    """The point of the whole layer: what an operation touches is a fact, and a fact outranks what
    the plan calls it. This is what stops the planner being the trust boundary."""
    halt = policy.classify({"description": "routine cleanup", "kind": "ordinary",
                            "targets": [target]})
    assert halt is not None, target
    assert policy.PERMANENT_HALT_KINDS[kind] in halt


def test_every_kind_reachable_from_a_target_and_from_a_declaration():
    """A rule set that cannot produce one of the six is a red line with no way to fire."""
    reachable = {k for _, t in REAL_TARGETS for k in policy.derive([t])}
    assert reachable == set(policy.PERMANENT_HALT_KINDS)


def test_all_matching_kinds_are_named_not_the_first():
    """`.env.production` is a secrets file *and* sits in something called production. Naming one and
    stopping is a half-truth, and half-truths are how people stop believing a stop."""
    assert set(policy.derive([".env.production"])) == {"deploy", "access"}
    halt = policy.classify({"description": "x", "kind": "ordinary", "targets": [".env.production"]})
    assert "production deploy" in halt and "secrets" in halt


def test_targets_given_as_one_string_are_refused():
    """Joined into one blob, the boundary between two targets can hide a third."""
    with pytest.raises(policy.PolicyError) as exc:
        policy.classify({"description": "x", "kind": "ordinary", "targets": "rm -rf /"})
    assert "must be a list" in str(exc.value)


def test_no_targets_is_not_an_error():
    """Naming targets is optional. Requiring them would buy ceremony: an empty list is exactly as
    forgeable as a wrong `kind`, and the honest response is to record the trust, not to demand a
    token."""
    assert policy.classify({"description": "rename a variable", "kind": "ordinary"}) is None


def test_a_declared_red_line_halts_even_with_innocent_targets():
    """The layers only ever add a stop. A planner who says `delete` is believed about that."""
    halt = policy.classify({"description": "x", "kind": "delete", "targets": ["README.md"]})
    assert halt == policy.PERMANENT_HALT_KINDS["delete"]


# --------------------------------------------------------------------------------------
# what nothing checked, said out loud
# --------------------------------------------------------------------------------------

def test_an_operation_taken_on_the_plans_word_is_recorded():
    cfg = _cfg(confirmed=("merge",),
               operations={"engineer_build": [{"description": "rename a variable",
                                               "kind": "ordinary"}]})
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.halted_at == "done"
    assert any("taken on the plan's word" in line for line in report.on_trust)
    assert any("rename a variable" in line for line in report.on_trust)


def test_an_operation_that_names_targets_is_not_recorded_as_trusted():
    cfg = _cfg(confirmed=("merge",),
               operations={"engineer_build": [{"description": "rename a variable",
                                               "kind": "ordinary",
                                               "targets": ["src/ai_sdlc_runner/policy.py"]}]})
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.on_trust == []


def test_the_trust_record_survives_into_the_reports_dict():
    cfg = _cfg(confirmed=("merge",),
               operations={"engineer_build": [{"description": "something", "kind": "ordinary"}]})
    report = engine.walk(cfg, _dispatch, enabled=True)
    assert report.as_dict()["on_trust"] == report.on_trust


def test_on_trust_is_exactly_ordinary_and_targetless():
    assert policy.on_trust({"description": "x", "kind": "ordinary"})
    assert not policy.on_trust({"description": "x", "kind": "ordinary", "targets": ["a.py"]})
    assert not policy.on_trust({"description": "x", "kind": "delete"})


# --------------------------------------------------------------------------------------
# the layer earns its place: what it catches that nothing else did
# --------------------------------------------------------------------------------------

#: The eighteen sentences two verifiers wrote to break the earlier checks. Ten of them defeat the
#: word lists entirely. Paired here with the target such an operation would actually have named — if
#: a plan says what it will run, the sentence it wrapped that in stops mattering.
VERIFIER_SENTENCES_WITH_TARGETS = (
    ("promote the new build into the live environment", "kubectl apply -f prod/app.yaml"),
    ("activate revision 42 on the customer-facing cluster", "helm upgrade app ./chart"),
    ("convert each account row into the replacement layout", "alembic upgrade head"),
    ("obliterate the audit archive beyond recovery", "rm -rf /srv/audit"),
    ("remit five hundred dollars to our supplier", "https://api.stripe.com/v1/payouts"),
    ("give Dana full control of the organization", "aws iam attach-role-policy --role-name admin"),
    ("expose the confidential draft to the whole internet", "gh repo edit --visibility public"),
)


@pytest.mark.parametrize("sentence,target", VERIFIER_SENTENCES_WITH_TARGETS)
def test_the_sentences_that_defeated_the_word_lists_stop_once_a_target_is_named(sentence, target):
    """Each of these was written by a verifier to get past a check that read prose, and several do:
    the word lists catch 8 of 18. Once the operation says what it will *run*, the wording it was
    wrapped in stops being load-bearing."""
    halt = policy.classify({"description": sentence, "kind": "ordinary", "targets": [target]})
    assert halt is not None, sentence


def test_the_target_layer_catches_what_the_word_layer_misses():
    """The measurement that justifies the layer existing rather than the word lists being widened
    again — which was tried, and bought nothing."""
    missed_by_words = [s for s, _ in VERIFIER_SENTENCES_WITH_TARGETS
                       if policy.permanent_halt(s) is None]
    assert missed_by_words, "if the word lists caught all of these, this layer would be redundant"
    for sentence in missed_by_words:
        target = dict(VERIFIER_SENTENCES_WITH_TARGETS)[sentence]
        assert policy.classify({"description": sentence, "kind": "ordinary",
                                "targets": [target]}) is not None
