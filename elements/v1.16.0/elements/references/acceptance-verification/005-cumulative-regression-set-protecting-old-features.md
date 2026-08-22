## Cumulative regression set (protecting old features)

Per-change acceptance verifies "did we build the new thing right"; on its own, nothing verifies "did we break old things". So acceptance promises accumulate:

- **Registry**: `docs/acceptance/regression.md` — one line per **programmatically checkable** criterion from past ACCs: criterion, how to run (test/script pointer), source ACC, scope tags (module/area). Wrap run pointers in backticks (e.g. `` `tests/test_x.py::test_y` ``) — the lint verifies the pointed file still exists; a deleted test is a silently void promise.
- **Deposit**: when closing an ACC, add its scriptable criteria to the registry (no duplicates; extend scope tags instead).
- **Run**: for **medium/high-risk** changes, run the registry items whose scope tags intersect this CHG's impact scope. **Breaking an old criterion = Fail**, even if every new criterion passes — route it back like any other failure. Low risk: run what the impact scope obviously touches.
- The registry points at tests/scripts rather than replacing the test suite — its job is to keep past acceptance promises executable and actually re-run.

