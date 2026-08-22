## Writing tips

- **Every item needs evidence, and evidence must be re-runnable**: a "Pass" comes with a command + its key output, or a file/line pointer a reviewer can open — not a narrative claim. A "Pass" without a reproducible check is treated as unverified.
- **Run what's programmatically checkable**: for criteria checkable by script/test, actually run them, don't visually inspect.
- **Make failures actionable**: write the gap and suggested handling clearly, and point to `modification-guide` to form a fix loop.
- **Check structure consistency**: not only whether the feature works, but whether the implementation drifted from the structure docs; if so, route back to `modification-guide` to sync.
- **Align to source, don't expand**: only verify the criteria agreed up front; if you discover a new requirement, go through the requirement/modification flow — don't smuggle it into acceptance.

