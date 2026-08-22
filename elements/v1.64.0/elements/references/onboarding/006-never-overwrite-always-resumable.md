## Never overwrite, always resumable

Both `init` and `adopt` are multi-step flows that write files, and the session can end at any
step (see handshake, "last-act discipline"). So both must:

- **Never overwrite an existing file.** If it exists, skip it and name it, and let a human decide
  whether to merge. "Re-running is faster" is not a reason to overwrite someone's corrections.
- **Be resumable**: a re-run fills only what is missing and rebuilds nothing that already exists;
  an interruption leaves no half-set.
- **Print the plan first**: before writing, list which files will be created, marking existing
  ones as skipped.

