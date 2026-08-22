## What the runner actually checks

Three things, and it installs nothing:

1. The declared **kind** exists in `assets/interaction_kinds.json` (a table you can extend).
2. The declared **command** runs and exits zero.
3. The declared **artefacts really appeared** — and are non-empty.

The third one carries the weight. Without it `--interaction-cmd 'echo ok'` passes, which is
exactly what this gate is for. Exit zero is a claim; an artefact is evidence.

