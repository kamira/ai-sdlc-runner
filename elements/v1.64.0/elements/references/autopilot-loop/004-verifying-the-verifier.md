### Verifying the verifier

The gates are code, and an agent can write code. Deleting `require_test_command` from the
precondition tuple, or setting the kill-rate threshold to zero, leaves every existing test green.
Two things guard against that:

- `verifier_integrity.py` anchors the SHA-256 of the files that make up the checking apparatus.
  Re-anchoring requires naming the authorising CHG, so changing a verifier stops being a silent
  edit and becomes a signed ledger entry.
- `test_gates_wired.py` asserts by AST that each gate is still wired into the flow — the cheapest
  way to defeat a gate is to remove it, and a removed gate does not complain.

Escape hatches (`--allow-untested`, a below-floor `--min-kill-rate`, `--no-commit`) are printed
and written to the handshake; dropping the threshold below 60 additionally requires an
`Escape-hatch:` line in the CHG.

