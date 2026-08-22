## Guarding against bias

- **Self-confirmation bias**: self-verification tends to prove "it's right"; independent acceptance tends to find "where it breaks".
- **Consensus bias (specific to agent teams)**: if multiple agents share the same (possibly wrong) assumption or the same polluted context, they "fail together". Countermeasure: anchor criteria to the source requirement/docs, and run at least one verification scenario in a clean context (without the implementation conversation).
- **Cross-model review (break same-model blind spots)**: one model carries the same training biases and blind spots — if implementation and verification use the same model, some errors are "systematically invisible to both". **Prefer a different model/provider for the verifier** (cross-model review); especially for high-risk changes. Record the implementer model and verifier model in the ACC for traceability. If the platform has only one model, fall back to "clean context + a different role/system setup" to reduce correlation, and note this limitation in the ACC.
- **Blind check (advanced)**: don't tell the verifying agent the "expected answer" — give only criteria and result, and let it judge independently.

