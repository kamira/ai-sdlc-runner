## init — starting from zero

1. Decide the location (above) and write it into the Guideline header.
2. requirement-analysis → `<root>/ai-guideline.md`.
3. structure-design → `<root>/structure/{directory,logical,design,data}.md`.
4. Create `<root>/changes/`, `<root>/acceptance/`, `<root>/knowledge/` (a zero-entry INDEX plus a
   seed `vocabulary.json` — see knowledge, "found it first").
5. Create a root `AGENTS.md`; every tool-specific convention file present (`CLAUDE.md`,
   `GEMINI.md`, `.cursorrules`, `.github/copilot-instructions.md`, …) keeps a **two-line stub**
   pointing at it, carrying no content of its own (duplicates drift).

