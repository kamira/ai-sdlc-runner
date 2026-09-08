"""Swap in a hypothetical graph, validate it, and put the real one back — once, for three files.

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
against 39 test-function signatures. And a fixture would not merely cost more: fixture teardown runs
*after* the test body, so a test that catches the expected `GraphError` and then looks at
`graph.NODES` would read the hypothetical graph. The `try/finally` below is what makes that safe,
and once it is kept the teardown buys nothing.
"""
from ai_sdlc_runner import graph


def validate_with(nodes):
    """Rebind both views to `nodes`, `validate()`, and put the shipped graph back whatever happens.

    Exception-safe by construction: both originals are captured before anything is rebound, and the
    `finally` restores the objects themselves rather than rebuilding them.
    `test_graph_validation.py::test_the_shared_swap_puts_both_views_back_when_validate_raises`
    asserts that by identity — 39 test functions share this one `finally`, and until that test was
    written nothing named could notice it going.
    """
    original_nodes, original_by_id = graph.NODES, graph.BY_ID
    graph.NODES = nodes
    graph.BY_ID = {n.id: n for n in nodes}
    try:
        graph.validate()
    finally:
        graph.NODES, graph.BY_ID = original_nodes, original_by_id
