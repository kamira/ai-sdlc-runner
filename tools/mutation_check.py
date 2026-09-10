"""Break a guarantee on purpose and check that a test notices.

    python3 tools/mutation_check.py
    python3 tools/mutation_check.py --only importer
    python3 tools/mutation_check.py --only examples

Exit 0 if every mutation was caught, 1 otherwise.

## Why this exists

A test that stays green when the behaviour it names is broken is not a test, and this repository has
shipped three of them. The one that forced this file:

```python
def test_a_directory_named_like_a_conversation_does_not_stop_the_import(...):
    ...
    assert good.id in report["imported"] or report["refused"]
```

When the directory **did** stop the import, `imported` was empty and `refused` held one entry saying
the store could not be listed — so the `or` was satisfied and the test passed on the exact failure
its own name forbids. It shipped in CHG-20260823-45, it was marked done, and a review seat found it
rather than the suite.

Nothing in an ordinary green run distinguishes that test from a real one. Reverting the fix and
watching a test go red does.

## What this is not

**It is not coverage, and it is not mutation testing.** A real mutation tester generates variants
mechanically and finds the ones nobody thought about. Every entry here was written *after* a defect
was known, by the same person who fixed it. It proves the tests for the classes we have named can
fail; it proposes no new class.

That limitation is the honest reading of the table it produces, and it is worth stating twice
because a clean table invites the other reading.

**It is not a check on which scenarios got tested.** CHG-20260823-50's `frontier` group was 2/2
caught, its table read clean, and the defect shipped anyway — because the test pinning the claim
asserted over an ask history the shipped graph cannot produce. No mutation of the *code* can expose
a test whose *scenario* is unreachable. A review seat put it exactly: this answers "can the tests I
wrote fail?", never "did I write the test for the case that matters?"

**And a red is only meaningful against a green.** Until CHG-20260823-51 any non-zero exit counted as
caught, including a collection error or an unrelated pre-existing failure. Each file is now run
unmutated first.

## Adding a mutation

Add a `Mutation` with the smallest edit that makes the guarantee false — an inverted condition, a
dropped exception type, a normalisation skipped. Then check it fails for the *right* reason: the
first draft of the importer's first mutation rebound a dict to an equal dict, which changes nothing
and would have reported a false "not caught".
"""
from __future__ import annotations

import argparse
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src/ai_sdlc_runner"

#: The checkers themselves (CHG-20260828-02). A guard is code that can be wrong: `ledger_check`
#: walked changes and never acceptances, so an ACC naming no change read as a pass. Mutating the
#: guards is the only way to know they still refuse.
TOOLS = REPO / "tools"

#: The harness's own safety net lives next door, in `mutation_recovery.py`. Not tidiness: a
#: mutation's `before` string sits in THIS file, so any anchor into it appears twice and the
#: uniqueness guard correctly refuses it. A file cannot pin guarantees about itself by exact
#: text, and the recovery is the part that most needed pinning (CHG-20260828-18).
from mutation_recovery import (DEFAULT_IN_FLIGHT, IN_FLIGHT, MutationInFlight,  # noqa: E402
                               apply, recover, restore, restore_on_signal)


class Mutation(NamedTuple):
    group: str
    #: What becomes untrue. Phrased as the defect returning, because that is what is being tested.
    says: str
    path: Path
    before: str
    after: str
    #: The tests that must notice. A narrow file keeps a run to seconds.
    tests: str


MUTATIONS: List[Mutation] = [
    # ── attachment-route (CHG-20260906-05) ─────────────────────────────────────────────────
    # `POST /attachments` had a documented request body, a documented row and three documented
    # refusals, and nothing executable pinning any of them — because the fixture that speaks HTTP
    # had no attachment store, so the route answered "this runner has no attachment store" from
    # the only layer that could have tested it.
    Mutation(
        "attachment-route", "the route stops refusing a body that is not base64",
        SRC / "server.py",
        '''                        raise ServerError(f"the attachment body is not valid base64: {exc}")''',
        '''                        raw = b""''',
        "tests/test_server.py"),

    Mutation(
        "attachment-route", "the route reads a field the page does not send",
        SRC / "server.py",
        '''                        raw = base64.b64decode(str(body.get("data") or ""), validate=True)''',
        '''                        raw = base64.b64decode(str(body.get("data_base64") or ""), validate=True)''',
        "tests/test_server.py"),

    Mutation(
        "attachment-route", "the filename the operator sent is dropped on the way through",
        SRC / "server.py",
        '''                    out = runner.attach(version, str(body.get("filename") or ""), raw)''',
        '''                    out = runner.attach(version, "attachment", raw)''',
        "tests/test_server.py"),
    # ── refusal-routing (CHG-20260907-08) ─────────────────────────────────────────
    # `validate` accepted any `rejects_to` that existed and was not the node itself: all 24
    # retargets of the eight rejection edges to `merge`, `pr` or `done` passed. Four
    # structural rules were measured and none is sufficient -- two are vacuous because the
    # flow is one cycle, one refuses a shipped edge, and the best of them accepts
    # `qa_accept -> qa_verify`, which returns while skipping the `lead_review` gate. Which
    # gates a refusal must pass is policy; the weak rule and the explicit pin are separate
    # entries because reverting one must not look like reverting the other.
    Mutation(
        "refusal-routing", "a refusal may again land where the run can never return from",
        SRC / "graph.py",
        '''            if not _reaches(node.rejects_to, node.id):''',
        '''            if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "refusal-routing", "an acceptance refusal routes around the whole-change bound",
        SRC / "graph.py",
        '''         answer_decides=True, mode=MODEL_PANEL, rejects_to="acceptance_failed",''',
        '''         answer_decides=True, mode=MODEL_PANEL, rejects_to="next_module",''',
        "tests/test_graph_validation.py"),

    Mutation(
        "refusal-routing", "the bound goes back to a hand-written pair of node names",
        SRC / "engine.py",
        '''    return tuple(node.id for node in graph.NODES if node.next == "change_retry")''',
        '''    return ("review_failed", "acceptance_failed")''',
        "tests/test_graph_validation.py"),

    # ── two-views (CHG-20260907-10) ─────────────────────────────────
    # `validate` opened with a length check over two module attributes either of which a
    # caller may rebind, and `policy.py` says an in-memory-altered graph is a supported
    # surface. Rebinding one was enough to certify a graph that is not the one a run then
    # executes. The second entry is the same fault one module over: a derivation captured
    # at import, measured putting a node the graph places inside the module loop into the
    # shared tree.
    Mutation(
        "two-views", "the two views of the graph may disagree again",
        SRC / "graph.py",
        '''        if BY_ID.get(node.id) is not node:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "two-views", "which tree a node works in may be read from a snapshot again",
        SRC / "engine.py",
        '''    return worktree.key_for(cycle) if node.id in graph.module_cycle() else ""''',
        '''    return worktree.key_for(cycle) if node.id in frozenset(["engineer_build", "engineer_selfverify", "fix_pass", "lead_task_review", "re_review"]) else ""''',
        "tests/test_module_built.py"),

    # ── graph-swap (CHG-20260907-25) ───────────────────────────────
    # Three modules each carried their own "swap both views, validate, restore"; they are one
    # `tests/_graph_swap.validate_with` now, shared by 44 functions — 43 test functions and one
    # helper, and this line said 39 until
    # CHG-20260908-03 counted them. A shared helper is a
    # single point of failure for every guarantee that goes through it, which is what these two
    # entries are about.
    #
    # **Both name a test node, and the first has to.** Dropping the `BY_ID` rebind makes most of
    # the tests in those three files fail collaterally: `validate` raises its identity refusal and
    # their own `match=` string no longer matches the message. Exactly one pattern in those files
    # does match it — `"rebound separately"`, the deliberate half-swap's own. So a file-level
    # CAUGHT here would be reporting missing regexes, not the swap. The node registered is the one
    # whose stated guarantee IS that both views move.
    #
    # **The figures behind that are CHG-20260907-25's**: 43 of 74 tests failing, 41 of them
    # collaterally, over 34 distinct `match=` patterns. They stood here in the present tense until
    # CHG-20260908-03, when a seat measured them at 82 tests and 39 patterns. The conclusion is
    # re-measured and unchanged — one of the 39 matches the identity refusal — so the numbers are
    # left where they were taken rather than restated here, and the argument above no longer needs
    # them.
    #
    # The second entry is registered **because its test was written for it**. Measured first:
    # with the `finally` body removed and one mutating node run alone the result is `1 passed` —
    # nothing named noticed. Run wider it fails 49, every one a later test inheriting a polluted
    # graph, which is collection order rather than a guarantee (`pytest-randomly` is not
    # installed, so that order is stable, which makes the collateral reliable and no more
    # meaningful). Registering it against a file would have been a clean CAUGHT over a hole.
    #
    # **Absent on purpose:** nothing is registered for `_validate_one`'s arity. Its splice
    # `tuple(node if n.id == node.id else n for n in graph.NODES)` and `_mutate` build the same
    # tuple for the cases its two callers exercise, so no edit between the two shapes is
    # observable by any test, and inventing one to round the group up to three would be the
    # thing this file's own docstring warns against.
    Mutation(
        "graph-swap", "the shared swap may rebind one view of the graph and not the other",
        REPO / "tests" / "_graph_swap.py",
        '''    graph.BY_ID = {n.id: n for n in graph.NODES}''',
        '''    pass''',
        "tests/test_graph_validation.py::test_the_half_swap_used_to_certify_a_graph_that_does_not_run"),

    Mutation(
        "graph-swap", "the shared swap may stop putting the shipped graph back",
        REPO / "tests" / "_graph_swap.py",
        # One restore in the module, so one entry. CHG-20260908-03 briefly had two — it added a
        # context manager with an identical `finally`, `test_every_shipped_mutation_has_a_unique_
        # anchor` refused the bare restore line for naming both, and the fold that followed removed
        # the duplicate rather than the ambiguity. **Two** named tests cover this one line now:
        # `test_the_shared_swap_puts_both_views_back_when_validate_raises` reaches it through
        # `validate_with`, and `test_the_context_manager_puts_both_views_back_when_the_body_raises`
        # reaches it directly; this entry names the second, which fails alone.
        '''        yield graph.NODES
    finally:
        graph.NODES, graph.BY_ID = original_nodes, original_by_id''',
        '''        yield graph.NODES
    finally:
        pass''',
        "tests/test_graph_validation.py::test_the_context_manager_puts_both_views_back_when_the_body_raises"),

    # ── single-model (CHG-20260907-18) ─────────────────────────────
    # `graph.py` says a SINGLE node is 'exactly one model, one session' and that three
    # configured is 'a configuration error, not a panel'. Three surfaces accepted it and
    # the engine asked once and said nothing. The second entry is the other direction:
    # a length rule that starts refusing the panel and the pool, which take lists on
    # purpose.
    Mutation(
        "single-model", "a single node may be given a panel's worth of models again",
        SRC / "plan.py",
        '''                    and graph.BY_ID[owner].mode == graph.SINGLE and len(value) > 1):''',
        '''                    and graph.BY_ID[owner].mode == graph.SINGLE and False):''',
        "tests/test_plan.py"),

    Mutation(
        "single-model", "the rule may start biting a panel or a pool again",
        SRC / "plan.py",
        '''            if (key == "node_models" and owner in graph.BY_ID''',
        '''            if (key == "node_models" and owner in graph.BY_ID or True''',
        "tests/test_plan.py"),

    # ── shared-temp (CHG-20260907-23) ─────────────
    # `_deep` built under a name fixed for the whole machine and deleted it before building, so
    # two pytest processes in two worktrees deleted each other's tree. The entry restores that
    # name. Note the anchor is in `tests/`, not `src/`: the defect was in a test helper, and a
    # mutation that could only be spelled in `src/` could not reach it.
    Mutation(
        "shared-temp", "a test may build under a name the whole machine shares again",
        REPO / "tests" / "test_attachments.py",
        '''    base = pathlib.Path(tempfile.mkdtemp(prefix="aslr_"))''',
        '''    base = pathlib.Path(tempfile.gettempdir()) / "aslr_deep"''',
        "tests/test_attachments.py::test_no_test_module_builds_a_path_from_the_machine_s_temp_directory"),

    # ── backlog (CHG-20260907-22) ──────────────────
    # `socketserver` defaults the listen backlog to 5 and `serve` never set it, so the sixth
    # caller of a server whose acceptor is not draining is told `WinError 10061` -- the error
    # for nothing listening at all.
    #
    # One entry, not two. A second was registered that deleted the attribute so the default is
    # inherited by accident -- and both seats said the same thing about it: `pass` and `= 5`
    # produce the identical class attribute, so no test can tell them apart and anything catching
    # one catches the other. It read as a distinct class only to a human reading the source.
    # Deleted rather than relabelled.
    Mutation(
        "backlog", "the listen backlog may go back to five again",
        SRC / "server.py",
        '''        request_queue_size = 128''',
        '''        request_queue_size = 5''',
        "tests/test_server.py::test_a_burst_of_connections_is_queued_rather_than_refused"),

    # ── resolver-fixed (CHG-20260907-21) ────────────
    # The reverse test asserted a containment and `localhost` satisfied it by being a bind
    # spelling, which is not why it belongs. Equality stated the relation instead, so every term
    # was required rather than tolerated; CHG-20260907-24 then made the same relation true by
    # construction and moved `RESOLVER_FIXED` into `src/`, which is where these two now anchor.
    #
    # **One of the three is deleted with its guarantee** -- the bind list and the header set
    # losing `localhost` TOGETHER, an eleven-line span across both constants. That state cannot
    # be reached any more and not because it stopped mattering: `localhost` is in exactly one
    # constant now, and the header set follows it. Deleting the name is what entry 1 below does,
    # in one line, and it is the same state.
    #
    # Its history is worth keeping even though the entry is gone, because the reasoning was the
    # defect. It was first left out with a sentence saying no single anchor could reach it, the
    # harness taking one replacement and the constants being separate statements. That sentence
    # was never measured and was false -- `replace` has no length limit, 130 registered anchors
    # already contained newlines and the longest was 393 lines. A seat measured it.
    #
    # Every objector, measured with `-x` off, because `-x` reports whichever test is collected
    # first and that is not the same question. At CHG-20260907-21:
    #
    #     HOSTS loses localhost         5   equality, live Host x2, Origin, forward table
    #     both constants lose it        4   equality, live Host x2, Origin
    #     [127.0.0.1] added to HOSTS    1   equality alone
    #
    # and after CHG-20260907-24, re-measured on the anchors below:
    #
    #     RESOLVER_FIXED emptied        5   derivation, live Host x2, Origin, the literal pin
    #     [127.0.0.1] added to it       2   derivation, the literal pin
    #
    # The entries name the test whose guarantee each one is, so a CAUGHT means what the `says`
    # means rather than that something in the file went red.
    Mutation(
        "resolver-fixed", "the header set may lose a name a standard fixes again",
        SRC / "server.py",
        '''RESOLVER_FIXED = frozenset({"localhost"})''',
        '''RESOLVER_FIXED = frozenset()''',
        "tests/test_server.py::test_the_name_a_standard_fixes_is_accepted_as_a_live_host_header"),

    Mutation(
        "resolver-fixed", "an authority form nothing derives may be accepted again",
        SRC / "server.py",
        '''RESOLVER_FIXED = frozenset({"localhost"})''',
        '''RESOLVER_FIXED = frozenset({"localhost", "[127.0.0.1]"})''',
        "tests/test_server.py::test_the_names_a_standard_fixes_are_the_one_member_that_was_measured"),

    # ── derived-hosts (CHG-20260907-24) ──────────────────────────
    # `LOOPBACK_HOSTS` is now `_accepted_hosts(LOOPBACK)` and `localhost` has left the bind list,
    # which is one record because the second is what makes the first honest: with `localhost` in
    # both `LOOPBACK` and `RESOLVER_FIXED`, dropping the `| RESOLVER_FIXED` term changed the
    # resulting table by nothing at all -- measured -- so the standard's term would have crossed
    # into `src/` already unfalsifiable. Entry 3 is that measurement as a mutation, and it is
    # CAUGHT only because of the narrowing.
    #
    # **The obvious entry is deliberately absent: hardcoding `LOOPBACK_HOSTS` back to
    # `frozenset({"127.0.0.1", "localhost"})`.** Measured, the whole file passes -- 142, no
    # objector -- because the derivation and the literal are the same table today, which is the
    # point of a refactor and not a hole in it. What this record makes checkable is the *rule*,
    # on inputs the constant does not have, and those are entries 1, 2, 4 and 5. Registering an
    # entry that cannot fail would be a claim this file exists to refuse.
    #
    # Entries 4 and 5 are the two normalisations CHG-20260907-20 left dead-by-data, with a note
    # saying they are what an IPv6 build would need back. They were NOT CAUGHT by anything --
    # re-measured here, 139 passed with the new test deselected, for each -- and they are caught
    # now, because deriving the table for a hypothetical bind list is a question a test can ask
    # and a constant cannot.
    #
    # Entry 1 has **two** production call sites, and the second was found by review: `server.py`
    # was carrying a byte-identical copy of the rule inline in `_loopback_origin`
    # (`literal = f"[{host}]" if ":" in host else host`), ninety lines from the function that now
    # owns it, in the file whose whole subject is one boundary written twice. It reads
    # `_authority(host)` now, and that call site is the one where the bracket is actually
    # **reached** -- `test_an_ipv6_origin_is_refused_because_nothing_serves_one` sends
    # `http://[::1]:8080` on every run.
    #
    # **A second absent entry, for the same reason as the first:** putting that inline copy back
    # is behaviour-preserving too -- 142 passed, no objector, measured. De-duplicating an
    # expression is not a behaviour a test can hold, and neither is deriving a table that already
    # had the right members. Both are written here instead of registered.
    Mutation(
        "derived-hosts", "the derivation may store an IPv6 address in a form no client sends again",
        SRC / "server.py",
        '''    return f"[{addr}]" if ":" in addr else addr''',
        '''    return addr''',
        "tests/test_server.py::test_the_derivation_is_the_authority_form_plus_the_name_a_standard_fixes"),

    Mutation(
        "derived-hosts", "the derivation may store a bind address in a case the lookup never asks for",
        SRC / "server.py",
        '''    return frozenset({_authority(addr).lower() for addr in addresses}) | RESOLVER_FIXED''',
        '''    return frozenset({_authority(addr) for addr in addresses}) | RESOLVER_FIXED''',
        "tests/test_server.py::test_the_derivation_is_the_authority_form_plus_the_name_a_standard_fixes"),

    Mutation(
        "derived-hosts", "the derivation may admit only what the bind list supplies again",
        SRC / "server.py",
        '''    return frozenset({_authority(addr).lower() for addr in addresses}) | RESOLVER_FIXED''',
        '''    return frozenset({_authority(addr).lower() for addr in addresses})''',
        "tests/test_server.py::test_the_name_a_standard_fixes_is_accepted_as_a_live_host_header"),

    Mutation(
        "derived-hosts", "the Host check may stop keeping the brackets a browser sends again",
        SRC / "server.py",
        '''    if host.startswith("["):                       # [::1]:8765
        host = host.split("]")[0] + "]"
    elif ":" in host:''',
        '''    if ":" in host:''',
        "tests/test_server.py::test_the_derived_table_answers_both_lookups_for_any_address_it_is_given"),

    Mutation(
        "derived-hosts", "the Origin check may stop stripping the brackets off the table again",
        SRC / "server.py",
        '''    return host in {h.strip("[]") for h in LOOPBACK_HOSTS}''',
        '''    return host in set(LOOPBACK_HOSTS)''',
        "tests/test_server.py::test_the_derived_table_answers_both_lookups_for_any_address_it_is_given"),

    # ── bind (CHG-20260907-20) ───────────────────────────
    # `LOOPBACK` called itself "the only addresses this server will bind" and named one the
    # socket has never opened: `address_family` is `AF_INET` and `AF_INET` refuses `::1`. The
    # two tests CHG-19 added read the list against the header set and neither could see it,
    # because the claim is about the operating system and both stopped at Python. The third
    # entry is the error branch that hid it: `gaierror` is an `OSError`, so a resolver answer
    # was reported as a port conflict.
    #
    # Re-anchored by CHG-20260907-24, which derived the header set and narrowed the bind list to
    # one member. Entry 1 now names the test whose guarantee it is rather than the file: the
    # socket is the only instrument that can see this, and `::1` back in the list also puts
    # `[::1]` back in the header table -- five objectors in all, three of them origin tests, so a
    # file-level CAUGHT would not have said the socket noticed.
    #
    # The second entry -- *"the header set may accept an authority no listener can answer on"* --
    # is **deleted with its guarantee**, not re-anchored. It edited a hand-written
    # `LOOPBACK_HOSTS`, and there is no longer one to edit. Both doors into that table are
    # covered: an address arrives through `LOOPBACK` (entry 1 here) and anything else through
    # `RESOLVER_FIXED` (`resolver-fixed` entry 2). **What refuses it there is the literal pin, not
    # a shape check** -- an earlier draft of this comment said "by shape", and a review seat
    # measured that the shape conditions cannot fail while the pin stands, which is why they are
    # no longer written as assertions at all.
    Mutation(
        "bind", "the permit list may name an address the socket cannot open again",
        SRC / "server.py",
        '''LOOPBACK = ("127.0.0.1",)''',
        '''LOOPBACK = ("127.0.0.1", "::1")''',
        "tests/test_server.py::test_every_permitted_address_can_actually_be_bound"),

    Mutation(
        "bind", "every way a bind can fail may be called a port conflict again",
        SRC / "server.py",
        '''        if exc.errno == errno.EADDRINUSE:''',
        '''        if True:''',
        "tests/test_server.py"),

    # Re-anchored by CHG-20260907-24, because the edit it shipped with became a no-op: it replaced
    # `' or '.join(LOOPBACK)` with `LOOPBACK[0]`, and with one member in the list those are the
    # same string. Measured NOT CAUGHT under the narrowing. The guarantee is unchanged and the
    # assertion that holds it is unchanged -- a refusal must name every address `serve` takes --
    # so what is registered is an edit that can still make it false: the refusal naming none.
    Mutation(
        "bind", "the refusal may stop naming the addresses it will take again",
        SRC / "server.py",
        '''f"on {' or '.join(LOOPBACK)} and nowhere else. If another machine needs to see it, put "''',
        '''f"on this machine and nowhere else. If another machine needs to see it, put "''',
        "tests/test_server.py::test_it_refuses_to_bind_anything_but_loopback"),

    # Both added in review of the build. The fifth is the one that matters: two branches are
    # defensible only because the plain one carries the operating system's own sentence, and
    # removing that sentence was caught by nothing. The sixth is the other kind of widening --
    # `0.0.0.0` BINDS, so no bind test refuses it; what fails is local-only, and this is what
    # makes the socket test's address assertion load-bearing rather than incidental.
    Mutation(
        "bind", "a failure may stop saying what the operating system said again",
        SRC / "server.py",
        '''        raise ServerError(f"cannot listen on {host}:{port} — {paths.plain_in(str(exc))}.")''',
        '''        raise ServerError(f"cannot listen on {host}:{port}.")''',
        "tests/test_server.py"),

    Mutation(
        "bind", "the permit list may take an address the whole network can reach again",
        SRC / "server.py",
        '''LOOPBACK = ("127.0.0.1",)''',
        '''LOOPBACK = ("127.0.0.1", "0.0.0.0")''',
        "tests/test_server.py::test_it_refuses_to_bind_anything_but_loopback"),

    # ── loopback (CHG-20260907-19) ───────────────────────
    # One boundary written twice: `LOOPBACK` is what `serve` permits as a bind argument,
    # `LOOPBACK_HOSTS` is what a `Host` or `Origin` may say. No test named either constant.
    # Re-anchored by CHG-20260907-20, which took `"::1"` and its two header spellings out; one
    # entry was DELETED there rather than re-anchored, because its guarantee went with them --
    # there is no permitted IPv6 address left for a bracketed form to be lost from. Not
    # registered, then or now: removing the bare "::1", which one seat proposed and measurement
    # refused - `"[::1]".strip("[]")` supplied it to `_loopback_origin`, and `_loopback_host`
    # reached it only through `Host: ::1:8765`, an unbracketed IPv6 authority no compliant
    # client sends.
    # Re-anchored again by CHG-20260907-24, and **two of the four are deleted with their
    # guarantees** because deriving `LOOPBACK_HOSTS` made the states they name unreachable:
    #
    #   "the header check may be tightened below what the bind list permits"  -- there is no
    #       hand-written header set left to tighten; it follows the bind list by construction.
    #   "the bind list may lose an address the header check still accepts"    -- the header check
    #       cannot still accept it. The name it went to, the set equality, is gone with it.
    #
    # That is this record's product rather than a hole in it, and the entry below replaces the
    # second with what is still true and still falsifiable: `serve`'s own default has to be a
    # member. Losing `127.0.0.1` draws ten objectors and 52 errors; `test_binding_loopback_is_
    # allowed` is the one whose guarantee that is.
    #
    # The first entry keeps its anchor and loses half its `says`. Under a hand-written table,
    # `127.0.0.2` in the bind list was *"an address no request may name"* -- the server refused
    # its own requests and blamed the header. Derivation makes that impossible, so what is left
    # is the other half: it is not the address this constant promises. One objector now, measured
    # twice, and it is the socket.
    #
    # **Not "an address that is not this machine"**, which is what an earlier draft of this `says`
    # read and which a review seat refused: `127.0.0.2` **is** this machine, it is in 127.0.0.0/8,
    # and that is precisely why ACC-20260907-20 kept the socket test's `server_address[0] ==
    # "127.0.0.1"` instead of the `is_loopback` weakening a seat proposed there. What the socket
    # objects to is the address not being the one the constant promises.
    Mutation(
        "loopback", "the bind list may permit an address the constant does not promise again",
        SRC / "server.py",
        '''LOOPBACK = ("127.0.0.1",)''',
        '''LOOPBACK = ("127.0.0.1", "127.0.0.2")''',
        "tests/test_server.py::test_every_permitted_address_can_actually_be_bound"),

    Mutation(
        "loopback", "the bind list may lose the address serve itself defaults to again",
        SRC / "server.py",
        '''LOOPBACK = ("127.0.0.1",)''',
        '''LOOPBACK = ("localhost",)''',
        "tests/test_server.py::test_binding_loopback_is_allowed"),

    # The rebinding guard, re-anchored to the door that is left. A name enters `LOOPBACK_HOSTS`
    # without being an address `serve` binds only through `RESOLVER_FIXED` now, and that set is
    # pinned against a literal on the test side -- a set union permits, and it takes a separate
    # assertion to make it forbid.
    Mutation(
        "loopback", "the rebinding guard may accept a name this server never answers on again",
        SRC / "server.py",
        '''RESOLVER_FIXED = frozenset({"localhost"})''',
        '''RESOLVER_FIXED = frozenset({"localhost", "runner.local"})''',
        "tests/test_server.py::test_the_names_a_standard_fixes_are_the_one_member_that_was_measured"),

    # ── decisions (CHG-20260907-16) ────────────────────────────────
    # `plan.check` refused an unknown KEY with 'ignoring them would let a setting look
    # configured and do nothing', and accepted an unknown NODE. `feedback` sits after
    # `merge`, so the typo was found past the one-way door. The last entry names
    # `test_module_built.py` because that is where the front door's refusal is asserted.
    Mutation(
        "decisions", "a plan may decide a node this flow does not have again",
        SRC / "engine.py",
        '''        if node_id not in graph.BY_ID:''',
        '''        if False:''',
        "tests/test_plan.py"),

    Mutation(
        "decisions", "a plan may decide a branch the node does not offer again",
        SRC / "engine.py",
        '''            if branch == FRONTIER or branch in offered:''',
        '''            if True:''',
        "tests/test_plan.py"),

    Mutation(
        "decisions", "a plan may supply a decision the run reads for itself again",
        SRC / "engine.py",
        '''        if node_id in DERIVED_DECISIONS:''',
        '''        if False:''',
        "tests/test_plan.py"),

    Mutation(
        "decisions", "a run built without a plan may skip the check again",
        SRC / "engine.py",
        '''        check_decisions(self.decisions, where="this run")''',
        '''        pass''',
        "tests/test_module_built.py"),

    # ── record-lifecycle (CHG-20260907-15) ─────────────────────────
    # `conversation.close` lives in `_finish` alone and every `_finish` is on a `return`,
    # so the closing turn was written on seven of the eight return paths and on none of
    # the exceptional ones. The third entry is the false green: `RunReport.state` defaults
    # to FINISHED, so closing with it would record a crash as a clean run. The second is
    # why `Exception` is not enough -- an interruption is the case a record exists for.
    Mutation(
        "record-lifecycle", "a walk that dies may leave its record open again",
        SRC / "engine.py",
        '''    except BaseException as exc:
        if cfg.conversation is not None:''',
        '''    except BaseException as exc:
        if False:''',
        "tests/test_conversations.py"),

    Mutation(
        "record-lifecycle", "an interruption may go unrecorded again",
        SRC / "engine.py",
        '''    except BaseException as exc:''',
        '''    except Exception as exc:''',
        "tests/test_conversations.py"),

    Mutation(
        "record-lifecycle", "a crashed walk may be recorded as one that finished again",
        SRC / "engine.py",
        '''                STOPPED, at_node=where.get("node"),''',
        '''                FINISHED, at_node=where.get("node"),''',
        "tests/test_conversations.py"),

    # ── propagation (CHG-20260907-14) ──────────────────────────────
    # `reach_guessed` joined `models.COMPUTED` in CHG-20260903-39 and reached none of the
    # four documents that enumerate the set. Each of these puts one of those documents
    # back to two fields, or back to quoting a sentence the source stopped carrying.
    Mutation(
        "propagation", "a page may enumerate two computed fields again",
        REPO / "docs" / "SCHEMAS.md",
        '''`leaves_this_machine` follows from it, and `reach_guessed` says whether the derivation had''',
        '''`leaves_this_machine` follows from it, and the derivation had''',
        "tests/test_schemas.py"),

    Mutation(
        "propagation", "the payload sketch may omit a key the route ships again",
        REPO / "docs" / "API.md",
        '''                "reach", "leaves_this_machine", "reach_guessed" } ],''',
        '''                "reach", "leaves_this_machine" } ],''',
        "tests/test_api_schema.py"),

    Mutation(
        "propagation", "a document may quote a comment the source does not carry again",
        REPO / "docs" / "MODELS.md",
        '''`models.COMPUTED` is declared:
*"Storing one would let a stale label outlive the truth."*''',
        '''`models.COMPUTED` is declared:
*"both are computed; storing them would let a stale label outlive the truth."*''',
        "tests/test_documented_numbers.py"),

    # ── contradiction (CHG-20260907-13) ────────────────────────────
    # The guard these replace proved a **true** sentence was present:
    #     assert f"{built} of {built} tables" in catalogue
    # which was green while the heading of the section its row describes said three of
    # five. So the first two break a document rather than the code -- that is where the
    # claim lives -- and the third takes a withdrawn sentence out of its `>` block and
    # back into live prose, which is the whole boundary `_prose` draws.
    Mutation(
        "contradiction", "a section heading may contradict the row it heads again",
        REPO / "docs" / "SCHEMAS.md",
        '''## 14 · SQLite DDL — six of six tables built''',
        '''## 14 · SQLite DDL — three of five tables built''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "contradiction", "a route count may disagree with the server again",
        REPO / "docs" / "SCHEMAS.md",
        '''Nineteen routes, eight `GET` and eleven `POST`, every one crossing''',
        '''Nineteen routes, eight `GET` and nine `POST`, every one crossing''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "contradiction", "a document may call a built table uncreated again",
        REPO / "docs" / "SCHEMAS.md",
        '''> This paragraph said `conversations` and `turns` were *"not created by any code yet"* until''',
        '''This paragraph is where `conversations` and `turns` are not created by any code yet, until''',
        "tests/test_documented_numbers.py"),

    # ── claim-referent (CHG-20260907-12) ───────────────────────────
    # The subject is a guard that read the right number against the wrong thing, so these
    # break what the guard guards -- a document's claim, a document's referent, and the
    # payload a claim describes. An earlier draft mutated the assertions themselves and
    # reported NOT CAUGHT and ANCHOR GONE, which was right: disabling a test and then
    # running that same test proves nothing about it.
    Mutation(
        "claim-referent", "a documented field count may drift from what it names again",
        REPO / "docs" / "structure" / "data.md",
        '''Seventeen fields, listed in `workorder.WORK_ORDER_FIELDS`''',
        '''Sixteen fields, listed in `workorder.WORK_ORDER_FIELDS`''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "claim-referent", "a field count may stop saying what it counts again",
        REPO / "docs" / "structure" / "design.md",
        '''**Three fields, listed in `settings.FIELDS`.**''',
        '''**Three fields.**''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "claim-referent", "the flow route may send a different number of node fields than the page states again",
        SRC / "server.py",
        '''                     "branches": dict(n.branches), "next": n.next,''',
        '''                     "next": n.next,''',
        "tests/test_api_schema.py"),

    # ── gate-phase (CHG-20260907-11) ────────────────────────────────
    # A validator cannot choose between two valid values, so these two pin the
    # assignment rather than the rule. Measured before they existed: moving
    # `pm_signoff` to `before` and `engineer_selfverify` to `after` keeps the count
    # test at ten and three and leaves the **whole suite** green -- 2292 passed. The
    # first names `test_flow.py` on purpose: the phase is only observable in who gets
    # asked, and every test that pinned that node checked where the run stopped.
    Mutation(
        "gate-phase", "a sign-off may be reached without anyone being asked again",
        SRC / "graph.py",
        '''         gate="before_dispatch", gate_when="after", answer_decides=True, mode=MODEL_PANEL,''',
        '''         gate="before_dispatch", gate_when="before", answer_decides=True, mode=MODEL_PANEL,''',
        "tests/test_flow.py"),

    Mutation(
        "gate-phase", "which gate is consulted when may change unnoticed again",
        SRC / "graph.py",
        '''         gate="self_verify", gate_when="before", next="lead_task_review", mode=FOLLOWS,''',
        '''         gate="self_verify", gate_when="after", next="lead_task_review", mode=FOLLOWS,''',
        "tests/test_graph_validation.py"),

    # ── mode-declared (CHG-20260907-26) ───────────────
    # `Node.mode` defaulted to `SINGLE`, which is 4 of the 31 nodes where `RUNNER` is 15 --
    # the minority value, the same shape the `gate-phase` group above was written for. A
    # role-bearing node whose author never thought about its mode was read as one model in
    # one session and `validate` accepted it: measured, `lead_task_review` rebuilt from its
    # own fields minus `mode` came back `single` against a real `model_panel`.
    #
    # The first entry is the default itself. It must be reached through the **constructor**,
    # because that is the only place a default acts: the obvious test
    # `_mutate("pm_plan", mode=None)` passes with the default restored, since what it trips
    # is the `is None` rule and that rule survives this mutation. Measured before the test
    # was written: with `mode: str = SINGLE` back, nothing in the suite objects -- no shipped
    # node omits `mode`, and the one construction that did (`test_rerun_idempotence.py:118`)
    # is never validated. The second entry pins the message rather than the refusal: with the
    # `is None` rule gone the closed-set rule below it still raises, saying "unknown mode
    # None", which sends a reader after a typo when what happened is an omission.
    #
    # **Absent on purpose:** the other half of CHG-20260907-26 removes a hand-written count
    # from a comment in `graph.py` -- "three nodes are `role="lead"`", where there are five,
    # false from the commit that wrote it. Nothing can catch that returning. It is prose, and
    # the sweep that reads `graph.py` for stale numbers
    # (`test_the_node_count_in_the_documents_matches_the_graph`) matches digits only, which is
    # not an oversight: of the 12 spelled-out "<word> nodes" phrases across the swept files,
    # 11 are true counts of a *subset*, so a word-aware rule comparing against `len(NODES)`
    # would fail 11 true sentences. The repair was to delete the number, and a deleted number
    # is guarded by nothing -- which is why it is a smaller claim than a rule.
    Mutation(
        "mode-declared", "a node may take a mode nobody chose for it again",
        SRC / "graph.py",
        '''    mode: Optional[str] = None''',
        '''    mode: str = SINGLE''',
        "tests/test_execution_mode.py::test_a_node_whose_author_never_declared_a_mode_is_refused"),

    Mutation(
        "mode-declared", "an omitted mode may be reported as a typo again",
        SRC / "graph.py",
        '''        if node.mode is None:''',
        '''        if False:''',
        "tests/test_execution_mode.py::test_a_node_whose_author_never_declared_a_mode_is_refused"),

    # ── kind-and-edges (CHG-20260907-09) ──────────────────────────────
    # `MODES` was closed from the day it was written; `kind` was not, and the difference was
    # worth 23 of 31 nodes accepting nonsense -- with `done` reaching the engine's terminal
    # test as an ordinary node, so a finished run reported no `halted_at`, in the returned
    # report and in the durable conversation record both. The second rule is the same defect
    # in the edges: `validate` walks the union of `branches` and `next`, a run takes one of
    # them, and where they differ the guard is measuring a graph that does not run.
    Mutation(
        "kind-and-edges", "a node's kind may be nonsense again",
        SRC / "graph.py",
        '''        if node.kind not in KINDS:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "kind-and-edges", "a node may declare an edge no run can take again",
        SRC / "graph.py",
        '''        if node.branches and node.next:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "kind-and-edges", "the closed set may quietly gain a member again",
        SRC / "graph.py",
        '''KINDS = (STEP, DECISION, LOOP, TERMINAL)''',
        '''KINDS = (STEP, DECISION, LOOP, TERMINAL, "seat_panel")''',
        "tests/test_graph_validation.py"),

    Mutation(
        "kind-and-edges", "which nodes are loops may change unnoticed again",
        SRC / "graph.py",
        '''    Node("plan_scope", LOOP, "one workstream or several", mode=RUNNER,''',
        '''    Node("plan_scope", DECISION, "one workstream or several", mode=RUNNER,''',
        "tests/test_graph_validation.py"),

    # ── graph-validation (CHG-20260907-07) ───────────────────────────────────────
    # `validate()` is the only guard over the flow, and nineteen of its thirty-two rules had
    # no reverse test: each could be deleted with every likely test file still green. The one
    # CHG-20260901-11 added to close a defect was among them -- the check a repair installs is
    # itself somewhere the next defect can hide. One entry per rule now pinned.
    Mutation(
        "graph-validation", "two nodes may share an id again",
        SRC / "graph.py",
        '''    if len(BY_ID) != len(NODES):''',
        '''    if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "an edge may name a node that does not exist again",
        SRC / "graph.py",
        '''            if target not in ids:''',
        '''            if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a terminal may have an outgoing edge again",
        SRC / "graph.py",
        '''        if node.kind == TERMINAL and targets:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a decision may offer fewer than two branches again",
        SRC / "graph.py",
        '''        if node.kind in (DECISION, LOOP) and len(node.branches) < 2:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a step may have no successor again",
        SRC / "graph.py",
        '''        if node.kind == STEP and not node.next:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a node may name a gate policy does not have again",
        SRC / "graph.py",
        '''        if node.gate and node.gate not in policy.GATES:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a node may name a role policy does not have again",
        SRC / "graph.py",
        '''        if node.role and node.role not in policy.BY_ROLE:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a gate phase outside the two words is accepted again",
        SRC / "graph.py",
        '''        if node.gate_when is not None and node.gate_when not in ("before", "after"):''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    # Re-anchored by CHG-20260907-11, which rewrote both lines. The guarantee above is the same
    # one; the guarantee below is **larger** than the entry it replaces -- "an after phase may
    # name no gate" was half a contract, and the type change made the other half sayable.
    # Re-anchoring is not evidence: the whole group was run again.
    Mutation(
        "graph-validation", "a gate and its phase may go without each other again",
        SRC / "graph.py",
        '''        if (node.gate is None) != (node.gate_when is None):''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "an answer may decide where nobody is asked again",
        SRC / "graph.py",
        '''        if node.answer_decides and not node.role:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a rejection may be declared where there is no gate to refuse again",
        SRC / "graph.py",
        '''            if not node.gate:''',
        '''            if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a rejection may name a node that does not exist again",
        SRC / "graph.py",
        '''            if node.rejects_to not in ids:''',
        '''            if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a rejection may return to the node that was refused again",
        SRC / "graph.py",
        '''            if node.rejects_to == node.id:''',
        '''            if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "an unreachable node is accepted again",
        SRC / "graph.py",
        '''    if unreachable:''',
        '''    if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a node that is not a terminal may be permanent again",
        SRC / "graph.py",
        '''        if n.permanent and n.kind != TERMINAL:''',
        '''        if False:''',
        "tests/test_graph_validation.py"),

    Mutation(
        "graph-validation", "a node may follow itself and be told it follows something else again",
        SRC / "graph.py",
        '''            if node.follows == node.id:
                raise GraphError(f"node {node.id!r} follows itself")
            if BY_ID[node.follows].mode == FOLLOWS:''',
        '''            if BY_ID[node.follows].mode == FOLLOWS:''',
        "tests/test_execution_mode.py"),

    # ── effect-state (CHG-20260907-06) ─────────────────────────────────────────────
    # `STOPPED`'s own definition says it covers *a permanent halt, or an effect that
    # failed*. The second clause was never implemented: the except block set `halted_at`
    # and `halt_reason` and left `state` at its `FINISHED` default, so a run whose `pr`
    # effects half-landed reported `finished` to the terminal, the console and the durable
    # conversation record. CHG-20260827-22 made this same decision for the first clause.
    Mutation(
        "effect-state", "a failed effect reports itself as a normal finish again",
        SRC / "engine.py",
        '''        report.state = STOPPED
        report.halted_at = node.id''',
        '''        report.halted_at = node.id''',
        "tests/test_flow.py"),

    # ── option-distinctness (CHG-20260907-05) ───────────────────────────────────────
    # `option_request` asks a model for *different* options; `read_options` counted the
    # length of the list, so three copies of one label passed the check that exists because
    # one option is a decision wearing a question mark. The request and the check disagreed,
    # twenty lines apart in one module.
    Mutation(
        "option-distinctness", "one label repeated goes back to counting as three choices",
        SRC / "intake.py",
        '''    distinct = len(set(options))''',
        '''    distinct = len(options)''',
        "tests/test_intake.py"),

    # ── intake-count / refused-answer (CHG-20260907-04) ─────────────────────────────────────────
    # One count with two definitions, and a journal that keeps what the walk refused.
    # The CLI writer recorded a stop on every walk that suspended incomplete, including a
    # `--resume` where nothing was dispatched -- measured, three resumes took the count from
    # 5 to 8 while each printed *4 ask(s) answered from the journal, not re-asked*. The server
    # writer missed its FIRST stop whenever the run began on nothing, because the mark and
    # `told` were both 0. And an option answer the walk refused was journaled as `answered`,
    # so `--resume` replayed it and refused it again -- with no way out that did not mean
    # abandoning the resume or changing the brief the escalation exists to avoid changing.
    Mutation(
        "intake-count", "a run that started on nothing goes back to not counting its first stop",
        SRC / "server.py",
        '''    instructions_at_last_incomplete_stop: int = -1''',
        '''    instructions_at_last_incomplete_stop: int = 0''',
        "tests/test_server.py"),

    Mutation(
        "intake-count", "a resume that asked nobody is counted as an ask again",
        SRC / "cli.py",
        '''            and len(report.resumed) < len(report.asks)):''',
        '''            and True):''',
        "tests/test_cli.py"),

    Mutation(
        "refused-answer", "an answer the walk refused is reused from the journal again",
        SRC / "engine.py",
        '''                and _acceptable(accept, answered[ask_id])):''',
        '''                and True):''',
        "tests/test_intake.py"),

    Mutation(
        "refused-answer", "a refused answer stays journaled as answered",
        SRC / "engine.py",
        '''                journal.refuse(ask_id, f"{type(exc).__name__}: {exc}", result)''',
        '''                pass''',
        "tests/test_intake.py"),

    # ── non-text-answer (CHG-20260907-03) ─────────────────────────────────────────
    # `_strings` read a truthy value that was not text with `str()`, in BOTH branches:
    # `{"problems": true}` became a problem named `True`, and `{"unsafe": [{...}]}` became a
    # Python repr at the stop that asks a person to read it -- with `--proceed-unsafe`
    # spending its digest against that repr. CHG-20260903-36 had taught only the scalar
    # fallback that a falsy value is silence. One helper now reads every item; the second
    # mutation exists because the first would pass a repair that swept only the fallback,
    # which is the shape of the mistake this change corrects.
    Mutation(
        "non-text-answer", "a truthy value that is not text is read as text again",
        SRC / "intake.py",
        '''    if isinstance(item, str):
        return item.strip() or None''',
        '''    return str(item).strip() or None''',
        "tests/test_intake.py"),

    Mutation(
        "non-text-answer", "the list branch goes back around the one rule",
        SRC / "intake.py",
        '''        texts = [_text(v, f"{where}[{i}]") for i, v in enumerate(value)]''',
        '''        texts = [str(v).strip() for v in value]''',
        "tests/test_intake.py"),

    # ── surveyed-render (CHG-20260907-02) ─────────────────────────────────────────
    # `problems` and `safety` are `seat -> [line]` maps, and the block drawing the survey
    # handed each value to `String()` -- `[object Object]`. It is drawn on every render, and
    # the readable rendering of `safety` is drawn only inside a suspension, so a finished run
    # showed the words a seat wrote as `[object Object]` and nowhere else. No `node` here, so
    # these pin the text; the guard asserts what each reversion removes.
    Mutation(
        "surveyed-render", "the survey goes back to being printed as [object Object]",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        '''      if (v && typeof v === "object" && !Array.isArray(v)) {''',
        '''      if (false) {''',
        "tests/test_server.py"),

    Mutation(
        "surveyed-render", "the lines stop saying which seat said them",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        '''          (v[seat] || []).forEach(function (line) { out.push(k + ": " + seat + ": " + line); });''',
        '''          (v[seat] || []).forEach(function (line) { out.push(k + ": " + line); });''',
        "tests/test_server.py"),

    # ── silent-seat (CHG-20260907-01) ─────────────────────────────────────────────
    # `engine.walk` refuses a model panel voice that names no answer — *a voice that said
    # nothing is not a voice that voted no*. The survey had no equivalent, so a seat
    # answering `{"verdict": "pass"}` — the shape every other seat node expects — was
    # counted as having found nothing. Measured with `cli._Stub`, the shipped default.
    Mutation(
        "silent-seat", "a seat that says nothing about the requirement is counted as a pass",
        SRC / "intake.py",
        '''        if not ANSWER_KEYS & set(answer):''',
        '''        if False:''',
        "tests/test_intake.py"),

    # ── unsafe-stop (CHG-20260906-07) ─────────────────────────────────────────────
    # A seat answering {"unsafe": [...], "missing": []} gave complete=True, no suspension,
    # and the run walked to `merge` with the words the seat used printed on no surface at
    # all. Two of these pin the mechanism; two pin the **rule the operator chose** — that a
    # flag given before anything was shown decides nothing — which the mechanism alone would
    # let through silently.
    Mutation(
        "unsafe-stop", "a seat's unsafe finding no longer stops the run",
        SRC / "engine.py",
        '''                if not survey.complete or unsafe:''',
        '''                if not survey.complete:''',
        "tests/test_intake.py"),

    Mutation(
        "unsafe-stop", "the flag decides without the findings having been shown",
        SRC / "engine.py",
        '''                    if intake_mod.shown_digest(survey.safety) in tuple(cfg.unsafe_shown):''',
        '''                    if True:''',
        "tests/test_intake.py"),

    Mutation(
        "unsafe-stop", "a first run carrying the flag is allowed to walk",
        SRC / "cli.py",
        '''    if getattr(args, "proceed_unsafe", False) and not (journal and journal.unsafe_shown()):''',
        '''    if False:''',
        "tests/test_cli.py"),

    Mutation(
        "unsafe-stop", "the terminal says nothing about what a seat called unsafe",
        SRC / "cli.py",
        '''        elif stop.get("unsafe"):''',
        '''        elif False and stop.get("unsafe"):''',
        "tests/test_cli.py"),

    Mutation(
        "unsafe-stop", "an unsafe stop is answerable as if it were a gate",
        SRC / "server.py",
        '''        is_unsafe = bool(report.suspended.get("unsafe"))''',
        '''        is_unsafe = False''',
        "tests/test_server.py"),

    # ── phantom-flag (CHG-20260906-06) ─────────────────────────────────────────────
    # `NOT_ON_THE_CONSOLE` gives, for each field it excludes, the reason a reader would
    # argue with. One of those reasons named `--json` — a flag no commit of this
    # repository has ever declared. The guard asks the parser, so a reason that names a
    # flag must name one that exists.
    Mutation(
        "phantom-flag", "an exclusion is justified by a flag that does not exist",
        REPO / "tests" / "test_server.py",
        '''    "risk_settled": "the grade the run was governed by — reaches the terminal only",''',
        '''    "risk_settled": "the grade the run was governed by — reaches `--json` and the terminal only",''',
        "tests/test_server.py"),

    Mutation(
        "phantom-flag", "the guard only knows the one field it was written for",
        REPO / "tests" / "test_server.py",
        '''    "relaxations": "the runner's own relaxations — `--undeclared allow` and the like",''',
        '''    "relaxations": "the runner's own relaxations — `--store-remote allow` and the like",''',
        "tests/test_server.py"),

    # ── attachment-provenance (CHG-20260906-04) ───────────────────────────────────────────────────────
    # `Attachment.instruction` was written, validated, sorted on and serialised, and read by
    # nothing that shows it to a person — while its own comment claimed it existed so a later
    # brief could say where a document came from. KN-8: make the sentence true or delete it.
    Mutation(
        "attachment-provenance", "the console stops saying where a document came from",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        """    var when = f.instruction ? "with instruction " + f.instruction""",
        """    var when = false ? "with instruction " + f.instruction""",
        "tests/test_cli.py"),

    Mutation(
        "attachment-provenance", "an attachment that arrived before any instruction says nothing",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        """                             : "before the first instruction";""",
        """                             : "";""",
        "tests/test_cli.py"),
    # ── approval-lifetime (CHG-20260906-03) ────────────────────────────────────────────────
    # A finished high-risk run, all eight gates answered by a person, re-walked all 17 nodes on one
    # attached file — rebuild, re-review, re-open the PR, re-merge — spending all eight answers
    # again, with no stop, reporting "nothing further was asked for". The engine already applies
    # this rule to what a model said and did not apply it to what a person said.
    Mutation(
        "approval-lifetime", "an approval is spent again on a brief nobody gave it for",
        SRC / "server.py",
        """            (live if approval.brief in (None, here) else retired).append(approval)""",
        """            live.append(approval)""",
        "tests/test_server.py"),

    Mutation(
        "approval-lifetime", "every re-walk retires the approvals, so no run can finish",
        SRC / "server.py",
        """            (live if approval.brief in (None, here) else retired).append(approval)""",
        """            retired.append(approval)""",
        "tests/test_server.py"),

    Mutation(
        "approval-lifetime", "an approval given up-front on the command line stops answering",
        SRC / "server.py",
        """            (live if approval.brief in (None, here) else retired).append(approval)""",
        """            (live if approval.brief == here else retired).append(approval)""",
        "tests/test_server.py"),

    Mutation(
        "approval-lifetime", "the brief is a count again, so a replaced document reads as no change",
        SRC / "server.py",
        """        return (len(self.state.instructions),
                tuple(sorted(a.id for a in self.state.attachments)))""",
        """        return (len(self.state.instructions),
                len(self.state.attachments))""",
        "tests/test_server.py"),

    Mutation(
        "approval-lifetime", "a retired approval is deleted from the ledger instead of kept",
        SRC / "server.py",
        # Anchored on the line above the check as well, since CHG-20260906-07 gave
        # `retired_approvals` a second writer — a decision about unsafe findings that the brief
        # outgrew — whose dedupe-and-append is textually identical. One list, two things retired
        # into it; this entry means the approval one.
        """                        f"and this gate asks again")
                if note not in self.state.retired_approvals:""",
        """                        f"and this gate asks again")
                self.state.approvals.remove(approval)
                if note not in self.state.retired_approvals:""",
        "tests/test_server.py"),

    Mutation(
        "approval-lifetime", "the operator is never told an approval was retired",
        SRC / "server.py",
        """            "retired_approvals": list(self.retired_approvals),""",
        """            "retired_approvals": [],""",
        "tests/test_server.py"),
    # ── request-layer (CHG-20260906-02) ────────────────────────────────────────────────────
    # `_body` read whatever Content-Length announced, before any limit applied and before route
    # dispatch, so the bound was missing for every POST and not only the one route that had a
    # limit underneath it. The deadline is a separate property: a connection that says nothing at
    # all never reaches `_body`, and 20 of them held 20 threads.
    Mutation(
        "request-layer", "the body is read before it is bounded again",
        SRC / "server.py",
        '''            if length > MAX_BODY_BYTES:''',
        '''            if False:''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "the wire limit is set to the attachment limit, refusing legal uploads",
        SRC / "server.py",
        '''MAX_BODY_BYTES = attach_mod.MAX_BYTES * 4 // 3 + 1024 * 1024''',
        '''MAX_BODY_BYTES = attach_mod.MAX_BYTES''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "a connection may hold a thread for as long as it likes again",
        SRC / "server.py",
        '''        timeout = 30''',
        '''        timeout = None''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "a Content-Length that is not a number goes back to being a 500",
        SRC / "server.py",
        '''            try:
                length = int(raw_length)
            except ValueError:''',
        '''            if True:
                length = int(raw_length)
            elif False:''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "a negative Content-Length is read to EOF again",
        SRC / "server.py",
        '''            if length < 0:''',
        '''            if False:''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "a body that arrives short is parsed as if it were whole",
        SRC / "server.py",
        '''            if len(data) < length:''',
        '''            if False:''',
        "tests/test_server.py"),

    Mutation(
        "request-layer", "a JSON array reaches body.get() and becomes a 500",
        SRC / "server.py",
        '''            if not isinstance(body, dict):''',
        '''            if False:''',
        "tests/test_server.py"),
    # ── doc-truth (CHG-20260905-05) ────────────────────────────────────────────────────────
    # A test three records call proof of a property it never touched, and two documents that
    # disagreed about what the package is. Both now have something that fails when they stop
    # being true.
    Mutation(
        "doc-truth", "the scan test stops driving the halt and asserts on a helper again",
        REPO / "tests" / "test_attachments.py",
        '''    halt = _halts_on_artifacts(["production/manifest.yaml"])
    assert halt is not None, "a brief naming a production target stopped halting"''',
        '''    halt = "deploy" in policy.derive(["kubectl apply -f prod/"]) or None
    assert halt is not None, "a brief naming a production target stopped halting"''',
        "tests/test_attachments.py"),

    Mutation(
        "doc-truth", "a module list stops being compared with the package",
        REPO / "tests" / "test_documented_numbers.py",
        '''    return [m for m in modules if m not in text]''',
        '''    return []''',
        "tests/test_documented_numbers.py"),

    # One `doc-truth` mutation was retired rather than faked (CHG-20260905-05): narrowing
    # `INVENTORIES` back to one document. Both documents are complete now, so dropping one changes
    # nothing any test can observe — the same shape CHG-20260904-19 retired for `CITED_ROOTS`, and
    # for the same reason. What is pinned instead is the **rule**, pointed at planted text:
    # `modules_missing_from` above, and `test_the_inventory_guard_can_see_a_module_that_is_missing_
    # from_a_list`. Re-anchoring it onto a live gap would mean leaving a document wrong on purpose.

    Mutation(
        "doc-truth", "an id with neither a record nor a link is called resolvable",
        REPO / "tests" / "test_documented_numbers.py",
        '''    return {what: where for what, where in cited.items()
            if what not in records and what not in followable}''',
        '''    return {}''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "doc-truth", "a link nobody can open counts as a way to follow a citation",
        REPO / "tests" / "test_documented_numbers.py",
        '''        if (source.parent / href).resolve().exists():''',
        '''        if True:''',
        "tests/test_documented_numbers.py"),
    # ── attachments (CHG-20260905-04) ──────────────────────────────────────────────────────
    # 225 lines, two importers, named in 26 records, and 0 of 253 mutations. Its own docstring
    # records two defects found live, and nothing guarded either. Every entry here reverts the
    # line this change edited.
    Mutation(
        "attachments", "the wired door stops checking what the manifest holds",
        SRC / "attachments.py",
        '''            if not _STORED_NAME.match(name):''',
        '''            if False:''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "the shape check picks up an existence check and drops a lost attachment",
        SRC / "attachments.py",
        '''            out.append(str(self.dir / name))''',
        '''            if not paths.exists(self.dir / name):
                continue
            out.append(str(self.dir / name))''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "the manifest is truncated before its replacement exists",
        SRC / "attachments.py",
        '''        staging = self.dir / "manifest.json.writing"
        paths.write_text(
            staging,''',
        '''        staging = self.manifest_path
        paths.write_text(
            staging,''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "a manifest that parses into the wrong shape crashes instead of refusing",
        SRC / "attachments.py",
        '''        if not isinstance(raw, dict):''',
        '''        if False:''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "an instruction that is not a number is read as one",
        SRC / "attachments.py",
        '''            if not isinstance(attachment.instruction, int) or isinstance(''',
        '''            if False and isinstance(''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "two documents sharing a stored name silently become one again",
        SRC / "attachments.py",
        '''        if clash:''',
        '''        if False:''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "the declared media type stops having to match the bytes",
        SRC / "attachments.py",
        '''        if expected and not any(data.startswith(sig) for sig in expected):''',
        '''        if False:''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "the signature check refuses a type it has no signature for",
        SRC / "attachments.py",
        '''        if expected and not any(data.startswith(sig) for sig in expected):''',
        '''        if not any(data.startswith(sig) for sig in (expected or ())):''',
        "tests/test_attachments.py"),

    Mutation(
        "attachments", "the run state moves before the store is known to be readable",
        SRC / "server.py",
        '''            held, lost = self._read_attachments()
            self.state = RunState(state="running", version=self.state.version + 1,
                                  instructions=[instruction] if instruction else [])
            self.state.attachments, self.state.missing = held, lost''',
        '''            self.state = RunState(state="running", version=self.state.version + 1,
                                  instructions=[instruction] if instruction else [])
            self._refresh_attachments()''',
        "tests/test_server.py"),

    Mutation(
        "attachments", "a store directory the scanner reads as a red line is accepted at startup",
        SRC / "cli.py",
        '''    crosses = policy.derive([str(store.dir)])''',
        '''    crosses = ()''',
        "tests/test_cli.py"),
    # ── separators (CHG-20260905-03) ───────────────────────────────────────────────────────
    # `derive`'s boundaries are POSIX (`(^|/)`, `([\s/.:]|$)`), and this runner is Windows-first.
    # 8 of 9 path shapes answered differently in the two spellings, and `classify` returned None
    # for the native spelling of a production path. The union is what makes the fix unable to
    # subtract a detection; both halves are pinned here.
    Mutation(
        "separators", "the scanner goes back to reading one separator",
        SRC / "policy.py",
        '''    spellings = {haystack, haystack.replace(chr(92), "/")}''',
        '''    spellings = {haystack}''',
        "tests/test_policy.py"),

    Mutation(
        "separators", "normalisation replaces the raw haystack instead of joining it",
        SRC / "policy.py",
        '''    spellings = {haystack, haystack.replace(chr(92), "/")}''',
        '''    spellings = {haystack.replace("/", chr(92))}''',
        "tests/test_policy.py"),

    Mutation(
        "separators", "only the first spelling that matches is consulted",
        SRC / "policy.py",
        '''                 if any(re.search(pattern, one)
                        for one in spellings for pattern in _TARGET_RULES[kind]))''',
        '''                 if all(re.search(pattern, one)
                        for one in spellings for pattern in _TARGET_RULES[kind]))''',
        "tests/test_policy.py"),
    # ── doc-anchors (CHG-20260905-02) ──────────────────────────────────────────────────────
    # A document repair with nothing watching it is the defect this round was about, one file over.
    # Each entry reverts the sentence the change edited, in the document itself.
    Mutation(
        "doc-anchors", "D6.2 goes back to having one line binding it",
        REPO / "docs" / "changes" / "CHG-20260822-04.md",
        """2. **D6.2 - effect admissibility rule**: an operation may be an effect""",
        """2. **Effect admissibility rule**: an operation may be an effect""",
        "tests/test_documented_numbers.py"),

    Mutation(
        "doc-anchors", "a definition is any bold anywhere, not one that starts a line",
        REPO / "tests" / "test_documented_numbers.py",
        r'''    return set(re.findall(r"(?m)^\s*(?:\d+\.\s+)?\*\*(D\d+\.\d+)\b", text))''',
        r'''    return set(re.findall(r"\*\*(D\d+\.\d+)\b", text))''',
        "tests/test_documented_numbers.py"),

    Mutation(
        "doc-anchors", "the effects report row goes back to naming three of four fields",
        REPO / "docs" / "structure" / "data.md",
        """`frontier` (where the resume started), `already_met`, `applied`, `out_of_order`""",
        """`already_met`, `applied`, `out_of_order`""",
        "tests/test_documented_numbers.py"),
    # ── effects (CHG-20260905-01) ──────────────────────────────────────────────────────────
    # `effects.py` carried 0 of 238 registered mutations while `engine.py` carried 35 — the module
    # the crash-safety rests on, and the one D6 defines, with no revert check at all. Its 12 tests
    # were green against every finding the eleventh review round made.
    Mutation(
        "effects", "an unanswerable probe walks out of the process again",
        SRC / "effects.py",
        '''    try:
        return bool(effect.probe())
    except EffectError:
        raise
    except Exception as exc:''',
        '''    try:
        return bool(effect.probe())
    except EffectError:
        raise
    except ValueError as exc:''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "the halt stops naming which probe could not answer",
        SRC / "effects.py",
        '''            f"could not read whether {effect.name!r} is done "
            f"({effect.postcondition or 'no postcondition described'}): "
            f"{type(exc).__name__}: {exc}", outcome=outcome) from exc''',
        '''            "a probe could not be read", outcome=outcome) from exc''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "a halted sequence loses the record of what had already landed",
        SRC / "effects.py",
        '''            f"{type(exc).__name__}: {exc}", outcome=outcome) from exc''',
        '''            f"{type(exc).__name__}: {exc}") from exc''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "the false-green refusal loses the record of what had already landed",
        SRC / "effects.py",
        '''                f"design exists to prevent.", outcome=outcome)''',
        '''                f"design exists to prevent.")''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "a dry run stops reading past the frontier",
        SRC / "effects.py",
        '''    outcome.frontier = effects[start].name

    for position, effect in enumerate(effects[start:], start):''',
        '''    outcome.frontier = effects[start].name
    if dry_run:
        return outcome

    for position, effect in enumerate(effects[start:], start):''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "a dry run starts applying what it was only meant to look at",
        SRC / "effects.py",
        '''        if dry_run:
            continue
        effect.apply()''',
        '''        effect.apply()''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "the frontier is read a second time for an answer already in hand",
        SRC / "effects.py",
        '''        if position != start and _ask(effect, outcome):''',
        '''        if _ask(effect, outcome):''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "an out-of-order effect stops every effect after it",
        SRC / "effects.py",
        '''            outcome.out_of_order.append(effect.name)
            continue''',
        '''            outcome.out_of_order.append(effect.name)
            break''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "a probe that cannot be called with no arguments is admitted again",
        SRC / "effects.py",
        '''        if not _takes_no_arguments(self.probe):''',
        '''        if False:''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "the arity guard refuses what it merely cannot read",
        SRC / "effects.py",
        '''    except (TypeError, ValueError):
        return True''',
        '''    except (TypeError, ValueError):
        return False''',
        "tests/test_effects.py"),

    Mutation(
        "effects", "a halted node leaves no record of its effects in the run report",
        SRC / "engine.py",
        '''        if exc.outcome is not None:''',
        '''        if False:''',
        "tests/test_flow.py"),

    Mutation(
        "effects", "the frontier and what is out of causal order stop reaching a terminal",
        SRC / "cli.py",
        '''        if outcome.get("frontier"):''',
        '''        if False:''',
        "tests/test_cli.py"),
    Mutation(
        "importer", "the walk collapses same-named files across projects again",
        SRC / "conversations.py",
        '''    files = _inventory(root)''',
        '''    files = _inventory(root)
    files = list({r["name"]: r for r in files}.values())''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a refusal names the bare stem instead of the file",
        SRC / "conversations.py",
        '''            where = f"{record['project']}/{record['name']}" if record["project"] else record["name"]''',
        '''            where = str(record["name"]).split(".")[0]''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a broken target is blamed on the source conversation again",
        SRC / "conversations.py",
        '''        except (TargetError, OSError) as exc:''',
        '''        except (TargetError,) as exc:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "the collision comparison stops normalising the two sides",
        SRC / "conversations.py",
        '''    body = {k: v for k, v in turn.items() if k not in Turn.ENVELOPE}
    return (int(turn.get("seq", 0)), str(turn.get("kind") or ""), str(turn.get("at") or ""),
            json.dumps(body, ensure_ascii=False, sort_keys=True))''',
        '''    return (json.dumps(dict(turn), ensure_ascii=False, sort_keys=True),)''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a header naming a different project than its directory is accepted",
        SRC / "conversations.py",
        '''            if in_header != project:''',
        '''            if False:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "importer", "a filename disagreeing with its header's id is accepted",
        SRC / "conversations.py",
        '''            if name != f"{cid}.jsonl":''',
        '''            if False:''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "examples", "the agent runs in the operator's shell directory again",
        SRC / "cli.py",
        '''                                      cwd=self.cwd,''',
        '''                                      cwd=None,''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "examples", "agent_cwd stops defaulting to the config file's directory",
        SRC / "cli.py",
        '''    config_cwd = config.get("agent_cwd") or None''',
        '''    config_cwd = None''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "provenance", "the plan a run walked is recorded as the operator's keystrokes again",
        SRC / "cli.py",
        # Pinned to `cmd_run` by the journal line above it: `cmd_serve` builds the same
        # conversation and the bare line matched both (CHG-20260828-01).
        '''        args, journal_dir=args.ask_journal,
        run={"journal": str(Path(args.ask_journal).resolve()) if args.ask_journal else None,
             "plan": _where(args.plan)})''',
        '''        args, journal_dir=args.ask_journal,
        run={"journal": str(Path(args.ask_journal).resolve()) if args.ask_journal else None,
             "plan": str(args.plan)})''',
        "tests/test_run_provenance.py"),

    Mutation(
        "frontier", "an engineer reporting nothing left is discarded again",
        SRC / "engine.py",
        '''    if remaining and last_word == "":''',
        '''    if False:''',
        "tests/test_rerun_idempotence.py"),

    Mutation(
        "frontier", "a missing module key is read as 'nothing left'",
        SRC / "engine.py",
        '''        if "module" not in ask.result:''',
        '''        if False:''',
        "tests/test_rerun_idempotence.py"),

    Mutation(
        "routing", "an unrouted halt stops reaching the operator",
        SRC / "policy.py",
        '''    told.append(DEFAULT_RECIPIENT)
    return tuple(told)''',
        '''    return tuple(told)''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a kind nobody has heard of raises instead of falling back",
        SRC / "policy.py",
        '''    return DEFAULT_RECIPIENT, "default"''',
        '''    raise PolicyError(f"no route for {kind!r}")''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a kind with a typo in it is accepted at configuration time",
        SRC / "policy.py",
        '''    unknown = sorted(k for k in routing if k not in PERMANENT_HALT_KINDS)''',
        '''    unknown = []''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a project's own routing stops overriding the policy table",
        SRC / "policy.py",
        '''    if routing:
        named = str(routing.get(kind) or "").strip()''',
        '''    if False:
        named = str(routing.get(kind) or "").strip()''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "the owners stop being listed in the order their kinds were crossed",
        SRC / "policy.py",
        '''        if owner != DEFAULT_RECIPIENT and owner not in told:
            told.append(owner)''',
        '''        if owner != DEFAULT_RECIPIENT and owner not in told:
            told.insert(0, owner)''',
        "tests/test_halt_routing.py"),

    Mutation(
        "routing", "a halt stops recording who it was for",
        SRC / "engine.py",
        '''            report.halts.append({"node_id": node.id, "kinds": kinds,''',
        '''            [].append({"node_id": node.id, "kinds": kinds,''',
        "tests/test_halt_routing.py"),

    Mutation(
        "frontier", "an empty answer latches, foreclosing every later plan",
        SRC / "engine.py",
        '''            last_word = None
            continue''',
        '''            continue''',
        "tests/test_frontier_latch.py"),

    Mutation(
        "frontier", "an engineer reporting a failure is read as 'nothing left' again",
        SRC / "engine.py",
        '''        if not name and _went_wrong(ask.result):''',
        '''        if False:''',
        "tests/test_frontier_latch.py"),

    Mutation(
        "examples", "a --seat-model command is relocated into the config's directory again",
        SRC / "cli.py",
        # Re-anchored four times now: by CHG-20260828-02 after CHG-20260827-23 added
        # `risk`/`can_write`, again after CHG-20260827-21 moved the directory decision into
        # `_cwd_for`, again by CHG-20260901-18, which made the sandbox grade the grade **in force**
        # rather than the plan's proposal, and again by CHG-20260903-23, which named the process so
        # its sandbox tally could be handed over — `return _Process(` became `process = _Process(`
        # and the continuation lines shifted three columns.
        # Each time the staleness check added by CHG-20260828-02 caught it the same day, which is
        # the argument for that check rather than for remembering.
        '''                           timeout, retries, cwd=_cwd_for(workspace, from_config),
                           risk=grade or risk, can_write=_may_write(seat, role),''',
        '''                        timeout, retries, cwd=config_cwd,
                        risk=risk, can_write=_may_write(seat, role),''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "examples", "an explicit relative agent_cwd is left for the shell to resolve",
        SRC / "cli.py",
        '''    elif not Path(str(given)).is_absolute():
        config["agent_cwd"] = str((here / str(given)).resolve())''',
        '''    elif False:
        config["agent_cwd"] = str((here / str(given)).resolve())''',
        "tests/test_examples_run_from_anywhere.py"),

    Mutation(
        "importer", "one unreadable conversation in the target aborts the whole import again",
        SRC / "conversations.py",
        '''        except Exception as exc:
            named = ""''',
        '''        except Exception as exc:
            raise
            named = ""''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "risk", "gates read the proposed grade again, not the strictest candidate",
        SRC / "engine.py",
        '''        candidates = [cfg.risk] + list(report.risk_proposed.values()) + list(
            cfg.workstreams.values())
        return policy.strictest([c for c in candidates if c])''',
        '''        return cfg.risk''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a signed-off grade stops taking effect",
        SRC / "engine.py",
        '''    settled = report.risk_settled
    if not settled:''',
        '''    settled = report.risk_settled
    if True:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "one cautious voice can set the grade alone again",
        SRC / "policy.py",
        '''    if top * 2 > total:''',
        '''    if True:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a voice that answered something other than a grade is accepted",
        SRC / "policy.py",
        '''    unknown = sorted({g for g in grades.values() if g not in RISKS})''',
        '''    unknown = []''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "the grader stops having to be a panel",
        SRC / "graph.py",
        '''        if node.grades_risk and node.mode != MODEL_PANEL:''',
        '''        if False:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a work-producing step may be a panel again",
        SRC / "graph.py",
        '''        if node.mode == MODEL_PANEL and node.kind != DECISION and not node.grades_risk:''',
        '''        if False:''',
        "tests/test_risk_adjudicated.py"),

    Mutation(
        "risk", "a node in no workstream reads the loosest instead of the strictest",
        SRC / "engine.py",
        '''        return policy.strictest(list(cfg.workstreams.values()) + [settled])''',
        '''        return min(list(cfg.workstreams.values()) + [settled], key=policy.RISKS.index)''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a node stops reading its own workstream's grade",
        SRC / "engine.py",
        '''            grade = cfg.workstreams.get(named)
            if grade:
                return grade''',
        '''            grade = cfg.workstreams.get(named)
            if False:
                return grade''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "the operator's override stops overriding",
        SRC / "engine.py",
        '''    if cfg.risk_override:
        return cfg.risk_override''',
        '''    if False:
        return cfg.risk_override''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a workstream graded with a word that is not a grade is accepted",
        SRC / "plan.py",
        '''        if grade not in policy.RISKS:''',
        '''        if False:''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a node may point at a workstream nobody declared",
        SRC / "plan.py",
        # This anchor was unique when it was written. CHG-20260827-22 added a second
        # `if name not in workstreams:` — the interfaces guard — and silently made it ambiguous;
        # nothing reported that until CHG-20260828-01 added the check. Pinned by its own message.
        '''        if name not in workstreams:
            raise PlanError(
                f"{where} puts node {node_id!r} in workstream {name!r}''',
        '''        if False:
            raise PlanError(
                f"{where} puts node {node_id!r} in workstream {name!r}''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "a declared workstream may have no name",
        SRC / "plan.py",
        '''        if not str(name).strip():''',
        '''        if False:''',
        "tests/test_workstream_risk.py"),

    Mutation(
        "risk", "the plan's workstreams stop reaching the run",
        SRC / "cli.py",
        # Pinned to `cmd_run`: `cmd_serve` builds the same RunConfig, and mutating the console path
        # would leave the tested path working while the run printed CAUGHT (CHG-20260828-01).
        '''        workstreams=plan.get("workstreams") or {},
        node_workstream=plan.get("node_workstream") or {},
        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        '''        workstreams={},
        node_workstream=plan.get("node_workstream") or {},
        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        "tests/test_workstream_risk.py"),

    Mutation(
        # The guarantee CHG-20260903-30 added, mutated the way the seven beside it are: not by
        # deleting the check but by emptying what it checks against, which is how a blocklist
        # actually stops working. `wrap` still runs, the profile is still assembled, and a path
        # that ends the string literal early is written straight into it.
        "sandbox", "a filename can rewrite the seatbelt policy again",
        SRC / "sandbox.py",
        """UNREPRESENTABLE_IN_SBPL = '"'""",
        """UNREPRESENTABLE_IN_SBPL = ''""",
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "a role that may not write gets a pen again",
        SRC / "policy.py",
        '''    if not can_write:
        policy_for_grade["write"] = "none"''',
        '''    if False:
        policy_for_grade["write"] = "none"''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "a high grade binds the workspace writable",
        SRC / "sandbox.py",
        '''    if wanted["write"] == "workspace":
        out += ["--bind", root, root]''',
        '''    if True:
        out += ["--bind", root, root]''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the network is never denied",
        SRC / "sandbox.py",
        '''    if not wanted["network"]:
        out += ["--unshare-net"]''',
        '''    if False:
        out += ["--unshare-net"]''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "an unenforceable sandbox is reported as enforced",
        SRC / "sandbox.py",
        '''        return list(argv), {**wanted, "mechanism": None, "enforced": False}''',
        '''        return list(argv), {**wanted, "mechanism": None, "enforced": True}''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "asking for a sandbox the machine cannot give proceeds anyway",
        SRC / "sandbox.py",
        '''        if required:
            raise SandboxError(''',
        '''        if False:
            raise SandboxError(''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the platform stops deciding which mechanism is used",
        SRC / "sandbox.py",
        '''        if not running.startswith(needs_platform):
            continue''',
        '''        if False:
            continue''',
        "tests/test_sandbox.py"),

    Mutation(
        "sandbox", "the dispatched process stops being told the role's capability",
        SRC / "cli.py",
        '''        named = policy.BY_ROLE.get(role or "")''',
        '''        named = None''',
        "tests/test_sandbox.py"),

    Mutation(
        "planning", 'a programme with several workstreams is planned as one',
        SRC / 'engine.py',
        '    return "split" if len(cfg.workstreams or {}) > 1 else "single"',
        '    return "single"',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the run gets to answer the scope question itself',
        SRC / 'engine.py',
        '    if node.id == "plan_scope":',
        '    if node.id == "plan_scope" and value is None:',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'interfaces are compared by signature instead of by name',
        SRC / 'engine.py',
        '            seen.setdefault(label, {})[workstream] = signature',
        '            seen.setdefault(signature, {})[workstream] = signature',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'a conflict is reported as agreement',
        SRC / 'engine.py',
        '    found = conflicts(cfg.interfaces)\n    if not found:\n        return "agree"',
        '    found = conflicts(cfg.interfaces)\n    if True:\n        return "agree"',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'an unresolvable conflict cycles instead of halting',
        SRC / 'engine.py',
        '    if all(note in report.dispatches for note in notes):',
        '    if False:',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the plan may declare interfaces for a workstream nobody declared',
        SRC / 'plan.py',
        '        if name not in workstreams:\n            raise PlanError(\n                f"{where} declares interfaces for workstream {name!r}',
        '        if False:\n            raise PlanError(\n                f"{where} declares interfaces for workstream {name!r}',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the declared interfaces never reach the run',
        SRC / 'cli.py',
        # Re-anchored (CHG-20260828-02): CHG-20260827-20 inserted `change_class=` between these two
        # lines the same day this was written, and nothing said so. Pinned to `cmd_run` by the
        # comment that follows only there.
        '''        interfaces=plan.get("interfaces") or {},
        # From the command line and nowhere else''',
        '''        interfaces={},
        # From the command line and nowhere else''',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'the dispatch tree is no longer bounded on a run',
        SRC / 'engine.py',
        '    policy.check_dispatch_depth(graph.dispatch_edges(), graph.roles_asked_directly())',
        '    pass',
        'tests/test_sub_planning.py'),

    Mutation(
        "planning", 'a halt reports itself as a normal finish again',
        SRC / 'engine.py',
        '            report.state = STOPPED if node.permanent else FINISHED',
        '            report.state = FINISHED',
        'tests/test_sub_planning.py'),

    Mutation(
        "classes", 'a class dissolves a halt, not only a confirm',
        SRC / 'policy.py',
        '    if not named.relaxes or graded != CONFIRM:',
        '    if not named.relaxes:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", '`normal` starts relaxing gates',
        SRC / 'policy.py',
        '    ChangeClass("normal", relaxes=False, reviewed_after=False,',
        '    ChangeClass("normal", relaxes=True, reviewed_after=False,',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a class never expires',
        SRC / 'policy.py',
        '    if review_by < today:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", "a pre-authorisation needs nobody's signature",
        SRC / 'policy.py',
        '    if not who:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a class may be declared with no review date',
        SRC / 'policy.py',
        '    if not review_by:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the class stops reaching the gate',
        SRC / 'engine.py',
        '    return policy.verdict(node.gate, risk, autonomy, change_class)',
        '    return policy.verdict(node.gate, risk, autonomy)',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'a plan may class itself again',
        SRC / 'plan.py',
        '    classing = sorted(set(unknown) & {"change_class", "class", "pre_authorised", "standard"})',
        '    classing = []',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the command line accepts a class with parts missing',
        SRC / 'cli.py',
        '    if len(parts) != 3 or not all(p.strip() for p in parts):',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'an unknown class is guessed at instead of refused',
        SRC / 'cli.py',
        '    if name not in policy.BY_CLASS:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        "classes", 'the run stops recording which class let it through',
        SRC / 'engine.py',
        '    report.change_class = why',
        '    report.change_class = ""',
        'tests/test_change_classes.py'),

    Mutation(
        'guards', 'an acceptance for a change that does not exist is accepted again',
        TOOLS / 'ledger_check.py',
        '        if suffix not in known:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'an acceptance filed against the wrong change stops being noticed',
        TOOLS / 'ledger_check.py',
        '        if stated and stated != f"CHG-{suffix}":',
        '        if False:',
        'tests/test_ledger_check.py'),

    # ── CHG-20260828-16: the codec is named, not inherited from whoever ran the process ────────
    #
    # These revert one call site each. A revert that only removed the keyword from `ledger_check`
    # would prove the guard test reads that one file; reverting in `cli` as well proves it reads
    # the tree rather than a remembered list of paths.

    Mutation(
        'codecs', "the id-collision guard decodes git with the caller's locale again",
        TOOLS / 'ledger_check.py',
        '''        done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(repo),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)''',
        '''        done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(repo),
                              capture_output=True, text=True, timeout=60)''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', "an agent's reply is decoded with the caller's locale again",
        SRC / 'cli.py',
        '                                      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=self.timeout,',
        '                                      capture_output=True, text=True, timeout=self.timeout,',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the agent picks its own codec for the order it is sent',
        SRC / 'cli.py',
        '                                      env={**os.environ, "PYTHONIOENCODING": "utf-8"})',
        '                                      env=None)',
        'tests/test_cli.py'),

    Mutation(
        'codecs', 'a stray byte can kill the reader thread again, silently',
        SRC / 'worktree.py',
        '        return self._run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)',
        '        return self._run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the recorder reads UTF-8 without asking the child to write it',
        TOOLS / 'session_record.py',
        '    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")',
        '    env = dict(os.environ, PYTHONUNBUFFERED="1")',
        'tests/test_recording.py'),

    Mutation(
        'codecs', 'the rule matches a keyword spelled `text` rather than a process launch',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '        if keywords & TEXT_SWITCHES and keywords & PROCESS_KEYWORDS:',
        '        if keywords & TEXT_SWITCHES:',
        'tests/test_subprocess_codecs.py'),

    # ── CHG-20260830-04: the probes underneath the sequence ────────────────────────────────────
    #
    # CHG-20260830-03 reserved this: every effect in `ship` delegates its probe here, so a probe
    # that answers wrongly defeats all of that from underneath. The failure mode is not "it breaks"
    # — it is "it answers", when it could not find out.

    Mutation(
        'probes', 'an unreachable remote is reported as "not pushed"',
        SRC / 'probes.py',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, ref], cwd=repo)
    if proc.returncode != 0:''',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, ref], cwd=repo)
    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'the push probe reads a local ref, which is stale in both directions',
        SRC / 'probes.py',
        '''    proc = _run(["git", "ls-remote", "--heads", remote, ref], cwd=repo)''',
        '''    proc = _run(["git", "rev-parse", "--verify", f"refs/remotes/{remote}/{branch}"], cwd=repo)''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a remote that answers with more than one ref is guessed at',
        SRC / 'probes.py',
        '''    if len(rows) > 1:''',
        '''    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a remote holding a branch this repository lacks is answered rather than refused',
        SRC / 'probes.py',
        '''    local = _run(["git", "rev-parse", "--verify", ref], cwd=repo)
    if local.returncode != 0:''',
        '''    local = _run(["git", "rev-parse", "--verify", ref], cwd=repo)
    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'an unreachable forge is reported as an absent PR',
        SRC / 'probes.py',
        '''    proc = _run([*argv, "--head", branch], cwd=repo)
    if proc.returncode != 0:''',
        '''    proc = _run([*argv, "--head", branch], cwd=repo)
    if False:''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a CHG id is treated as a regular expression when searching commits',
        SRC / 'probes.py',
        '''    argv = ["git", "log", "--fixed-strings", f"--grep={needle}", "--format=%s"]''',
        '''    argv = ["git", "log", f"--grep={needle}", "--format=%s"]''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a commit that merely cites an id counts as that change\'s commit again',
        SRC / 'probes.py',
        '''    return any(needle in subject for subject in proc.stdout.splitlines())''',
        '''    return bool(proc.stdout.strip())''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'the push probe goes back to asking whether a branch of that name exists',
        SRC / 'probes.py',
        '''    return parts[0] == local.stdout.strip()''',
        '''    return True''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a failed git log answers "no commit" instead of refusing',
        SRC / 'probes.py',
        '''        raise ProbeError(f"git log failed in {repo}: {proc.stderr.strip()}")''',
        '''        return False''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a failed git status answers "clean" instead of refusing',
        SRC / 'probes.py',
        '''        raise ProbeError(f"git status failed in {repo}: {proc.stderr.strip()}")''',
        '''        return True''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a missing binary answers instead of saying it is not there',
        SRC / 'probes.py',
        '''        raise ProbeError(f"{argv[0]!r} is not available: {paths.plain_in(str(exc))}") from None''',
        '''        return subprocess.CompletedProcess(argv, 0, "", "")''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a probe that timed out answers instead of saying so',
        SRC / 'probes.py',
        '''        raise ProbeError(f"{' '.join(argv)} timed out after {timeout}s: {exc}") from None''',
        '''        return subprocess.CompletedProcess(argv, 0, "", "")''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'a half-written CHG with no Branch reads as intent recorded',
        SRC / 'probes.py',
        '''    return bool(re.search(r"^\\s*-?\\s*Branch\\s*[:：]", text, re.MULTILINE))''',
        '''    return True''',
        'tests/test_probes.py'),

    Mutation(
        'probes', 'an unticked task reads as ticked',
        SRC / 'probes.py',
        '''        if task in line and re.search(r"\\[\\s*[xX]\\s*\\]|\\*\\*\\[\\s*[xX]\\s*\\]\\*\\*", line):''',
        '''        if task in line:''',
        'tests/test_probes.py'),

    # ── CHG-20260830-03: the sequence that carries a change out ────────────────────────────────
    #
    # `ship.py` is the only module whose effects reach outside this machine, and the only one whose
    # steps are irreversible in the ordinary case. Measured with the harness against the file that
    # drives the sequence end to end.

    Mutation(
        'ship', 'a git command that failed is treated as having worked',
        SRC / 'ship.py',
        '    if proc.returncode != 0:\n        raise ShipError(f"git',
        '    if False:\n        raise ShipError(f"git',
        'tests/test_ship_refuses.py'),

    Mutation(
        # A real reorder, not a rename. The first version changed `name="record-intent"` to
        # `name="zzz-record-intent"` and reported CAUGHT — because the test compares effect names
        # literally, not because anything moved. Renaming an entry does not reorder a list, so the
        # guarantee this row names had no mutation at all until the review panel said so
        # (CHG-20260830-05).
        'ship', 'the intent is recorded after the effects it describes, not before',
        SRC / 'ship.py',
        '''    return [
        effects.Effect(
            name="record-intent",
            probe=lambda: probes.chg_recorded(repo, chg_id),
            apply=write_chg,
            postcondition=f"docs/changes/{chg_id}.md exists and names its Branch",
        ),
        effects.Effect(
            name="branch",
            probe=lambda: probes.branch_exists_locally(repo, branch),
            apply=lambda: _git(repo, "checkout", "-b", branch),
            postcondition=f"refs/heads/{branch} exists",
        ),''',
        '''    return [
        effects.Effect(
            name="branch",
            probe=lambda: probes.branch_exists_locally(repo, branch),
            apply=lambda: _git(repo, "checkout", "-b", branch),
            postcondition=f"refs/heads/{branch} exists",
        ),
        effects.Effect(
            name="record-intent",
            probe=lambda: probes.chg_recorded(repo, chg_id),
            apply=write_chg,
            postcondition=f"docs/changes/{chg_id}.md exists and names its Branch",
        ),''',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'a commit over a dirty tree counts as done, so a resume pushes half of it',
        SRC / 'ship.py',
        '            probe=lambda: (probes.commit_exists_for(repo, chg_id)\n                           and probes.working_tree_clean(repo)),',
        '            probe=lambda: probes.commit_exists_for(repo, chg_id),',
        'tests/test_ship_refuses.py'),

    Mutation(
        'ship', 'the PR step stops asking whether a PR is already open',
        SRC / 'ship.py',
        '            probe=lambda: probes.pr_open_for(repo, branch, gh_list),',
        '            probe=lambda: False,',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'the push step stops asking whether the branch is already on the remote',
        SRC / 'ship.py',
        '            probe=lambda: probes.branch_on_remote(repo, branch, remote),',
        '            probe=lambda: False,',
        'tests/test_kill_resume.py'),

    Mutation(
        'ship', 'the runner invents the content of a governance record nobody supplied',
        SRC / 'ship.py',
        '''            apply=tick or _refuse("tick", f"task {task!r} of {chg_id}"),''',
        '''            apply=tick or (lambda: None),''',
        'tests/test_ship_refuses.py'),

    Mutation(
        'ship', 'a failed PR creation is reported as success',
        SRC / 'ship.py',
        '''        raise ShipError(f"could not open a PR for {branch}: {proc.stderr.strip()}")''',
        '''        pass''',
        'tests/test_ship_refuses.py'),

    # ── CHG-20260830-02: where a model is, and what it must not carry ──────────────────────────
    #
    # `reach` decides whether a work order leaves this network, and `validate` decides whether a key
    # can end up in a file. Measured with the harness, pointed at the existing tests.

    Mutation(
        'reach', 'reach becomes something the operator declares rather than something computed',
        SRC / 'models.py',
        '    if transport == CLI:\n        return LOCAL',
        '    if transport == CLI:\n        return EXTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a name nobody can resolve is called internal, the generous way to be wrong',
        SRC / 'models.py',
        '        if graded_by_guess(endpoint) or host.endswith(LOCAL_SUFFIXES):\n            return INTERNAL',
        '        return INTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a private address is called external, so an internal model looks like a leak',
        SRC / 'models.py',
        '    if address.is_private or address.is_link_local:\n        return INTERNAL',
        '    if False:\n        return INTERNAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'loopback stops being local',
        SRC / 'models.py',
        '    if address.is_loopback:\n        return LOCAL',
        '    if False:\n        return LOCAL',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an api model with no endpoint gets a reach guessed for it',
        SRC / 'models.py',
        '''        raise ModelError("an api model needs an endpoint before its reach can be known")''',
        '''        return EXTERNAL''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a secret in the query string is accepted into the registry',
        SRC / 'models.py',
        '    leaked = _secret_in_url(model.endpoint)\n    if leaked:',
        '    leaked = _secret_in_url(model.endpoint)\n    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'the secret scan reads the value instead of the key, so ?api_key= passes',
        SRC / 'models.py',
        '        name = pair.split("=", 1)[0].strip().lower()',
        '        name = pair.split("=", 1)[-1].strip().lower()',
        'tests/test_models.py'),

    Mutation(
        'reach', 'key_env takes the key itself, so it reaches a file and a git history',
        SRC / 'models.py',
        '    if model.key_env and not _ENV_NAME.match(model.key_env):',
        '    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'a public endpoint with no key named is registered anyway',
        SRC / 'models.py',
        '    if model.reach == EXTERNAL and not model.key_env:',
        '    if False:',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an endpoint scheme this runner does not speak is accepted',
        SRC / 'models.py',
        '''    if scheme not in ("http", "https"):''',
        '''    if False:''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'an api model may carry a command it cannot use',
        SRC / 'models.py',
        '''        raise ModelError(f"api model {model.id!r} carries a command it cannot use")''',
        '''        pass''',
        'tests/test_models.py'),

    Mutation(
        'reach', 'two models may share one id',
        SRC / 'models.py',
        '''                raise ModelError(f"two models are called {model.id!r}")''',
        '''                pass''',
        'tests/test_models.py'),

    # ── CHG-20260830-01: the console's network boundary ────────────────────────────────────────
    #
    # `_guard` is the only thing between a local HTTP server holding an operator token and whatever
    # else is running on the machine. Measured the way CHG-20260828-24's acceptance said it should
    # have been: pointed at the existing test file, and the ones that come back NOT CAUGHT are the
    # holes — no second instrument.

    Mutation(
        'console', 'a non-loopback Host reaches the router, so DNS rebinding works again',
        SRC / 'server.py',
        '            if not _loopback_host(self.headers.get("Host")):',
        # `if False:`, which lets the request through — what the description says. `if True:` refuses
        # **every** request including loopback, so the console is bricked and this reports CAUGHT off
        # 28 failures about anything else; deleting every rebinding test left the group green. It was
        # flipped here by a `replace(..., 1)` that matched the wrong occurrence while repointing a
        # different mutation (CHG-20260831-06, conformance seat VETO and idiom seat).
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'the shell is served to any Host at all',
        SRC / 'server.py',
        '                return _loopback_host(self.headers.get("Host")) or self._refuse_host()',
        '                return True',
        'tests/test_server.py'),

    Mutation(
        'console', 'a cross-origin request is answered',
        SRC / 'server.py',
        '            if origin and not _loopback_origin(origin):',
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'no operator token is needed',
        SRC / 'server.py',
        '            if not operator.accepts(presented):',
        '            if False:',
        'tests/test_server.py'),

    Mutation(
        'console', 'the token is compared with `==`, leaking its prefix by timing',
        SRC / 'server.py',
        '        return bool(presented) and secrets.compare_digest(presented, self.token)',
        '        return bool(presented) and presented == self.token',
        'tests/test_server.py'),

    Mutation(
        'console', 'every route takes the token from the query string, not only the stream',
        SRC / 'server.py',
        '            if presented is None and urlsplit(self.path).path == "/run/events":',
        '            if presented is None:',
        'tests/test_server.py'),

    Mutation(
        'console', 'a Host with a port stops matching, so the console refuses itself',
        SRC / 'server.py',
        '        host = host.rsplit(":", 1)[0]',
        '        host = host',
        'tests/test_server.py'),

    Mutation(
        'console', 'a body that is not JSON comes back as a traceback',
        SRC / 'server.py',
        '            except ValueError as exc:\n                raise ServerError(f"the request body is not JSON: {exc}")',
        '            except TypeError as exc:\n                raise ServerError(f"the request body is not JSON: {exc}")',
        'tests/test_server.py'),

    # ── CHG-20260828-24: the model store ───────────────────────────────────────────────────────
    #
    # Measured before writing: nine of ten were already pinned. The tenth was not, and writing its
    # test found the guarantee was not delivered at all — which is why this group also mutates
    # `paths.py` below.
    #
    # This comment used to say "TEN OF TEN were already pinned. No hole was found." That was the
    # figure a discarded probe reported; the harness said nine and was right, and CHG-20260828-24's
    # own acceptance records the correction. The records were updated and this line was not, so the
    # permanent registry stated the opposite of the change it heads — the review panel's conformance
    # seat vetoed on it (CHG-20260830-05).

    Mutation(
        'store', 'a file that is not a database comes back as a raw traceback',
        SRC / 'store.py',
        '''    except sqlite3.DatabaseError as exc:
        # A file that is not a database''',
        '''    except NotImplementedError as exc:
        # A file that is not a database''',
        'tests/test_store.py'),

    Mutation(
        'store', 'the extended-length prefix reaches the operator in the message',
        SRC / 'store.py',
        'f"{file} could not be opened as a store: {paths.plain_in(str(exc))}. If it is a real "',
        'f"{file} could not be opened as a store: {exc}. If it is a real "',
        'tests/test_store.py'),

    Mutation(
        # The defect this group found. `plain` strips a LEADING prefix; an OS error quotes a
        # path mid-sentence, so the guard was a no-op wearing the name of the thing it did not do.
        'store', 'the prefix is stripped only from the start again, so a message keeps it',
        SRC / 'paths.py',
        # A raw triple-quote. The escaped one-line form this shipped as put sixteen consecutive
        # backslashes on a 214-character line, which nobody can check against source by eye — an
        # unverifiable anchor in the file whose meta-test exists to keep anchors honest. The `r`
        # prefix is new here; the plain `'''` multi-line form is not (`store.py`'s anchor, 18 lines
        # above). CHG-20260830-06 cited it as precedent for the raw form, which it is not.
        r'''    return (text
            .replace(_DOUBLED_UNC_PREFIX, "\\\\\\\\")
            .replace(_DOUBLED_PREFIX, "")
            .replace(UNC_PREFIX, "\\\\")
            .replace(PREFIX, ""))''',
        '    return plain(text)',
        'tests/test_paths.py'),

    Mutation(
        # The defect the REVIEW PANEL found. Only the undoubled spelling was handled — and the
        # undoubled spelling is the one no real error carries, because `str(OSError)` embeds
        # `repr(filename)` and doubles every backslash (CHG-20260830-05).
        'store', 'only the spelling a real OS error never uses is stripped',
        SRC / 'paths.py',
        r'''            .replace(_DOUBLED_UNC_PREFIX, "\\\\\\\\")
            .replace(_DOUBLED_PREFIX, "")
''',
        '',
        'tests/test_paths.py'),

    Mutation(
        'store', r'a UNC path is left as UNC\server\share, which is not a path anybody can use',
        SRC / 'paths.py',
        r'''            .replace(UNC_PREFIX, "\\\\")
            .replace(PREFIX, ""))''',
        r'''            .replace(PREFIX, "")
            .replace(UNC_PREFIX, "\\\\"))''',
        'tests/test_paths.py'),

    Mutation(
        'store', 'a store from a newer schema is opened and written anyway',
        SRC / 'store.py',
        '    if found > SCHEMA_VERSION:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'a table already there with the wrong columns is blessed as current',
        SRC / 'store.py',
        '        if found != columns:',
        '        if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'foreign keys stay off, so a delete can orphan an assignment',
        SRC / 'store.py',
        'db.execute("PRAGMA foreign_keys = ON")',
        'db.execute("PRAGMA foreign_keys = OFF")',
        'tests/test_store.py'),

    Mutation(
        'store', 'a node that is not in this flow can be assigned models',
        SRC / 'store.py',
        '''    if node is None:
        raise StoreError(f"no node {node_id!r} in this flow")''',
        '''    if False:
        raise StoreError(f"no node {node_id!r} in this flow")''',
        'tests/test_store.py'),

    Mutation(
        'store', 'a node whose mode does nothing with models is configured anyway',
        SRC / 'store.py',
        '    if node.mode not in MODES_THAT_USE_MODELS:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', 'an unknown seat is assigned a model',
        SRC / 'store.py',
        '    if seat not in known:',
        '    if False:',
        'tests/test_store.py'),

    Mutation(
        'store', "the standing store setting overrides this change's plan",
        SRC / 'store.py',
        '        combined = {**from_store, **from_plan}          # plan last, so the plan wins',
        '        combined = {**from_plan, **from_store}          # plan last, so the plan wins',
        'tests/test_store.py'),

    Mutation(
        'store', 'nobody can tell which source put an assignment there',
        SRC / 'store.py',
        '            source[f"{half}.{key}"] = FROM_PLAN if key in from_plan else FROM_STORE',
        '            source[f"{half}.{key}"] = FROM_STORE',
        'tests/test_store.py'),

    # ── CHG-20260828-23: the closed-schema renderer, pinned deliberately ───────────────────────
    #
    # `workorder.py` had no mutation and no test file of its own. Measured before writing either:
    # seven of these nine were already caught by tests written about other things. The last two
    # were not — and the source marks one of them `# pragma: no cover`, which is the code admitting
    # nothing exercised it.

    Mutation(
        'workorder', 'a harness-specific field rides in through the caller',
        SRC / 'workorder.py',
        '    if extra:', '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a partial node spec is filled in rather than refused',
        SRC / 'workorder.py',
        '    if missing:', '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'whitespace stops counting as blank',
        SRC / 'workorder.py',
        '        return not value.strip()', '        return not value',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a list holding only blanks passes as content',
        SRC / 'workorder.py',
        '        return not value or all(_blank(item) for item in value)',
        '        return not value',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'a blank field is accepted again, as long as the key exists',
        SRC / 'workorder.py',
        '''    if problem:
        raise WorkOrderError(problem)''',
        '''    if False:
        raise WorkOrderError(problem)''',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'an unknown seat is accepted',
        SRC / 'workorder.py',
        '        if chair is None:', '        if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'the permanent halts are emptied out of the order',
        SRC / 'workorder.py',
        '        "permanent_halts": list(policy.PERMANENT_HALTS),',
        '        "permanent_halts": [],',
        'tests/test_workorder.py'),

    # The two nothing pinned.
    Mutation(
        'workorder', 'the rendered order stops being checked against the closed schema',
        SRC / 'workorder.py',
        '    if tuple(sorted(order)) != tuple(sorted(WORK_ORDER_FIELDS)):',
        '    if False:',
        'tests/test_workorder.py'),

    Mutation(
        'workorder', 'the order reaches the agent in whatever key order it happened to have',
        SRC / 'workorder.py',
        'sort_keys=True', 'sort_keys=False',
        'tests/test_workorder.py'),

    # ── CHG-20260828-22: the whole-change loop is bounded ──────────────────────────────────────

    Mutation(
        'bounds', 'a rejected change goes round for ever again, until the step cap',
        SRC / 'engine.py',
        '''    if node.id == "change_retry":''',
        '''    if False:''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the panel and acceptance get a budget each, so neither is ever spent',
        SRC / 'engine.py',
        '''    return tuple(node.id for node in graph.NODES if node.next == "change_retry")''',
        '''    return ("review_failed",)''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the bound fires on the first rejection instead of the second',
        SRC / 'engine.py',
        '''    return "again" if rejections > 1 else "first"''',
        '''    return "again" if rejections > 0 else "first"''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'a seat panel counts once per seat again, so three seats halt a first rejection',
        SRC / 'engine.py',
        '''    rejections = sum(1 for node_id in report.visited if node_id in _whole_change_rejected())''',
        '''    rejections = sum(1 for ask in report.asks if ask.node_id in ("lead_review", "qa_accept")
                     and isinstance(ask.result, Mapping)
                     and str(ask.result.get("verdict") or "") == "fail")''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'acceptance stops routing through the bound, leaving its loop unbounded',
        SRC / 'graph.py',
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="change_retry", mode=RUNNER),''',
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="next_module", mode=RUNNER),''',
        'tests/test_change_bound.py'),

    Mutation(
        'bounds', 'the halt is not permanent, so a class or a confirmation could pass it',
        SRC / 'graph.py',
        '''    Node("halt_change_rejected", TERMINAL, "the whole change was rejected twice", mode=RUNNER,
         permanent=True,''',
        '''    Node("halt_change_rejected", TERMINAL, "the whole change was rejected twice", mode=RUNNER,
         permanent=False,''',
        'tests/test_change_bound.py'),

    # ── CHG-20260828-21: an emergency run is chased ────────────────────────────────────────────
    #
    # The failure that matters here is a FALSE CLOSE — a run marked reviewed by something that is
    # not a person, or by reviewing something that never needed it. Those three refusals get one
    # mutation each; the queue merely being wrong is the milder half.

    Mutation(
        'emergency', 'a review signed by nobody closes the obligation',
        SRC / 'conversations.py',
        '''    if not who:
        raise ConversationError(
            "a review must name who did it.''',
        '''    if False:
        raise ConversationError(
            "a review must name who did it.''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'the queue empties by reviewing any run at all',
        SRC / 'conversations.py',
        '    run = runs.get(cid)',
        '    run = runs.get(cid) or {"conversation_id": cid, "project_id": "", "reviewed_by": None}',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'a second review is written over the first, losing who looked',
        SRC / 'conversations.py',
        '''    if run["reviewed_by"]:''',
        '''    if False:''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'the word emergency anywhere queues a run again',
        SRC / 'conversations.py',
        '''    return "'emergency'" in str(turn.get("change_class") or "")''',
        '''    return "emergency" in str(turn)''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'a reviewed run stays in the queue, so the queue never empties',
        SRC / 'conversations.py',
        '''    return [run for run in emergency_runs(back, pid) if not run["reviewed_by"]]''',
        '''    return list(emergency_runs(back, pid))''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', "a person's review is filed under the runner in the export",
        SRC / 'conversations.py',
        '''    REVIEW: ("operator", "reviewed"),''',
        '''    NOTE: ("runner", "noted"),''',
        'tests/test_emergency_queue.py'),

    Mutation(
        'emergency', 'nothing chases the queue after a run again',
        SRC / 'cli.py',
        '''    _chase_emergencies(args)
    return 0''',
        '''    return 0''',
        'tests/test_emergency_queue.py'),

    # ── CHG-20260828-20: a record's evidence has to be findable ────────────────────────────────

    Mutation(
        'closure', 'a record can name a test that does not exist again',
        TOOLS / 'ledger_check.py',
        '                  if name not in known and not _excused(text, name, ledger_ids, known)]',
        '                  if False]',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the excuse stops being bounded, so any removal note launders a ghost',
        TOOLS / 'ledger_check.py',
        # The **whole** condition, both lines. Anchoring the first line alone orphaned the
        # continuation, so the mutated file raised `SyntaxError: unmatched ')'`, every test in the
        # module died on import, and this reported CAUGHT while proving only that the file
        # compiles — now held by `test_no_shipped_mutation_makes_its_file_unparsable`
        # (CHG-20260831-06, all four seats; the paragraph was pasted twice and the two copies
        # disagreed, corrected in CHG-20260831-07).
        #
        # `if True:` and not `if False:`, because over-excusing is what `says` describes.
        '            if (names in ledger_ids and len(said) <= EXCUSE_WINDOW\n'
        '                    and not _PARAGRAPH_BREAK.search(said)):',
        '            if True:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the evidence check is written but never run by the ledger',
        TOOLS / 'ledger_check.py',
        '    problems.extend(check_named_tests_exist(repo))',
        '    pass',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'naming a test module stops counting, so every file reference is a ghost',
        TOOLS / 'ledger_check.py',
        '        names.add(path.stem)',
        '        pass',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'the rule reaches back over history it cannot change',
        TOOLS / 'ledger_check.py',
        '        if stamp < TESTS_MUST_EXIST_FROM:',
        '        if False:',
        'tests/test_ledger_check.py'),

    # ── CHG-20260828-19: the file half of the same question ───────────────────────────

    Mutation(
        # The helper the file survey EXEMPTS. Most file I/O here goes through it, so if its default
        # stopped naming a codec the survey would go on quietly exempting it — the exemption is
        # load-bearing and had nothing checking it until this mutation had nowhere else to land.
        'codecs', 'the file helper the survey trusts stops defaulting to utf-8',
        SRC / 'paths.py',
        '''def read_text(path: str | Path, encoding: str = "utf-8") -> str:''',
        '''def read_text(path: str | Path, encoding: str = None) -> str:''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'going through `paths` stops counting as naming a codec',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '''CODEC_BY_DEFAULT = "paths"''',
        '''CODEC_BY_DEFAULT = "not-paths"''',
        'tests/test_subprocess_codecs.py'),

    Mutation(
        'codecs', 'the file survey stops looking at bare open() as well',
        REPO / 'tests' / 'test_subprocess_codecs.py',
        '        if name == "open" and receiver not in (None, "io"):',
        '        if name == "open":',
        'tests/test_subprocess_codecs.py'),

    # ── CHG-20260828-18: a killed run does not leave the tree mutated ──────────────────
    #
    # Every one of these anchors into `mutation_recovery.py` rather than into this file. A
    # mutation's `before` string lives HERE, so an anchor into this file appears twice and the
    # uniqueness guard refuses it — which is why the recovery is next door.

    Mutation(
        # Was "two runs in one worktree overwrite each other's way back" — which this pins only
        # half of, and the half it does not pin was broken. See CHG-20260830-06 below.
        'stranded', 'a record already on disk is overwritten instead of refused',
        TOOLS / 'mutation_recovery.py',
        r'''        with io.open(IN_FLIGHT, "x", encoding="utf-8", newline="\n") as handle:''',
        r'''        with io.open(IN_FLIGHT, "w", encoding="utf-8", newline="\n") as handle:''',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'a file a killed run left mutated stays mutated',
        TOOLS / 'mutation_recovery.py',
        '    if not IN_FLIGHT.exists():',
        '    if True:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the mutation is applied before it is recorded, so the window reopens',
        TOOLS / 'mutation_recovery.py',
        """    begin(path, original, mutated)
    write(path, mutated)""",
        """    write(path, mutated)
    begin(path, original, mutated)""",
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'recovery overwrites a file somebody has edited since the run died',
        TOOLS / 'mutation_recovery.py',
        '    if now == mutated:',
        '    if now != original:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the in-flight record outlives the run that wrote it',
        TOOLS / 'mutation_recovery.py',
        """    write(path, original)
    end()""",
        """    write(path, original)""",
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260830-06: exclusive creation was not the lock ───────────────────────────────────
    #
    # The entry above says two runs cannot overwrite each other's way back, and for one round that
    # was false while its mutation came back CAUGHT: `main()` calls `recover()` before its first
    # `apply()`, so the second run cleared the first one's record on the way in and never reached
    # the exclusive create. The test carrying the claim called `begin` twice in one process — the
    # path no real second run takes. Three seats of the CHG-20260830-05 panel found it, one by veto.

    Mutation(
        'stranded', 'a second run recovers over a live run and reports on unmutated source',
        TOOLS / 'mutation_recovery.py',
        '    if owner != os.getpid() and _alive(owner):',
        '    if False:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'a finishing run deletes a record another run is relying on',
        TOOLS / 'mutation_recovery.py',
        '    if owner is not None and owner != os.getpid():',
        '    if False:',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'every process reads as dead, so the owner check never refuses anything',
        TOOLS / 'mutation_recovery.py',
        """    return _alive_nt(pid) if os.name == "nt" else _alive_posix(pid)""",
        """    return False""",
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260830-07: the liveness probe answered wrongly three ways ────────────────────────
    #
    # The owner check above is only as good as `_alive`, and nothing tested whether `_alive` was
    # right — ACC-20260830-06 row 16 checked only that it does not *kill* what it asks about. Three
    # seats of the round-3 panel found three separate wrong answers in it.

    Mutation(
        'stranded', 'a live process this run may not open reads as dead, so recovery overwrites it',
        TOOLS / 'mutation_recovery.py',
        '        return ctypes.get_last_error() == ERROR_ACCESS_DENIED',
        '        return False',
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the wait is asked without SYNCHRONIZE, so every live process reads as dead',
        TOOLS / 'mutation_recovery.py',
        '    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)',
        '    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)',
        'tests/test_mutation_recovery.py'),

    # The two entries above mutate lines inside `_alive_nt`, so on POSIX they are unreachable:
    # this group is **10 of 12** there. Counted, not carried — CHG-20260830-08 wrote 9/11 here and
    # 11/12 in its acceptance while the group held twelve entries, and CHG-20260830-09's claims
    # table corrected both to 10/12 without touching this line (CHG-20260831-01, conformance).
    # Nothing reports the difference: CI never runs this file. The entry below is their POSIX twin
    # and is the one that runs everywhere.

    Mutation(
        'stranded', 'a process this run may not signal reads as dead on POSIX too',
        TOOLS / 'mutation_recovery.py',
        """    except PermissionError:
        return True""",
        """    except PermissionError:
        return False""",
        'tests/test_mutation_recovery.py'),

    Mutation(
        'stranded', 'the record stops saying who owns it, so no later run can tell',
        TOOLS / 'mutation_recovery.py',
        '                         "owner": os.getpid()}, ensure_ascii=False)',
        '                         }, ensure_ascii=False)',
        'tests/test_mutation_recovery.py'),

    # ── CHG-20260828-17: the two records are read, not just counted ────────────────────────────

    Mutation(
        'closure', 'a change goes on waiting for a decision its acceptance already made',
        TOOLS / 'ledger_check.py',
        '        if waiting:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a change accepted and later superseded is called a contradiction',
        TOOLS / 'ledger_check.py',
        '    "proposed", "draft", "under review", "in progress", "wip", "pending",',
        '    "proposed", "draft", "under review", "in progress", "wip", "pending", "superseded",',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a verdict nobody wrote down is treated as a pass',
        TOOLS / 'ledger_check.py',
        '        if not passed and not refused:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'closure', 'a verdict that reads both ways is settled by whichever list is checked first',
        TOOLS / 'ledger_check.py',
        '        if passed and refused:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'voice', "a person's pre-authorisation is filed under the runner again",
        SRC / 'conversations.py',
        '    if kind == RELAXATION and turn.get("by"):',
        '    if False:',
        'tests/test_export_voice.py'),

    Mutation(
        "voice", "a split programme's gates are filed under the runner again",
        SRC / 'engine.py',
        # **The one that survived** (CHG-20260903-41). Reverting this exact line — the whole point of
        # that change — left the entire suite green at 2066 tests, because every guard written for
        # the change tested the pieces around it: the helper it called, the CLI that fed it, the AST
        # beside it. Registered here so the line itself stays checked rather than its neighbours.
        '''                by=(report.relaxation_authorisers.get(relaxed)
                    or report.class_authorised_by or None))''',
        '                by=(report.class_authorised_by or None))',
        'tests/test_change_classes.py'),

    Mutation(
        'voice', 'the declaration stops recording who made it',
        SRC / 'cli.py',
        # **One line again** (CHG-20260903-41). This was anchored through `cmd_run`'s own comment
        # because CHG-20260903-22 gave `serve` the same flag and the same operator turn, so a
        # one-line anchor matched twice. That duplication is what `_declare_classes` removed — both
        # commands had also dropped the per-workstream form, identically — so the reason for the
        # two-line anchor is gone with it and the guarantee now lives in one place.
        '            by=str(entry["authorised_by"]))',
        '''            # dimension this document exists to keep straight.
            by=None)''',
        'tests/test_export_voice.py'),

    Mutation(
        'modules', 'each module builds from HEAD again, so N+1 cannot see N',
        SRC / 'worktree.py',
        '        done = self._run(["git", "worktree", "add", "--detach", str(where), self.tip],',
        '        done = self._run(["git", "worktree", "add", "--detach", str(where), "HEAD"],',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'the finished module is no longer committed when the next one starts',
        SRC / 'worktree.py',
        '        if self._live is not None and self._live != key:\n            self.finish(self._live)',
        '        if False:\n            self.finish(self._live)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'an ignored build artifact is committed after all',
        SRC / 'worktree.py',
        '        staged = self._git(["add", "-A"], where)',
        '        staged = self._git(["add", "-A", "--force"], where)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "the build's artifacts stop reaching the working tree",
        SRC / 'worktree.py',
        '        for key, where in sorted(self._trees.items()):\n            for rel in self.artifacts(key):',
        '        for key, where in []:\n            for rel in self.artifacts(key):',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "the operator's branch is moved even when that would discard their work",
        SRC / 'worktree.py',
        '        done = self._git(["merge", "--ff-only", self.tip], top)',
        '        done = self._git(["merge", self.tip], top)',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'a module that halted is committed as though it had passed',
        SRC / 'cli.py',
        '        if live and int(str(live).rsplit("-", 1)[-1] or 0) <= recorded:',
        '        if live:',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'the run stops saying that uncommitted edits will not be seen',
        SRC / 'cli.py',
        '        dirty = trees.uncommitted()',
        '        dirty = []',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', 'a new tree starts empty, so a filesystem-reading agent rebuilds the same module',
        SRC / 'worktree.py',
        '        self._carry_forward_into(str(where))',
        '        pass',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'modules', "an ignored directory is skipped, dropping the whole of a build's output",
        SRC / 'worktree.py',
        '            if source.is_dir():',
        '            if False:',
        'tests/test_worktree_isolation.py'),

    Mutation(
        'guards', 'two changes may wear one number again',
        TOOLS / 'ledger_check.py',
        '        if mine and landed and mine != landed:',
        '        if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'editing a record starts counting as a collision',
        TOOLS / 'ledger_check.py',
        '        mine = _title(path.read_text(encoding="utf-8"))',
        '        mine = path.read_text(encoding="utf-8")',
        'tests/test_ledger_check.py'),

    Mutation(
        'guards', 'an unresolvable ref passes quietly instead of saying nothing was checked',
        TOOLS / 'ledger_check.py',
        # Removes the message outright. The first draft mutated only the FIRST line of the
        # two-line string, and `was NOT checked` lives on the second — so the mutated code still
        # printed what the test asserts, and the run reported NOT CAUGHT for a mutation that had
        # not broken anything. A mutation that does not make the guarantee false proves nothing
        # either way.
        '''        print("ledger check: no main to compare against, so a change taking an id another change "
              "already has was NOT checked. Fetch the default branch to get that check.")''',
        '''        pass''',
        'tests/test_ledger_check.py'),

    Mutation(
        'classes', 'a change-level gate relaxes when only some parts were pre-authorised',
        SRC / 'policy.py',
        '    if not seen or any(n == DEFAULT_CLASS for n in seen):',
        '    if not seen:',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'an emergency part is reported as a standard one',
        SRC / 'policy.py',
        '    return "emergency" if "emergency" in seen else "standard"',
        '    return "standard"',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', "a node stops reading its own workstream's class",
        SRC / 'engine.py',
        '    if mine is not None:\n        return policy.class_in_force(per.get(mine), today)',
        '    if False:\n        return policy.class_in_force(per.get(mine), today)',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'one sentence pre-authorises every part of a split programme again',
        SRC / 'cli.py',
        '    if run_level and len(workstreams or {}) > 1:',
        '    if False:',
        'tests/test_change_classes.py'),

    Mutation(
        'classes', 'a class may name a workstream the plan never declared',
        SRC / 'cli.py',
        '            if name not in (workstreams or {}):',
        '            if False:',
        'tests/test_change_classes.py'),

    Mutation(
        'record', 'a run records that it stopped and not why',
        SRC / 'engine.py',
        '        conversation.close(report.state, at_node=report.halted_at, why=report.halt_reason,\n                           risk=report.risk_settled, change_class=report.change_class or None)',
        '        conversation.close(report.state)',
        'tests/test_closing_record.py'),

    Mutation(
        'record', 'the closing summary goes back to the bare state word',
        SRC / 'conversations.py',
        '        where = f" at {turn[\'at_node\']}" if turn.get("at_node") else ""',
        '        where = ""',
        'tests/test_closing_record.py'),

    Mutation(
        'record', "a body may rewrite the turn's own envelope again",
        SRC / 'conversations.py',
        '        collided = [k for k in self.ENVELOPE if k in self.body]',
        '        collided = []',
        'tests/test_closing_record.py'),

    Mutation(
        'planning', 'a formatting difference stops a run again',
        SRC / 'engine.py',
        '        distinct = sorted({_same_signature(s) for s in by_workstream.values()})',
        '        distinct = sorted(set(by_workstream.values()))',
        'tests/test_sub_planning.py'),

    Mutation(
        'planning', 'all whitespace is stripped, so two different declarations read as one',
        SRC / 'engine.py',
        '    return re.sub(r"\\s*([^\\w\\s])\\s*", r"\x01", signature.strip())',
        '    return re.sub(r"\\s+", "", signature)',
        'tests/test_sub_planning.py'),

    Mutation(
        'readers', 'the strip forgets the page is HTML',
        REPO / 'tests' / 'test_server.py',
        '    return _without_scripts_comments(_without_html_comments(source))',
        '    return _without_scripts_comments(source)',
        'tests/test_server.py'),

    Mutation(
        'readers', 'quotes are tracked in markup again, so one apostrophe disables the strip',
        REPO / 'tests' / 'test_server.py',
        '    scripted = "<script" not in source',
        '    scripted = True',
        'tests/test_server.py'),

    Mutation(
        'readers', 'the field inventory reads the page with its prose again',
        REPO / 'tests' / 'test_server.py',
        '    page = _console_code()\n    snapshot = server.RunState().snapshot()',
        '    page = _console()\n    snapshot = server.RunState().snapshot()',
        'tests/test_server.py'),

    # Two `prose` mutations retired into this group rather than deleted (CHG-20260904-15).
    # *a call handing nothing counts as compliance again* pinned the `any(call.keywords ...)`
    # clause, which is gone: a call handing nothing cannot satisfy the recorded-against-handed
    # rule below, so the clause had nothing left to do and the mutation had nothing to anchor
    # on. *the page says `reason` belongs to the tie alone again* pinned one divider's
    # wording; the mutation below pins the **grouping**, which is what the page was wrong
    # about in both directions. Neither guarantee is unpinned; both are pinned harder.
    Mutation(
        'readers', 'a decision may record a stop name it never handed over',
        REPO / 'tests' / 'test_server.py',
        '        if not (calls and owed and all(owed)',
        '        if not (calls',
        'tests/test_server.py'),

    Mutation(
        'readers', 'the page puts `reason` back inside one question group',
        REPO / 'docs' / 'API.md',
        '  // Carried by TWO of the four questions each, so these belong to neither group below.',
        '  // meaningful when `incomplete` and nothing else.',
        'tests/test_server.py'),

    # Three `prose-guards` mutations were retired rather than faked (CHG-20260904-19). Reverting
    # the flowed read of the module, or the guard's read of its own file, re-opens a hole nothing
    # currently exercises: no live sentence is wrapped wrongly and this file no longer states the
    # claim it forbids, because the floors that test those two assemble their plants. What is
    # pinned instead is the **check**, pointed at planted text — `test_a_rewrapped_count_is_still_
    # a_count` and `test_the_banned_claim_is_found_wherever_it_is_wrapped`. Same call
    # CHG-20260904-15 made for the sibling inventory, and stated for the same reason.
    Mutation(
        'prose-guards', 'the cited-path rule narrows back to one directory',
        REPO / 'tests' / 'test_documented_numbers.py',
        'CITED_ROOTS = ("config", "docs", "examples", "tests", "tools")',
        'CITED_ROOTS = ("examples",)',
        'tests/test_documented_numbers.py'),

    Mutation(
        'prose-guards', 'the banned claim is matched as one exact string again',
        REPO / 'tests' / 'test_settings.py',
        'BANNED_CLAIM = re.compile(r"lower\\s+the\\s+seat\\s+floor\\s+and\\s+(?:can\\s+do\\s+)?nothing\\s+else",',
        'BANNED_CLAIM = re.compile(r"lower the seat floor and can do nothing else",',
        'tests/test_settings.py'),

    Mutation(
        'bypass', 'the crossing stops naming where the seat count came from',
        SRC / 'engine.py',
        '        if cfg.seats_from:\n            report.relaxation_authorisers[note] = cfg.seats_from',
        '        if False:\n            report.relaxation_authorisers[note] = cfg.seats_from',
        'tests/test_settings.py'),

    Mutation(
        'bypass', 'a relaxation goes back to being filed in the runner voice',
        SRC / 'engine.py',
        '            conversation.relaxation(\n                relaxed, by=report.relaxation_authorisers.get(relaxed) or None)',
        '            conversation.relaxation(relaxed)',
        'tests/test_settings.py'),

    Mutation(
        'bypass', 'a vouch that works goes back to leaving nothing behind',
        SRC / 'engine.py',
        '        if halt is None and vouched:',
        '        if False:',
        'tests/test_settings.py'),

    Mutation(
        'bypass', 'the confirmation is bound to the toggle again, so one order skips it',
        SRC / 'settings.py',
        '    if not after.below_floor() or before.below_floor():',
        '    if not after.high_risk_mode or before.high_risk_mode:',
        'tests/test_settings.py'),

    Mutation(
        'settings', 'a seat count no panel can open loads, and every surface crashes on it',
        SRC / 'settings.py',
        '    if seats > len(policy.SEATS):',
        '    if False:',
        'tests/test_settings.py'),

    Mutation(
        'settings', 'a vouch is stored as typed, so it is displayed and matches nothing',
        SRC / 'settings.py',
        '        out.append(name)',
        '        out.append(command)',
        'tests/test_settings.py'),

    Mutation(
        'settings', 'save writes what load will refuse, locking the screen out of its own file',
        SRC / 'settings.py',
        '    _check_seats(settings.review_seats, where=path)\n    _check_vouched(settings.ordinary_commands, where=path)',
        '    pass',
        'tests/test_settings.py'),

    Mutation(
        'settings', 'the vouch row is on the screen and does something else',
        SRC / 'settings.py',
        '         _edit_vouched),',
        '         _DISCARD),',
        'tests/test_settings.py'),

    Mutation(
        'settings', 'a below-floor option quietly yields the floor',
        SRC / 'settings.py',
        '        rows.append((f"{n}", "below the floor — needs high-risk mode, and the run records it", n))',
        '        rows.append((f"{n}", "below the floor — needs high-risk mode, and the run records it", policy.SEAT_FLOOR))',
        'tests/test_settings.py'),

    Mutation(
        'grading', 'the whole Risk line is read, so every qualified grade is refused',
        TOOLS / 'ledger_check.py',
        '    return re.split(r"[\\s,.;(—-]", said, 1)[0] if said else ""',
        '    return said',
        'tests/test_ledger_check.py'),

    Mutation(
        'grading', '`none` is admitted on a record that is still deciding',
        TOOLS / 'ledger_check.py',
        '        allowed = RISK_GRADES + ((RISK_WHEN_NOTHING_WAS_BUILT,) if terminal else ())',
        '        allowed = RISK_GRADES + (RISK_WHEN_NOTHING_WAS_BUILT,)',
        'tests/test_ledger_check.py'),

    Mutation(
        'grading', 'the section stops saying why it exists',
        REPO / 'README.md',
        'Named here rather than left for a reader to discover, because a governance tool that overstates what',
        'Named here for the reader, because a governance tool that claims more than it holds',
        'tests/test_documented_numbers.py'),

    Mutation(
        'provenance', 'a deliberately ignored artefact reads as a citation nobody can open',
        REPO / 'tests' / 'test_documented_numbers.py',
        '    return split(listed.stdout), split(asked.stdout)',
        '    return split(listed.stdout), set()',
        'tests/test_documented_numbers.py'),

    Mutation(
        'provenance', 'git failing to answer passes instead of saying nothing was checked',
        REPO / 'tests' / 'test_documented_numbers.py',
        '    if unanswered:',
        '    if False:',
        'tests/test_documented_numbers.py'),

    Mutation(
        'provenance', 'the skip stops naming which command could not answer',
        REPO / 'tests' / 'test_documented_numbers.py',
        '        pytest.skip("git could not answer %s, so provenance was NOT checked: %s"',
        '        pytest.skip("provenance was NOT checked: %.0s%s"',
        'tests/test_documented_numbers.py'),

    Mutation(
        'prose', 'the strip drops only a comment that starts its line',
        REPO / 'tests' / 'test_server.py',
        '        if source.startswith("//", i):',
        '        if source.startswith("//", i) and source[max(0, i - 200):i].rstrip().endswith(chr(10)):',
        'tests/test_server.py'),

    Mutation(
        'prose', 'the strip stops removing a comment that ends a line of code',
        REPO / 'tests' / 'test_server.py',
        '        if source.startswith("//", i):',
        '        if source.startswith("//", i) and not out:',
        'tests/test_server.py'),

    Mutation(
        'prose', "the decision rule writes the two names instead of reading _answering",
        REPO / 'tests' / 'test_server.py',
        '    wanted = {a.arg for a in _answering_of(runner).args.kwonlyargs}',
        '    wanted = {"gate", "node_id"}',
        'tests/test_server.py'),

    Mutation(
        'prose', 'the stop is given whichever adjudication happened last',
        SRC / 'server.py',
        '    mine = [a for a in report.adjudications if a.get("node_id") == here]',
        '    mine = []',
        'tests/test_server.py'),

    Mutation(
        'adjacency', 'the box goes back to whichever adjudication happened last',
        SRC / 'server.py',
        '    mine = [a for a in report.adjudications if a.get("node_id") == here]',
        '    mine = list(report.adjudications)',
        'tests/test_server.py'),

    Mutation(
        'adjacency', "a panel's first lap is shown instead of what it settled on",
        SRC / 'server.py',
        '    return dict(mine[-1]) if mine else None',
        '    return dict(mine[0]) if mine else None',
        'tests/test_server.py'),

    Mutation(
        'adjacency', 'the box stops reading the field and shows nothing again',
        SRC / 'console' / 'index.html',
        '    var here = state.adjudication_here;',
        '    var here = null;',
        'tests/test_server.py'),

    Mutation(
        'contract', 'the page goes back to calling six of the fifteen conditional',
        REPO / 'docs' / 'API.md',
        '**All 16 keys are on every suspension**',
        '**Nine keys are on every suspension**',
        'tests/test_api_schema.py'),

    Mutation(
        'contract', 'the block goes back to a divider that says only-when',
        REPO / 'docs' / 'API.md',
        '  // meaningful when `incomplete` — the intake survey.',
        '  // only when `incomplete` — the intake survey.',
        'tests/test_api_schema.py'),

    Mutation(
        'contract', 'a docstring is read as its first line again, so its body is unscanned',
        REPO / 'tests' / 'test_documented_numbers.py',
        '    for node in ast.walk(ast.parse(source)):\n        if isinstance(node, _HOLDERS):\n            text = ast.get_docstring(node, clean=False)\n            if text:',
        '    for node in ast.walk(ast.parse(source)):\n        if isinstance(node, _HOLDERS):\n            text = (ast.get_docstring(node, clean=False) or "").split("\\n")[0]\n            if text:',
        'tests/test_documented_numbers.py'),

    Mutation(
        'contract', "a parser's position report is read as a citation into this source",
        REPO / 'tests' / 'test_documented_numbers.py',
        'CITATIONS = (re.compile(r"[a-z_]+\\.py:(\\d+)"), re.compile(r"\\bline (\\d+)\\b(?! column)"))',
        'CITATIONS = (re.compile(r"[a-z_]+\\.py:(\\d+)"), re.compile(r"\\bline (\\d+)\\b"))',
        'tests/test_documented_numbers.py'),

    Mutation(
        'decisions', 'the two names are handed over swapped, so every valid refusal dies',
        SRC / 'server.py',
        '            waiting = self._answering(gate=gate, node_id=node_id)\n            self.state.rejections.append(\n                engine.Rejection(gate=gate, node_id=node_id or waiting.get("node_id"),',
        '            waiting = self._answering(gate=node_id, node_id=gate)\n            self.state.rejections.append(\n                engine.Rejection(gate=gate, node_id=node_id or waiting.get("node_id"),',
        'tests/test_server.py'),

    Mutation(
        'decisions', 'the ask counter goes back to outliving the run it counts',
        SRC / 'server.py',
        '            self.state = RunState(state="running", version=self.state.version + 1,\n                                  instructions=[instruction] if instruction else [])',
        '            self.state = RunState(state="running", version=self.state.version + 1,\n                                  instructions=[instruction] if instruction else [],\n                                  instructions_at_last_incomplete_stop=(\n                                      self.state.instructions_at_last_incomplete_stop))',
        'tests/test_server.py'),

    Mutation(
        'supersession', 'a back-pointer the named record denies goes unreported again',
        TOOLS / 'ledger_check.py',
        '            if claimed >= SUPERSESSION_REQUIRED_FROM and chg_id not in _supersedes(texts[claimed]):',
        '            if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'supersession', 'the gate moves to the pointer, silencing every pre-threshold record',
        TOOLS / 'ledger_check.py',
        '            if claimed >= SUPERSESSION_REQUIRED_FROM and chg_id not in _supersedes(texts[claimed]):',
        '            if chg_id >= SUPERSESSION_REQUIRED_FROM and chg_id not in '
        '_supersedes(texts[claimed]):',
        'tests/test_ledger_check.py'),

    Mutation(
        'supersession', 'a back-pointer naming a record that is not there goes unreported',
        TOOLS / 'ledger_check.py',
        '        for claimed in _superseded_by(texts[chg_id]):\n            if claimed not in texts:',
        '        for claimed in _superseded_by(texts[chg_id]):\n            if False:',
        'tests/test_ledger_check.py'),

    Mutation(
        'supersession', 'the field is read past its own line, so a linked sibling becomes an edge',
        TOOLS / 'ledger_check.py',
        'r"^[-*]\\s*(?:\\*\\*)?Supersedes(?:\\*\\*)?\\s*:(.*)$"',
        'r"^[-*]\\s*(?:\\*\\*)?Supersedes(?:\\*\\*)?\\s*:(.*(?:\\n  +.*)*)$"',
        'tests/test_ledger_check.py'),

    Mutation(
        'modules', 'a module is recorded on the lap the engineer said there was nothing',
        SRC / 'graph.py',
        '         branches={"yes": "record_module", "no": "next_module"},',
        '         branches={"yes": "record_module", "no": "record_module"},',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'silence is read as a build',
        SRC / 'engine.py',
        '        return "yes" if str(ask.result.get("module") or "") else "no"',
        '        return "yes"',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'the guard can be answered instead of read',
        SRC / 'engine.py',
        '    if node.id == "module_built":',
        '    if node.id == "module_built" and value is None:',
        'tests/test_module_built.py'),

    Mutation(
        'modules', 'the module cycle escapes the loop and puts review nodes in a worktree',
        SRC / 'graph.py',
        'def module_cycle(start: str = "engineer_build", end: str = "next_module") -> List[str]:',
        'def module_cycle(start: str = "engineer_build", end: str = "record_module") -> List[str]:',
        'tests/test_module_built.py'),

    Mutation(
        "cli", "refusal text goes to the terminal with its control characters intact",
        SRC / "cli.py",
        '''    return "".join(c if (c.isprintable() or c == " ") else''',
        '''    return str(value) or "".join(c if (c.isprintable() or c == " ") else''',
        "tests/test_conversations_sqlite.py"),

    Mutation(
        "clock", "the turn clock loses millisecond resolution again",
        SRC / "conversations.py",
        '''    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")''',
        '''    return datetime.now(timezone.utc).isoformat(timespec="seconds")''',
        "tests/test_conversations.py"),

    Mutation(
        "finish", "the unspent-confirmation report goes back to success-only",
        SRC / "engine.py",
        '''    unspent = {gate: n for gate, n in confirmations.items() if n > 0}''',
        '''    unspent = ({gate: n for gate, n in confirmations.items() if n > 0}
               if report.halted_at == "done" else {})''',
        "tests/test_settings.py"),

    Mutation(
        "finish", "a gate stop is finished twice, so it complains twice",
        SRC / "engine.py",
        '''            # Already finished inside `_gate`; see the `before` site above.
            return stop''',
        '''            return _finish(stop, confirmations)''',
        "tests/test_settings.py"),
    # ── node-config-accounting (CHG-20260907-28) ─────────────────────────────────────────────
    # `GET /config/nodes` sent six keys and no rule watched any of them. The `-29` rule iterates
    # `RunState.snapshot()` and the `-49` rule iterates `RunReport.as_dict()`; `assignable` is in
    # neither, so a key documented as something *"the console can grey out"* sat beside a console
    # with no per-node configure control for a fortnight and nothing could have said so.
    #
    # **One fix here is deliberately unregistered.** `server.py`'s comment above `"assignable"`
    # carried the same false claim as the page and is corrected in the same change, and no
    # mutation of it can be caught: `_console_code()` strips comments from the *console* so a
    # comment cannot satisfy the console rule, and no guard reads `server.py`'s comments at all.
    # Writing a second vocabulary check over source-file prose would pin the wording of a comment
    # and nothing else, which is the class this repository's own records call its recurring defect.
    # The page is the copy three surfaces are written against, and the page is the copy pinned.
    Mutation(
        "node-config-accounting", "a seventh key joins the route in silence",
        SRC / "server.py",
        '''                    "assignable": list(store_mod.MODES_THAT_USE_MODELS),
                })''',
        '''                    "assignable": list(store_mod.MODES_THAT_USE_MODELS),
                    "seventh": [],
                })''',
        "tests/test_server.py::test_every_key_of_the_node_config_route_is_named_by_the_console_or_written_down"),

    Mutation(
        "node-config-accounting", "a key leaves the route and its inventory entry stands",
        SRC / "server.py",
        '''                    "assignable": list(store_mod.MODES_THAT_USE_MODELS),
                })''',
        '''                })''',
        "tests/test_server.py::test_every_key_of_the_node_config_route_is_named_by_the_console_or_written_down"),

    Mutation(
        "node-config-accounting", "the console stops naming the one key it draws by name",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        '''  var byModel = assign.by_model || {};''',
        '''  var byModel = assign.byModel || {};''',
        "tests/test_server.py::test_every_key_of_the_node_config_route_is_named_by_the_console_or_written_down"),

    Mutation(
        "node-config-accounting", "the carrier two inventory reasons name is not a key any more",
        SRC / "server.py",
        '''                    "by_model": by_model,''',
        '''                    "by_models": by_model,''',
        "tests/test_server.py"
        "::test_no_fold_named_in_the_node_config_inventory_is_absent_from_the_route_or_the_page"),

    Mutation(
        "node-config-accounting", "the page goes back to promising a console that greys four modes",
        REPO / "docs" / "API.md",
        '''**No shipped console reads it.** From `22f6ace`
until CHG-20260907-28 this page said the console greys the other four out; the console has no
per-node configure control at all, so there has never been anything to grey.''',
        '''The other four ignore it, so the
console can grey them out rather than let somebody configure a node that will not read it.''',
        "tests/test_server.py"
        "::test_the_page_documents_this_route_and_promises_no_reader_it_does_not_have"),

    Mutation(
        "node-config-accounting", "the page stops saying the console it argues against is the shipped one",
        REPO / "docs" / "API.md",
        ''' **The console this repository ships is that
console**: it draws the merged assignments through `by_model` and renders no provenance at all.
`runner run` and `runner serve` each print a count to the terminal; per-assignment provenance is
sent on this route and read by nothing, and the view that would read it is named in
CHG-20260907-28 and built by no record yet.''',
        '''''',
        "tests/test_server.py"
        "::test_the_page_documents_this_route_and_promises_no_reader_it_does_not_have"),

    Mutation(
        "node-config-accounting", "a key the page starts naming keeps its inventory entry",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        '''  var byModel = assign.by_model || {};''',
        '''  var byModel = assign.by_model || {};
  var modes = assign.assignable || [];''',
        "tests/test_server.py::test_every_key_of_the_node_config_route_is_named_by_the_console_or_written_down"),

    # The same edit as "the console stops naming the one key it draws by name", against the other
    # guard. One console line carries two guarantees — that a named key stays named, and that the
    # carrier two folds name is one the page still mentions — and reverting it must not look like
    # reverting only the first. **Named, not drawn**: what these guards prove is that the
    # identifier occurs in executable page text, and a dead `var schemaNames = ["by_model"]` would
    # satisfy them while nothing read it. A seat blocked the first draft for saying more than that
    # and blocked the second for leaving the claim in the prose beside a renamed test.
    # Separate entries, separate objectors, the way `refusal-routing`
    # splits its weak rule from its explicit pin.
    Mutation(
        "node-config-accounting", "the carrier two inventory reasons name is nowhere on the page",
        REPO / "src" / "ai_sdlc_runner" / "console" / "index.html",
        '''  var byModel = assign.by_model || {};''',
        '''  var byModel = assign["by" + "_model"] || {};''',
        "tests/test_server.py"
        "::test_no_fold_named_in_the_node_config_inventory_is_absent_from_the_route_or_the_page"),

    Mutation(
        "node-config-accounting", "the page's sketch stops enumerating what the route sends",
        REPO / "docs" / "API.md",
        '''  "source": { "node_models.<node id>": "plan" | "store", "seat_models.<seat>": … },
''',
        '''''',
        "tests/test_server.py"
        "::test_the_page_documents_this_route_and_promises_no_reader_it_does_not_have"),

    # ── ask-in-flight (CHG-20260907-27) ───────────────────────────────────────────────────
    # CHG-20260904-05 measured that a walk is not always an ask and repaired the **tally**:
    # `server._walk_once` stops appending on `attach`. `intake.asks_including_this_one` kept
    # adding one unconditionally, so the walk that was not counted still counted itself, and two
    # recorded asks plus one attached file crossed `ASK_LIMIT`. Six sites carry the repair — the
    # arithmetic, the two engine call sites that must pass the same input, the one caller that
    # knows the answer, the append guard that has to take the same fact the engine took, and the
    # spelling that fact made reachable — and each is registered against the node that goes red
    # when it is undone.
    #
    # The last two are the **second round's**. The first build gave the engine a conjunct the
    # server's append guard did not have, so on a `serve` `start` against a persisted journal the
    # counter said 1 and the sentence said 0 — one box, two answers, which is the defect
    # CHG-20260903-42 closed. Both new entries name the same node, because both lines are what
    # makes that one box hold one number.
    #
    # The last two after those are the **third round's**, and they are not in `src/ai_sdlc_runner`
    # at all. The server's expression counts asks over the whole report and the engine's counts
    # them over one node; they are the same pair of integers only because nothing asks before
    # `intake_review`. Two comments say so and nothing enforced it, so the graph is what the
    # mutations edit: an asking node put in front of it, and a rejection routed back to it. Both
    # name the one test that pins the assumption rather than a behaviour, because that is what is
    # being registered — an assumption, not a repair.
    #
    # **`console/index.html` is deliberately not mutated here.** A draft registered
    # `if (opts && opts.length)` -> `if (true)` against
    # `test_the_row_this_file_renders_is_the_row_the_page_renders`, and a review seat named what
    # that measures: the guard is a text search over the page, so the entry is caught **by the
    # exact token it edits** and by nothing else. It reports on the spelling of the line rather
    # than on what a browser draws, which is the shape this repository has had to undo twice
    # (CHG-20260903-39). The test stays — a mirror nobody checks is a second implementation, and a
    # text search is the only console guard available here — and the table does not claim it as
    # coverage of rendered behaviour.
    #
    # The **default** is registered too, and the first draft of this comment said it could not be:
    # the server fills the field on every walk, so the reasoning went that no test could see the
    # default move. Measured instead of reasoned — `= True` -> `= False`, whole files — and **two**
    # tests objected, both walking with a plain `RunConfig` and reading the sentence a person is
    # shown. (The first draft of this sentence said *three*, against the `2 failed, 395 passed`
    # three lines below it and against its own *"both"*; a review seat absorbed the corrected
    # figure without carrying it here.) The claim that an entry is uncatchable is a claim about a
    # search
    # (`tests/test_intake.py`, `test_flow.py`, `test_cli.py`, `test_server.py`: 2 failed, 395
    # passed).
    Mutation(
        "ask-in-flight", "the ask in flight is counted on a walk nobody was asked for",
        SRC / "intake.py",
        '''    return times_asked(history, aspect) + (1 if in_flight else 0)''',
        '''    return times_asked(history, aspect) + 1''',
        "tests/test_server.py::test_the_runner_does_not_give_up_on_somebody_it_never_asked_again"),

    Mutation(
        "ask-in-flight", "the decision stops being told whether this walk is an ask",
        SRC / "engine.py",
        '''                        if not intake_mod.needs_options(cfg.intake_history, aspect,
                                                        in_flight):''',
        '''                        if not intake_mod.needs_options(cfg.intake_history, aspect):''',
        "tests/test_server.py::test_the_runner_does_not_give_up_on_somebody_it_never_asked_again"),

    Mutation(
        "ask-in-flight", "the sentence and the decision take different inputs again",
        SRC / "engine.py",
        '''                    said = (intake_mod.stop_reason(survey, cfg.intake_history, in_flight)''',
        '''                    said = (intake_mod.stop_reason(survey, cfg.intake_history)''',
        "tests/test_server.py::test_the_console_shows_one_answer_to_how_many_times_it_has_been_asked"),

    Mutation(
        "ask-in-flight", "the server tells every walk it is an ask",
        SRC / "server.py",
        '''                intake_ask_in_flight=(len(self.state.instructions)
                                      > self.state.instructions_at_last_incomplete_stop))''',
        '''                intake_ask_in_flight=True)''',
        "tests/test_server.py::test_the_walk_is_told_whether_it_is_an_ask"),

    Mutation(
        "ask-in-flight", "a resumed walk that opened no session still counts itself as an ask",
        SRC / "engine.py",
        '''                in_flight = cfg.intake_ask_in_flight and asked_somebody''',
        '''                in_flight = cfg.intake_ask_in_flight''',
        "tests/test_intake.py::test_a_resumed_walk_that_opened_no_session_asked_nobody"),

    Mutation(
        "ask-in-flight", "a caller that says nothing is assumed to have asked nobody",
        SRC / "engine.py",
        '''    intake_ask_in_flight: bool = True''',
        '''    intake_ask_in_flight: bool = False''',
        "tests/test_intake.py::test_before_three_asks_there_are_no_options_only_the_question"),

    Mutation(
        "ask-in-flight", "the append guard stops asking whether a session was opened",
        SRC / "server.py",
        '''                if len(report.resumed) < len(report.asks):''',
        '''                if len(report.resumed) <= len(report.asks):''',
        "tests/test_server.py::test_the_same_brief_started_twice_says_one_number"),

    # The fourth round's blocking finding, and the reason the two lines above are two `if`s.
    # Putting the assignment back under the third conjunct is the shipped code of `e3e838f`, so
    # this entry is the regression itself rather than an invented edit.
    Mutation(
        "ask-in-flight", "the mark stops moving on a walk that recorded no stop",
        SRC / "server.py",
        '''            if stop.get("incomplete") and told > self.state.instructions_at_last_incomplete_stop:
                self.state.instructions_at_last_incomplete_stop = told
                if len(report.resumed) < len(report.asks):
                    self.state.intake_history.append(
                        {"missing": list(stop.get("missing") or ())})''',
        '''            if (stop.get("incomplete") and told > self.state.instructions_at_last_incomplete_stop
                    and len(report.resumed) < len(report.asks)):
                self.state.instructions_at_last_incomplete_stop = told
                self.state.intake_history.append(
                    {"missing": list(stop.get("missing") or ())})''',
        "tests/test_server.py::test_an_attachment_after_a_replayed_start_is_not_an_ask"),

    Mutation(
        "ask-in-flight", "zero loses the spelling the conjunct made reachable",
        SRC / "intake.py",
        '''        nth = {0: "not asked yet", 1: "asked once",
               2: "asked twice"}.get(seen, f"asked {seen} times")''',
        '''        nth = {1: "asked once", 2: "asked twice"}.get(seen, f"asked {seen} times")''',
        "tests/test_server.py::test_the_same_brief_started_twice_says_one_number"),

    Mutation(
        "ask-in-flight", "a node asks somebody before the one the append guard counts over",
        SRC / "graph.py",
        '''    Node("intake", STEP, "the user's instruction arrives", next="intake_review", mode=RUNNER,
         note="the runner reads it; nobody is asked anything yet"),''',
        '''    Node("intake", STEP, "the user's instruction arrives", next="intake_review",
         role="seat", mode=SINGLE, note="the runner reads it; nobody is asked anything yet"),''',
        "tests/test_server.py::"
        "test_nothing_asks_anybody_before_the_node_the_append_guard_counts_over"),

    Mutation(
        "ask-in-flight", "a rejection routes back to the node the append guard counts over",
        SRC / "graph.py",
        '''    Node("review_failed", STEP, "the panel did not pass it", next="change_retry", mode=RUNNER,''',
        '''    Node("review_failed", STEP, "the panel did not pass it", next="intake_review", mode=RUNNER,''',
        "tests/test_server.py::"
        "test_nothing_asks_anybody_before_the_node_the_append_guard_counts_over"),

    # The half above looked for edges into `intake_review` alone, so this graph was green until
    # the fourth round widened the target set: `intake` is a `RUNNER` step whose only `next` is
    # `intake_review`, so an edge into it arrives at the counted node just the same. Measured on
    # the pre-widening expression: `routes_back` came back `[]`.
    # The eighth round's, and it is the shape this file exists for: the sixth round argued that the
    # mark is written only at an incomplete stop, corrected four documents on the strength of it,
    # and nothing executable held it. A seat measured the gap by dropping the conjunct and running
    # every file that names the mark, the history or the `Runner` — all green. The claim had a
    # measurement and no pin, which is the difference this registry is here to keep visible.
    Mutation(
        "ask-in-flight", "the mark moves on a walk that found nothing missing",
        SRC / "server.py",
        '''            if stop.get("incomplete") and told > self.state.instructions_at_last_incomplete_stop:''',
        '''            if told > self.state.instructions_at_last_incomplete_stop:''',
        "tests/test_server.py::test_a_walk_that_finds_nothing_missing_does_not_move_the_mark"),

    # ── panel-routability (CHG-20260908-03) ─────────────────────────────────────────────────
    # `validate`'s panel-routability rule was written for `MODEL_PANEL` and guarded on it, and the
    # other panel mode had no rule at all. Measured before writing one: renaming `lead_review`'s
    # branches to `approve`/`reject` passed `validate`, and would then have died at `engine`'s
    # branch lookup with `has no branch 'pass'` — which is the death CHG-20260901-11 was opened for
    # and closed on one side.
    #
    # The seat rule is **stricter**, and that asymmetry is the reason it is a separate rule rather
    # than a widened guard: a model panel's outcome is mapped through `panel_branches`
    # (`engine`'s `node.panel_branches.get(outcome, outcome)`), so declaring that mapping is a real
    # escape. A seat panel's comes back from `_adjudicate`, which does not consult it, so there is
    # no escape and the message must not offer one. The mapping is refused there because it cannot
    # help — the branch rule already puts `pass` among its branches, so the second read that names
    # *ratified* lands correctly with no declaration at all — and because one shape of it,
    # a `pass` key pointing elsewhere, makes that word the one the grade settles on — and the
    # grade settles at all only if that word is one `_adjudicate` returns: `fail` puts the settling
    # on a rejection, `undecided` on a panel that decided nothing, anything else on nothing.
    # **No declaration helps**; the harm has an exact condition and is not a count, after four
    # counts of this set were each refused for stopping short of it and four descriptions of the
    # harm each named a subset of its three outcomes.
    #
    # The third entry's rule refuses a declared mapping on a **`SEAT_PANEL` only**, and the fourth
    # pins that it stays there. Three corrections got it to that, each from a seat:
    #
    #   - the first draft said the mapping is *never read* on the seat path. `engine` reads it once
    #     more after the branch is taken, to name the word meaning ratified.
    #   - so the rule was widened to every mode but `MODEL_PANEL`, on the ground that a
    #     declared-but-unrouted mapping gives a `ratified` the node's own answer can never equal.
    #     **Backwards**: `pm_signoff` offers `yes`/`no` and settles *because* it declares
    #     `{pass: "yes"}` — without it `ratified` is `pass`, which it does not offer. Elsewhere the
    #     declaration is the only way to name that word, so the widening made a `settles_risk` node
    #     with its own vocabulary inexpressible. Withdrawn.
    #   - and the reason left behind — a declaration on a seat panel *can only misname* ratified —
    #     is refuted by every declaration that does not point a `pass` key elsewhere — most of
    #     them. What holds is that none helps, because rule 1 already puts `pass` among a seat
    #     panel's branches.
    #
    # The **first** entry pins a rule that had shipped for three rounds with no reverse test: this
    # file's own docstring lists CHG-20260901-11's rule among nineteen such, and the repair that
    # installed it is where the next defect was.
    Mutation(
        "panel-routability", "the model-panel branch check may stop looking again",
        SRC / "graph.py",
        '''        if node.mode == MODEL_PANEL and node.branches:''',
        '''        if False and node.branches:''',
        "tests/test_graph_validation.py::test_a_model_panel_whose_branches_the_panel_cannot_name_is_refused"),
    Mutation(
        "panel-routability", "the seat-panel branch check may stop looking",
        SRC / "graph.py",
        '''        if node.mode == SEAT_PANEL and node.branches:''',
        '''        if False and node.branches:''',
        "tests/test_graph_validation.py::test_a_seat_panel_whose_branches_the_panel_cannot_name_is_refused"),
    Mutation(
        "panel-routability", "a seat panel may declare a mapping that misnames ratified again",
        SRC / "graph.py",
        '''        if node.mode == SEAT_PANEL and node.panel_branches:''',
        '''        if False and node.panel_branches:''',
        "tests/test_graph_validation.py::test_a_seat_panel_declaring_panel_branches_is_refused"),
    Mutation(
        # Deleting a rule and **widening** it are different failures, and the entry above only pins
        # the first. This change widened this rule to every mode but `MODEL_PANEL` for one
        # revision; a seat measured that wrong, because elsewhere the declaration is the only way
        # to name the word meaning ratified — `pm_signoff` settles because it declares one. So what
        # needs pinning is that the rule does not reach past the seat panel.
        "panel-routability", "the mapping rule may widen past the seat panel again",
        SRC / "graph.py",
        '''        if node.mode == SEAT_PANEL and node.panel_branches:''',
        '''        if node.mode != MODEL_PANEL and node.panel_branches:''',
        "tests/test_graph_validation.py::test_a_node_that_is_not_a_panel_may_declare_panel_branches"),

    # ── config-accounting (CHG-20260908-02) ─────────────────────────────────────────────────
    # One count in `tests/test_server.py`'s `NOT_ON_THE_CONSOLE` preamble was typed and never
    # asserted: it said the snapshot has **19** keys and the snapshot has 21. The first account of
    # this said the two counts beside it were right *because tests hold them*; a seat measured
    # that and refused it. Only the inventory's fifteen is held. The thirty `as_dict` fields are
    # held by nothing either — no test asserts it, and the rule that would have is over a file
    # list this file is not in. So: one held, two not, and one of the two unheld happens to still
    # be right.
    #
    # The repair is the assertion, not a corrected number, so the mutation adds a key to
    # `RunState.snapshot()` and expects the size guard to go red. It also proves the guard is not
    # vacuous, which a constant compared against itself would not.
    #
    # What is **not** registered: the assertion message corrected in the same round. It said the
    # console renders nothing for the keys it names while the search only asks whether the token
    # occurs, and a message is not reachable by a mutation that keeps the test green — the test
    # passes, so the message is never built. Read instead.
    Mutation(
        "config-accounting", "a key joins the snapshot and the size guard does not notice",
        SRC / "server.py",
        '''            "retired_approvals": list(self.retired_approvals),''',
        '''            "retired_approvals": list(self.retired_approvals),
            "an_unheld_key": None,''',
        "tests/test_server.py::test_the_snapshot_is_twenty_one_keys"),

    # ── manifest-race (CHG-20260908-05) ──────────────────────────────────────────────────────
    # Two defects, one landing unit, and each half is registered against the node that goes red
    # when it alone is undone.
    #
    # The **race**: `start`, `instruct` and `attach` all read the attachment store under
    # `self._lock`; `_walk_once` did not, because a walk deliberately holds no lock across itself.
    # `Store.all()` opens `manifest.json`; `Store.add`, under the lock, finishes with `os.replace`
    # onto it; on Windows that fails `PermissionError` [WinError 5] against an open handle. The
    # defect appeared in one of eight ordinary runs, which is no use as a regression signal.
    # Four tests tried to drive that interleaving and each was green with the repair reverted; the
    # entry here asserts the **invariant** instead — the walk reads the store with the lock held —
    # and a lock knows whether it is held.
    #
    # The **accounting**: the hammer test joined six workers with a timeout, asserted on two flags,
    # and never on the workers. A thread dying of anything but `ServerError` was a
    # `PytestUnhandledThreadExceptionWarning`, and this repository sets no `filterwarnings`, so the
    # run reported `1 passed, 1 warning` — which is how the race above went unreported for as long
    # as it did. It was measured with a worker made to die; the numbers are in the next paragraph,
    # where they stand in for the registration this half cannot have.
    #
    # **Removing the accounting is what cannot be registered; the writer being unlocked can.** A
    # mutation that deletes the accounting runs against a tree where the race is fixed, so no worker
    # dies, `failures` is empty either way and the test passes — `NOT CAUGHT`, correctly, because
    # the accounting only bites when something else is broken. What was measured instead, and is in
    # `ACC-20260908-05`: with a worker injected to die, the accounting gives `1 failed` and its
    # removal gives `1 passed`, with the same `1 warning` in both.
    #
    # The **second entry below** is the something-else: it moves `attach`'s `store.add` out of
    # `with self._lock` and changes nothing else — the version check still runs first, under
    # the lock, and the write keeps its own `try`/`except AttachmentError`. A first version of
    # it moved the call above the version check and out of its `try` as well, and a seat
    # refused it: a compound mutation's `CAUGHT` cannot be attributed to any one of the things
    # it changed. Unlocked, workers die in the store's manifest write path and the accounting
    # reports it, while the invariant test stays green. How many die varies between runs and
    # machines, and so does the error — an earlier draft of this comment said six workers of
    # `PermissionError` in `paths.replace`, and nobody had measured either the count or that it
    # was the only error. **What did not vary across the runs of this mutation is that some die**:
    # none the record lists came back with none. The eight ordinary runs cited three paragraphs up
    # are a different thing — seven of those had none, which is why the undriven defect was no
    # regression signal. And this is a floor under those measurements, not under the scheduler:
    # serialise every manifest write in this process against every other reader and writer — neither
    # `manifest.json` nor the fixed `manifest.json.writing` open by another thread when the write
    # lands; the readers are enumerated two paragraphs below, and the writer counterparty is the
    # staging file itself, which that paragraph does not cover — and there is no collision to kill
    # anyone. (`Store.add` writes the content blob too, at `attachments.py:205`; that write has no
    # fixed name and is not part of this.) So a `NOT CAUGHT` here is a reason to re-run and then
    # to look, not by itself proof of a regression.
    #
    # The counts and the mix live in `ACC-20260908-05` and are not repeated here — not as a rule,
    # because this comment repeats other figures a few paragraphs up, but because these two are
    # what has moved between measurements: the count varied by run and by machine and was once
    # written down as a number nobody had taken, and which error dominates moved with it.
    #
    # What this entry establishes is that **the write belongs under the lock**. It does not isolate
    # what the unlocked write collides with. `Store.add` reads `manifest.json` before it writes
    # (`attachments.py:177`), `_refresh_attachments` reads it under the lock, and the walk reads it
    # too, so a replace onto an open handle can be against any of them. The walk's side is held by
    # the first entry, which asserts the lock is held rather than catching a collision. Between
    # them the pair pins the reader unlocked and the writer unlocked — not the accounting, which is
    # this group's third paragraph, and not the consequence: a walk-time 500 is still pinned by
    # nothing.
    Mutation(
        "manifest-race", "the walk reads the store outside the lock again",
        SRC / "server.py",
        '''            if self._store is not None:
                with self._lock:
                    order_paths = tuple(self._store.order_paths())
            else:
                order_paths = ()''',
        '''            order_paths = tuple(self._store.order_paths()) if self._store else ()''',
        "tests/test_server.py::test_the_walk_reads_the_attachment_store_holding_the_lock"),

    Mutation(
        "manifest-race", "the writer replaces the manifest outside the lock",
        SRC / "server.py",
        '''        with self._lock:
            self._require_version(version)
            try:
                self._store.add(filename, data, instruction=len(self.state.instructions))
            except attach_mod.AttachmentError as exc:
                raise ServerError(str(exc))
            self._refresh_attachments()''',
        '''        with self._lock:
            self._require_version(version)
        if True:
            try:
                self._store.add(filename, data, instruction=len(self.state.instructions))
            except attach_mod.AttachmentError as exc:
                raise ServerError(str(exc))
        with self._lock:
            self._refresh_attachments()''',
        "tests/test_server.py::test_the_gate_never_rests_with_something_still_flagged"),

    Mutation(
        "ask-in-flight", "a rejection routes back to the step in front of the counted node",
        SRC / "graph.py",
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="change_retry", mode=RUNNER),''',
        '''    Node("acceptance_failed", STEP, "back into the module loop", next="intake", mode=RUNNER),''',
        "tests/test_server.py::"
        "test_nothing_asks_anybody_before_the_node_the_append_guard_counts_over"),

    # -- bounded-wait (CHG-20260908-01) -----------------------------------------------------
    # Seven bounded waits in `test_server.py` could time out without saying so: five joins with
    # no `is_alive()` after them, and two `Event.wait(timeout=)` answers thrown away. Shortening
    # one join made the test report "the attachment was never walked" while the attachment was
    # walked, so the reader is sent after a dropped file that is sitting in the store.
    #
    # **When the wait times out**, no behavioural test fails if one of these guards is deleted:
    # the run reaches the same next line and fails there, with the same wrong sentence it had
    # before. That condition is the whole record, and it has now been dropped twice -- first as
    # "deleting an `assert` makes no test fail", which the first entry here refutes, and then as a
    # sentence whose colon promised a justification and delivered "the run fails there", which is a
    # behavioural test failing (both seats).
    #
    # Most entries below are therefore caught by the rule and not by the test they sit in. Three
    # are not: the arrangement group, which the stranded test refuses itself.
    #
    # Two of them — `a guard names the question without asking it` and `a ceiling passed
    # positionally stops counting as a ceiling` — are escapes a seat constructed against the rule's
    # first version. Both passed it. They were "the last two" until a tenth entry was inserted
    # above them; naming them is what a position could not do.
    Mutation(
        "bounded-wait", "a join's timeout goes back to being silent",
        REPO / "tests" / "test_server.py",
        '''    thread.join(timeout=10)
    assert not thread.is_alive(), (
        "the walk did not finish inside the join's timeout, so what follows would "
        "blame the attachment for something the wait did not do")

    assert not gave_up, (''',
        '''    thread.join(timeout=10)

    assert not gave_up, (''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    Mutation(
        "bounded-wait", "the wait in a `finally` goes back to discarding its result",
        REPO / "tests" / "test_server.py",
        '''        if thread.is_alive():
            note = ("the server thread outlived `_config_nodes_keys`. Nothing else in this "
                    "file reports that — measured — so this is the only place it is said: a "
                    "daemon thread is still holding a server this helper was finished with")''',
        '''        if False:
            note = ("the server thread outlived `_config_nodes_keys`. Nothing else in this "
                    "file reports that — measured — so this is the only place it is said: a "
                    "daemon thread is still holding a server this helper was finished with")''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    # By expression, not by presence. A guard copied from the function next door names a thread
    # this one never joined, and would pass a rule that only asked whether `is_alive` appeared.
    #
    # `httpd` rather than a name nothing binds, so the mutation is a copied guard and not a
    # `NameError` (a seat). It does not isolate cleanly either: `httpd` has no
    # `is_alive`, so the mutated helper would also raise `AttributeError` at every call site. The
    # rule refuses it first, at author time, and no in-scope name in that function has the
    # attribute — so this entry shows the rule reading the expression and not what it would cost
    # at runtime (a seat, again).
    Mutation(
        "bounded-wait", "a guard asks about something this function never waited on",
        REPO / "tests" / "test_server.py",
        '''        if thread.is_alive():
            note = (''',
        '''        if httpd.is_alive():
            note = (''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    Mutation(
        "bounded-wait", "a walk throws away the answer its wait gave it",
        REPO / "tests" / "test_server.py",
        '''            if not release[held].wait(timeout=10):
                gave_up.append(held)''',
        '''            release[held].wait(timeout=10)''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    # The arrangement the rule cannot see. `attach` ends in `_advance`, which walks on the
    # *calling* thread when nothing is in flight, so with the first walk returning at once the
    # attach below ran the second walk itself and sat in it for the full ten seconds. Every walk
    # ran, the count came out right, and the mid-walk arrival the test is named for never
    # happened. Holding the first walk is what puts it back.
    Mutation(
        "bounded-wait", "the walk that must block stops blocking, and `attach` walks it itself",
        REPO / "tests" / "test_server.py",
        '''        if held in entered:''',
        '''        if held == 2:''',
        "tests/test_server.py::test_an_action_arriving_as_the_walk_decides_to_stop_is_not_stranded"),

    # **Which line refuses, measured rather than assumed.** A seat pointed out that the mutation
    # above is caught by `entered[1].wait` — with `held == 2` the first walk never signals, so the
    # test dies ten seconds in and `ran_on` is never reached. The seat proposed this one as the
    # entry that would put `ran_on` on the stand. Run: it is caught by `gave_up`, not by `ran_on`,
    # at 12.34s. From those two runs this comment concluded **nothing puts `ran_on` on the
    # stand, and no small mutation can** — and stood on that for a round after the entry three
    # below refuted it. The reason was true of walks 1 and 2 only. Three entries now pin the
    # arrangement, from three sides, and the third of them is what puts `ran_on` on the stand.
    Mutation(
        "bounded-wait", "the first walk signals and does not hold, so `attach` walks the second",
        REPO / "tests" / "test_server.py",
        '''            # into a stopped run. The test thread reads it below.
            if not release[held].wait(timeout=10):''',
        '''            # into a stopped run. The test thread reads it below.
            if held != 1 and not release[held].wait(timeout=10):''',
        "tests/test_server.py::test_an_action_arriving_as_the_walk_decides_to_stop_is_not_stranded"),

    # A join made once a turn, guarded once outside the turn. The guard here is correct — it is a
    # comprehension over the whole collection — and moving it out of the loop is the shape the rule
    # learned to refuse this round.
    Mutation(
        "bounded-wait", "a loop's joins are answered for by the last turn only",
        REPO / "tests" / "test_server.py",
        '''    alive = [t.name for t in threads if t.is_alive()]''',
        '''    alive = [] if not t.is_alive() else [t.name]''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    Mutation(
        "bounded-wait", "a guard names the question without asking it",
        REPO / "tests" / "test_server.py",
        '''    assert not thread.is_alive(), (
        "the walk did not finish inside the join's timeout, so what follows would "
        "blame the attachment for something the wait did not do")
    assert len(walks) == 2, "the attachment was never walked"''',
        '''    assert thread.is_alive, (
        "the walk did not finish inside the join's timeout, so what follows would "
        "blame the attachment for something the wait did not do")
    assert len(walks) == 2, "the attachment was never walked"''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),

    # **This is the entry that puts `ran_on` on the stand**, and it exists because a seat built
    # what two rounds of this record called impossible. `walk` blocks only for walks 1 and 2, so an
    # arrangement defect that lands on the **third** produces no `gave_up` entry and no timeout:
    # move the last attachment to after the join and `_advance` runs walk 3 on the main thread,
    # `first` is not alive, the count is still 3, and `ran_on` is the only line that refuses.
    # Measured at 1.02s, deterministic — the join orders it.
    Mutation(
        "bounded-wait", "the last attachment arrives after the walk it was to interrupt has ended",
        REPO / "tests" / "test_server.py",
        '''    runner.attach(runner.state.version, "two.md", b"2")
    release[2].set()
    first.join(timeout=10)''',
        '''    release[2].set()
    first.join(timeout=10)
    runner.attach(runner.state.version, "two.md", b"2")''',
        "tests/test_server.py::test_an_action_arriving_as_the_walk_decides_to_stop_is_not_stranded"),

    Mutation(
        "bounded-wait", "a ceiling passed positionally stops counting as a ceiling",
        REPO / "tests" / "test_server.py",
        '''    first.join(timeout=10)
    assert not first.is_alive(), (
        "the first walk did not finish inside the join's timeout, so what follows would blame "
        "the second attachment for something the wait did not do")''',
        '''    first.join(10)''',
        "tests/test_server.py::test_every_bounded_wait_says_when_it_did_not_complete"),
]


def _pytest(tests: str):
    """One narrow pytest run. Shared so the baseline and the mutated run are the same command."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", tests, "-q", "-p", "no:randomly", "--no-header",
         "-x", "--tb=no"],
        cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace",
        # `PYTHONIOENCODING`, not `PYTHONUTF8` (CHG-20260828-16). Both make pytest write UTF-8 down
        # the pipe, which is all this needed — CHG-20260823-47 reached for the bigger switch and it
        # worked. But `PYTHONUTF8=1` also makes `locale.getpreferredencoding()` return UTF-8 *inside
        # the suite*, and that is what `subprocess`'s text mode reads. So every mutation ran in a
        # locale no ordinary run of this suite has, and a guarantee about decoding could not be
        # pinned here: reverting the fix left the tests green. `PYTHONIOENCODING` fixes the pipe and
        # leaves the locale alone, which is the part that had to stay real.
        # `MUTATION_RUN` is how the harness announces itself to
        # `test_this_repository_has_no_mutation_in_flight`, which would otherwise fail on the record
        # this run legitimately holds. It was keyed on the record's owner being *alive* instead, and
        # that coupled the guard to `_alive`: a mutation that broke `_alive` made the guard fail, so
        # the run stopped there under `-x` and the tests written for `_alive` never ran — while a
        # genuinely stranded tree whose dead owner's pid had been reused read as alive and went
        # **green**. Announcing beats inferring (CHG-20260830-08, defect and risk seats).
        env={**os.environ, "PYTHONPATH": "src", "PYTHONIOENCODING": "utf-8",
             "MUTATION_RUN": str(os.getpid())})


def _import_fails(path: Path) -> str:
    """Does the mutated file still import? Returns the error, or `""`.

    A separate interpreter, because importing it here would poison this process for every mutation
    after it. `-c` rather than a test run: the question is about the module, and pytest can only
    answer it when the test file happens to import it at its own module scope.
    """
    # **Only a module can fail to import** (CHG-20260904-10). A mutation may target a file that is
    # not Python at all — `docs/API.md` is the contract three surfaces are written against, and a
    # page that says the wrong thing about the data is the same defect class as code that does.
    # Asking the interpreter to import a markdown file reported `ModuleNotFoundError: No module
    # named 'API'` and called an honest mutation BROKE.
    if path.suffix != ".py":
        return ""

    # By its **package path**, not by bare name. `src/ai_sdlc_runner/models.py` imported standalone
    # raises `ImportError: attempted relative import with no known parent package` — which is a
    # property of how it was loaded, not of the mutation, and reported BROKE for four honest
    # mutations in the `reach` group alone (CHG-20260901-01, found by running it).
    if path.parent.name == "ai_sdlc_runner":
        module, where = f"ai_sdlc_runner.{path.stem}", "src"
    else:
        # `path.parent.name`, not a hard-coded `"tools"`. Three shipped mutations target
        # `tests/test_subprocess_codecs.py`, and the fallback imported them with `PYTHONPATH`
        # pointing at `tools/` — so `--only codecs` reported three false `BROKE`s and exited 1 on a
        # clean checkout, telling the author to re-anchor three correctly anchored mutations. That
        # is the failure this whole outcome exists to remove, reintroduced by fixing one arm of it.
        # The four groups run to check that fix were `stranded` and `closure` — which target `tools/`
        # only, and so **passed because** the fallback was hard-coded to `"tools"` — and `reach` and
        # `console`, which are `src/`. `codecs` is the only group with a `tests/` target, and it was
        # the one not run (CHG-20260901-03, conformance seat, correcting -02's account of this).
        # `test_every_mutated_file_still_imports_before_it_is_mutated` runs every target now.
        module, where = path.stem, path.parent.name
    stmt = f"import {module}"
    # A **fresh cache prefix**, not `-B`. `__pycache__` is validated on `int(st_mtime)` plus size,
    # so a same-size rewrite inside one second imports the stale `.pyc`. `-B` was the first fix and
    # it does not close that: it stops bytecode being *written*, never read. Measured — a planted
    # same-size, same-mtime rewrite imports clean under `python` and under `python -B` alike, and
    # refuses only when the cache prefix points somewhere with nothing in it (CHG-20260901-04,
    # defect seat, against this comment's own claim of "none trusted").
    #
    # It costs. A fresh prefix finds no cache **and leaves none**, so every probe recompiles the
    # module and everything it imports: median 65 files / 2.48 MB, up to 137 / 5.29 MB for
    # `server`. (`44 files, 1.34 MB` stood here and is the *smallest* of the 19 targets, quoted as
    # if it were typical.) ~0.34s per probe became ~0.89s warm and ~1.59s cold; over 197 mutations
    # a full run measures 175–313s, mean 261s.
    #
    # Roughly half of that is avoidable and is not being taken: of the 71 `.pyc` files one probe
    # writes, **61 are standard library**. The property being defended is "do not trust a stale
    # `.pyc` for the file under mutation" — invalidating the stdlib's cache 197 times is not part
    # of it. A prefix shared across probes and warmed once, with only the target's own `.pyc`
    # removed each time, measures 0.628s per probe, about 124s per run. That is a real change with
    # a real failure mode (a shared cache is a shared cache) and it is not this one; it is named
    # here so the next reader does not have to rediscover it (CHG-20260901-06, risk seat).
    #
    # The probe also runs **inside** the mutated window, so this adds roughly a second per mutation
    # to the time the tree spends holding a mutation — the exposure `mutation_recovery` exists for.
    # Small against a 54-minute run; not nothing. Correctness over speed is the right trade for the outcome that says "the probe
    # learned nothing", but the price is real and two figures elsewhere were left stale by it
    # (CHG-20260901-05, risk seat).
    #
    # A run killed mid-probe leaves one `mutation-probe-*` directory behind, because `with` does
    # not unwind through a `TerminateProcess`. One per killed run, in the system temp directory —
    # `%LOCALAPPDATA%\Temp` here, which **nothing sweeps by default**; the clause claiming the OS
    # clears it was written about POSIX in a module that is four paragraphs of Windows divergence
    # (CHG-20260901-06, idiom seat). This module's whole premise is that the harness gets killed,
    # so it is named here rather than left to be found.
    with tempfile.TemporaryDirectory(prefix="mutation-probe-") as cache:
        probe = subprocess.run([sys.executable, "-c", stmt], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", cwd=REPO,
                               # **`src` as well as the file's own directory** (CHG-20260904-13).
                               # `where` alone imported `tests/test_server.py` with only `tests`
                               # on the path, so `import ai_sdlc_runner` raised and four honest
                               # mutations were reported BROKE. A test module that imports the
                               # package it tests is the ordinary case, not the exception.
                               env={**os.environ,
                                    "PYTHONPATH": os.pathsep.join(
                                        dict.fromkeys([str(REPO / where), str(REPO / "src")])),
                                    "PYTHONPYCACHEPREFIX": cache})
    if probe.returncode == 0:
        return ""
    return (probe.stderr.strip().splitlines() or ["import failed"])[-1]


def run(mutation: Mutation, baseline: Dict[str, bool]) -> bool:
    """Apply, run, restore. The restore is in a `finally` because leaving a mutated tree behind is
    a worse outcome than any result this function can report.

    ## Green first, or the red proves nothing

    `caught = returncode != 0` cannot on its own tell *"the pinning test failed for the pinned
    reason"* from a collection error, an import failure, or an unrelated red that was already
    there. Both review seats named this independently on CHG-20260823-47..50. A mutation that
    merely made a module unimportable would have been "caught" by every test file in the list.

    So each file is run **unmutated** once first, and a mutation whose file is not already green is
    reported as `NO BASELINE` rather than as caught. A red suite no longer turns into twelve
    confident ticks.

    This still does not prove a failure happened for the *right* reason — only that there was a
    green state for the mutation to break. That limit is real and is in the module docstring.
    """
    if not baseline.get(mutation.tests, False):
        print(f"  NO BASELINE  {mutation.says}")
        print(f"               {mutation.tests} does not pass unmutated, so a failure here would "
              f"prove nothing.")
        return False
    original = io.open(mutation.path, encoding="utf-8").read()
    found = original.count(mutation.before)
    if found == 0:
        print(f"  ANCHOR GONE  {mutation.says}")
        print(f"               {mutation.path.name} no longer contains the text this mutates. The "
              f"mutation is stale, which is not the same as caught.")
        return False
    if found > 1:
        # `ANCHOR GONE`'s twin, and it was missing (CHG-20260828-01). The write below is
        # `replace(..., 1)`, so an anchor appearing more than once reverts **whichever comes
        # first** — which need not be the guarantee `says` names. The run then reports about a
        # different line, and CAUGHT is the dangerous reading: it looks exactly like coverage.
        #
        # This is not hypothetical. Three shipped mutations were ambiguous when this check was
        # added, and one of them became ambiguous *because a later change added a second copy of
        # its anchor* — nothing said so at the time, and the group went on reporting clean.
        print(f"  AMBIGUOUS    {mutation.says}")
        print(f"               {mutation.path.name} contains this text {found} times, so the "
              f"mutation would revert whichever comes first rather than the one it names. Narrow "
              f"`before` with enough surrounding context to be unique.")
        return False
    mutated = original.replace(mutation.before, mutation.after, 1)
    apply(mutation.path, original, mutated)
    try:
        broke = _import_fails(mutation.path)
        proc = _pytest(mutation.tests)
    finally:
        restore(mutation.path, original)

    summary = next((ln for ln in reversed(proc.stdout.splitlines())
                    if "passed" in ln or "failed" in ln or "error" in ln), "")

    # A mutated module that does not import is not a catch. `returncode != 0` alone reported CAUGHT
    # for it: every test in the file "fails", for a reason that has nothing to do with the guarantee
    # named. `test_no_shipped_mutation_makes_its_file_unparsable` closes the `SyntaxError` half at
    # author time; a module that parses and raises at import — a `NameError` at module scope, a bad
    # import — is the other half (CHG-20260831-07, defect and risk seats).
    #
    # Asked of the **module**, not of pytest's summary line. Reading the summary only caught it when
    # the *test* file happened to import the mutated module at its own module scope: measured, 12 of
    # 32 (tests, module) pairs here do not, and for those the false green survived the fix
    # (CHG-20260901-01, defect seat).
    # `broke` alone. The summary half was how this was first written, and it cannot tell an
    # import failure from an ordinary fixture that raises: both print `1 error`, and the second is
    # a real catch being reported as a non-catch with "re-anchor it" advice for a correctly
    # anchored mutation (CHG-20260901-01, risk seat). The module is asked directly now, so the
    # summary is not needed and is wrong more often than it is right.
    if broke:
        print(f"  BROKE      {mutation.says}")
        print(f"               {broke or summary}")
        print(f"               the mutated module did not import, so this measured nothing about "
              f"the class it names. Re-anchor it.")
        return False

    caught = proc.returncode != 0
    print(f"  {'CAUGHT     ' if caught else 'NOT CAUGHT '}{mutation.says}")
    print(f"               {summary}")
    return caught


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run one group only (e.g. `importer`)")
    parser.add_argument("--recover", action="store_true",
                        help="put back a file a killed run left mutated, then stop")
    args = parser.parse_args()

    # Before anything else. A tree left mutated by a previous run would make every baseline below
    # a measurement of the wrong code.
    restore_on_signal()
    if os.environ.get("MUTATION_IN_FLIGHT"):
        # A mutation run must write its record where the guard looks for it, and this moves it. The
        # override exists for one caller — the child pytest that drives
        # `test_this_repository_has_no_mutation_in_flight` — and a run that honoured it would mutate
        # source while `tools/.mutation-in-flight.json` stayed absent: `--recover` from an ordinary
        # shell then says "nothing in flight; the tree is as it should be" and exits 0 over a
        # mutated file, and the record is the lock, so a second run takes it uncontended.
        #
        # CHG-20260830-09 claimed a leaked value "points the harness at a file it will not find,
        # which fails loudly". It does not: `begin()` *creates* the record, so every writable value
        # is the silent case. Measured, and made true here rather than restated
        # (CHG-20260831-01, risk seat).
        raise SystemExit(
            f"MUTATION_IN_FLIGHT is set ({os.environ['MUTATION_IN_FLIGHT']}), which moves the "
            f"in-flight record there instead of {DEFAULT_IN_FLIGHT}. A mutation run must write it "
            f"where the stranded-tree guard reads it. Unset the variable and run again.")

    said = recover()
    if args.recover:
        # Before the refusal below, not after it — though the ordering changes nothing, and the
        # comment that shipped here said otherwise. It claimed the old order meant `--recover`
        # "exited 1 without ever reaching this branch, so the documented way out could not be
        # taken". Measured: both orderings produce byte-identical output and both exit 1, because
        # the refusal comes from `recover()` itself. The defect the reorder claimed to fix did not
        # exist; this order is simply the one that reads correctly (CHG-20260831-01, conformance).
        if said is None:
            print("nothing in flight; the tree is as it should be")
        return 1 if said and said.startswith("REFUSING") else 0
    if said and said.startswith("REFUSING"):
        # Refuse here rather than at the first `apply()`. That is minutes of baselines away, and
        # `apply` sits outside `run`'s try/finally, so the exception left main() as a traceback with
        # no summary line at all (CHG-20260830-06, defect seat).
        raise SystemExit(1)

    chosen = [m for m in MUTATIONS if not args.only or m.group == args.only]
    if not chosen:
        groups = sorted({m.group for m in MUTATIONS})
        raise SystemExit(f"no mutations in group {args.only!r}; have {groups}")

    print(f"{len(chosen)} mutation(s)\n")
    # Every file the chosen mutations touch, unmutated, once.
    baseline: Dict[str, bool] = {}
    for tests in sorted({m.tests for m in chosen}):
        green = _pytest(tests).returncode == 0
        baseline[tests] = green
        print(f"  {'baseline ok  ' if green else 'BASELINE RED '}{tests}")
    print()
    try:
        missed = [m for m in chosen if not run(m, baseline)]
    except MutationInFlight as blocked:
        # The tool's own refusal shape, not a traceback -- this is an operator telling
        # them what to do, the same as the unknown-group refusal above.
        raise SystemExit(str(blocked)) from None
    print()
    if missed:
        # "NOT caught" is one of five outcomes `run` returns False for, and the other four are not
        # a missing test at all: `ANCHOR GONE` means the code moved, `AMBIGUOUS` means the anchor
        # appears twice, `NO BASELINE` means the file was already red. Saying "a test names a
        # guarantee it does not check" about those sends a reader to write a test for something
        # that may already be pinned, while the real fault goes unnamed. The per-mutation lines
        # above say which is which; this one stops claiming to know (CHG-20260831-06, defect seat).
        print(f"{len(missed)} of {len(chosen)} did not report CAUGHT. Read the lines above for "
              f"which: a missing test, a stale anchor, a duplicated anchor, a red baseline, or a "
              f"module that would not import are five different faults, and only the first is "
              f"about coverage:")
        for m in missed:
            print(f"  - {m.says}  ({m.tests})")
        return 1
    print(f"all {len(chosen)} caught. This says the named classes are pinned. It does not say the "
          f"suite is complete — see this file's docstring.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
