## The cycle

1. **RED** — from the task's `test:` line, write the smallest failing test first and **run it to see it fail**. A test you never saw fail proves nothing (it may be testing nothing).
2. **GREEN** — write the **minimum** production code that makes it pass. Resist building ahead of the test; the next task has its own tests.
3. **REFACTOR** — with everything green, clean names/duplication/structure. Tests stay green throughout; behavior changes belong to a new RED, not to refactoring.

