## Multi-scenario verification

Verify each criterion under several scenarios for real coverage:
- **Different inputs/boundaries**: normal, boundary, abnormal, empty and extreme.
- **Different environments**: reinstall/rebuild in a clean environment, then run tests (catches "works on my machine" issues).
- **Different entry points**: unit, API, and end-to-end — not just one.
- **Different agents splitting the work**: when needed, several agents each verify a slice (e.g. A functional correctness, B compatibility/regression, C non-functional), then aggregate.

