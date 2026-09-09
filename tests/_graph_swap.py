"""Swap in a hypothetical graph and put the real one back — once, for the files that do it.

Three helpers: `mutated` builds the hypothetical graph, `validate_with` validates it and restores
before returning, and `swapped_graph` holds it open for a test that needs to look at it.


`graph.py` keeps two views of one graph, `NODES` and `BY_ID`. A test that wants `validate()` to
judge a graph other than the shipped one has to rebind **both** and restore both whatever happens.
Until CHG-20260907-25 three modules each carried their own implementation: `test_graph_validation`
and `test_execution_mode` with bodies that are identical once the docstrings are stripped (they
were recorded as "byte-identical", and are not — one carries a ten-line docstring and one carries
none), and `test_risk_adjudicated` with the same operation over a single node.

**Why both views.** Rehomed from the docstring this replaces, because it is the reason the helper
exists: `validate` compares the two lengths and then traverses `BY_ID`, so a graph rebound in one
view alone is half-validated against the new node and half against the shipped one — and
`engine.walk` executes the node it fetches from `BY_ID`. Since CHG-20260907-10 `validate` refuses
that outright ("the two views of the graph were rebound separately"), and
`test_graph_validation._validate_with_nodes_only` is the deliberate half-swap kept as the
counter-example that rule has to have something to refuse. It is **not** folded in here.

**Why a plain module and not a `conftest.py` fixture.** Both seats of CHG-20260907-10 recommended a
fixture, before the measurement existed; both seats of CHG-20260907-25 reversed that after seeing
it. The helper takes nothing from pytest, `tests/` is already on `sys.path` under the default
`prepend` import mode, and this suite already shares helpers by bare sibling import (`from
test_flow import DECISIONS, SPEC`, in eight modules). So the module costs three import lines
against 44 test-function signatures. And a fixture would not merely cost more: fixture teardown runs
*after* the test body, so a test that catches the expected `GraphError` and then looks at
`graph.NODES` would read the hypothetical graph. The `try/finally` below is what makes that safe,
and once it is kept the teardown buys nothing.
"""
import contextlib
import dataclasses

from ai_sdlc_runner import graph


def mutated(node_id, **changes):
    """The real graph with one node changed — the shape a wrong hand-edit would actually take.

    Two modules carried this as `_mutate`, with one docstring between them and bodies differing
    only by an intermediate variable (CHG-20260908-03). It belongs beside `validate_with` because
    every caller of one calls the other.
    """
    return tuple(dataclasses.replace(n, **changes) if n.id == node_id else n for n in graph.NODES)


@contextlib.contextmanager
def swapped_graph(nodes):
    """Both views rebound to `nodes` for the body, and put back whatever happens.

    `validate_with` cannot serve a test that wants to **look** at the swapped graph — it validates
    and restores, so anything the test asserts runs after the restore. Two tests therefore wrote
    the rebind and the `try`/`finally` out by hand in order to call `graph.module_cycle()` and
    `engine._whole_change_rejected()` against a hypothetical graph. This is that shape, once.

    `validate_with` **is** written in terms of this. The deliberate half-swap in
    `test_graph_validation` is not folded in here, for the reason its own docstring gives — it
    exists to be wrong.
    """
    original_nodes, original_by_id = graph.NODES, graph.BY_ID
    graph.NODES = tuple(nodes)
    graph.BY_ID = {n.id: n for n in graph.NODES}
    try:
        yield graph.NODES
    finally:
        graph.NODES, graph.BY_ID = original_nodes, original_by_id


def validate_with(nodes):
    """Rebind both views to `nodes`, `validate()`, and put the shipped graph back whatever happens.

    Exception-safe by construction: both originals are captured before anything is rebound, and the
    `finally` restores the objects themselves rather than rebuilding them.
    `test_graph_validation.py::test_the_shared_swap_puts_both_views_back_when_validate_raises`
    asserts that by identity — **44 test functions** call `validate_with` (28 in
    `test_graph_validation`, 15 in `test_execution_mode`, 1 in `test_risk_adjudicated`, counted by
    AST), and until that test was written nothing named could notice this `finally` going. An
    earlier figure here said 39 and CHG-20260908-03 re-asserted it without measuring; a seat
    measured it. Two more copies went with it, in that test's docstring and in the mutation
    registry. A third stands in `ACC-20260907-25`, which recorded 39 as its own measurement at the
    time — closed records are not rewritten here, and `test_documented_numbers` excludes
    `docs/acceptance/` for that reason.

    **Written in terms of `swapped_graph` (CHG-20260908-03).** The `with` exits before this returns,
    so the closed-before-return property those 44 functions rest on is unchanged. An earlier draft
    kept a second copy of the rebind here and gave that property as the reason; a seat measured the
    fold and it passes every caller, so the reason was not one. There is one restore in this module
    again, which is what its first line claims.
    """
    with swapped_graph(nodes):
        graph.validate()
