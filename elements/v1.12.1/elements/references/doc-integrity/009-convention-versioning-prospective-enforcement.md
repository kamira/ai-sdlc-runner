## Convention versioning (prospective enforcement)

Records carry `Skill: ai-sdlc vX.Y` — the convention version they were written under. **Newer rules apply prospectively**: don't retro-fail records produced under an older convention (the machine lint hard-requires only fields that have existed since v1.0; stricter checks are opt-in flags like `--require-commit`). On entry, compare the running skill version with the versions in recent records: records **newer** than the installed skill → the skill is outdated, upgrade before working (see handshake).

