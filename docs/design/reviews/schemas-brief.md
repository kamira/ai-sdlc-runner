You are an INDEPENDENT REVIEW SEAT on the repository at:
C:/Users/haruharu/Documents/GitHub/ai-sdlc-runner/.claude/worktrees/ai-sdlc-handshake-a967df

Another seat is reviewing the same thing at the same time. You will not see their verdict and they
will not see yours. A split does not pass. Do not soften.

THE SUBJECT: the SCHEMA DESIGN of this project. Not the prose — the shapes themselves.

Fourteen schemas are catalogued in docs/SCHEMAS.md. Thirteen are shipped and in use; the
fourteenth (a SQLite DDL) is proposed and unbuilt. Review the DESIGN OF THE SHAPES.

READ FIRST (open them, do not assume):
- docs/SCHEMAS.md                          <- the catalogue under review
- src/ai_sdlc_runner/graph.py              <- Node, MODES, validate()
- src/ai_sdlc_runner/workorder.py          <- WORK_ORDER_FIELDS, NODE_SPEC_FIELDS, VERDICT_FIELDS
- src/ai_sdlc_runner/policy.py             <- operations, PERMANENT_HALT_KINDS, roles, gates
- src/ai_sdlc_runner/conversations.py      <- the conversation document, turn kinds, CSV columns
- src/ai_sdlc_runner/models.py             <- the registry, and reach as a computed property
- src/ai_sdlc_runner/engine.py             <- AskJournal entry, RunReport
- src/ai_sdlc_runner/settings.py           <- Settings
- src/ai_sdlc_runner/attachments.py        <- Attachment
- docs/design/sqlite-only.md               <- the proposed DDL, already through one review round
- examples/plan.json + examples/agent.py   <- a plan and answer contract that actually run
- docs/defect-log.md                       <- how defects get found here

WHAT TO JUDGE — the shapes, not the wording:

1. ACCURACY. Is docs/SCHEMAS.md true of the code TODAY? Check field-by-field, not by counting.
   A catalogue that drifts is worse than none, because people stop reading the source.
2. CLOSEDNESS. Three schemas are called "closed" — node spec, work order, model registry. Is each
   actually enforced closed, in code, on every path in? Or is "closed" a name?
3. COMPLETENESS. Is any schema MISSING from the catalogue? Anything durable, or crossing a process
   boundary, that has a shape nobody wrote down?
4. CORRECTNESS OF SHAPE. For each schema ask: is there a field nothing reads? Two fields that can
   disagree? A required thing that is optional, or the reverse? A type that permits a value the
   code cannot handle? Somewhere the same fact is stored twice?
5. EVOLUTION. What happens when a shape changes? Which schemas are versioned, which are not, and
   which SHOULD be? conversations.py has SCHEMA = 1; nothing else appears to.
6. THE SQLITE DDL specifically. It has already been through one round (see
   docs/design/reviews/sqlite-only-*.md). Assume it still has a defect. Find it.

Check by running things (python3, PYTHONPATH=src, PYTHONUTF8=1, pytest all work). Prove claims.

The house standard for a finding:
- checkable. Quote the file and line, or give a command that shows it.
- "a name standing in for a constraint" and "a coarse check answering safe about something it had
  not examined" are this repository's two most frequent defects. Hunt for both.
- Do NOT average or split a difference. Say which is right.

OUTPUT, in markdown:
1. VERDICT on the schema design: exactly one of `sound`, `sound with changes`, `not sound`
2. The single worst schema, named, and why
3. Findings per schema — a table: schema -> sound / needs change / broken, with evidence
4. Schemas that are MISSING from the catalogue
5. Anything you would DELETE or MERGE — redundancy is a defect too
6. What you could not check, and what you would need

Vague approval is worse than nothing.
