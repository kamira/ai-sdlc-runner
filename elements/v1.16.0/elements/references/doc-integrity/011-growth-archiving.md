## Growth & archiving

`docs/changes/` and `docs/acceptance/` grow without bound; past a threshold (suggest ~50 closed records, or quarterly) entry scans get slow and noisy:
- Move **fully closed** records (CHG Accepted + its ACC) into `docs/changes/archive/` / `docs/acceptance/archive/`; never archive open ones.
- Keep one index line per archived record in `docs/changes/INDEX.md` (id / title / status / links) so traceability survives archiving.
- Entry checks (handshake, `doc_integrity_check.py`) scan only non-archived records.
