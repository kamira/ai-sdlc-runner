## Relationship to the existing flow

- This file comes **before** handshake: the handshake assumes the ledger can be found; this file
  is what makes that true.
- Steps 2 and 3 of `init` are requirement-analysis and structure-design; this file does not
  restate their content.
- Acceptance for `adopt` goes through acceptance-verification. Adoption **is not** acceptance.
- The location decision governs every machine assist's search scope — `doc_integrity_check` and
  `governance_health` both go through `ledger_roots()` and hardcode no directory name.
