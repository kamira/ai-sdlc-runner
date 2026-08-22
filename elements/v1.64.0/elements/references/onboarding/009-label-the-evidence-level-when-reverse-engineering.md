### Label the evidence level when reverse-engineering

Everything derived from existing code must be labelled:

| Label | Meaning |
|---|---|
| **Observed** | Readable directly from the code (this module imports that one) |
| **Inferred** | Intent deduced from evidence (this looks like it supports multi-tenancy) |
| **Unknown** | Cannot tell; a human has to answer |

The cost of skipping the labels is concrete: **an accidental implementation, a historical defect,
or even dead code acquires normative status by being written into a structure document.**
"Unknown" is not a failure, it is a to-do item; writing "unknown" as "inferred" is the failure.

