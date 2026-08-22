## Cross-repo coordinated change (XCHG)

- A logical change spanning repos → open a **coordinated change `XCHG-YYYYMMDD-NN`** at the authority, describing the overall intent, which repos are involved, and how the contract version changes.
- Each repo's **local CHG** links back to that XCHG in its "Related" field; the XCHG lists each repo's child CHG → **two-way traceability**.
- **Order of contract changes**: the authority changes the contract first (version +1) → each consuming repo opens a CHG to follow and updates its local pointer to the new version. Change the contract first, then the consumers, so consumers don't build against a stale contract.

