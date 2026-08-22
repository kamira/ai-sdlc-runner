## Workflow

1. Read the Guideline and list the requirements the structure must answer (especially P0 and non-functional ones).
2. Produce abstract→concrete: logical → design → data → directory (order can flex per project, but all four must exist).
3. Verify the four are mutually consistent: logical modules should map to directory folders, design components, and data entities.
4. In each document, note which requirement IDs it answers (traceable back to the Guideline's FR/NFR).
5. **Hand back to the user with the diagrams, for review and correction, before any implementation.** Of the four structure documents, the diagrams are the part that most needs a human pass — they are the only thing that lets someone see at a glance that "you wired that module to the wrong side", and that is the mistake this stage catches cheapest and every later stage pays most for. Show them, correct them as directed, and keep correcting until the user confirms; **do not proceed before they do**. The user may decide not to look (note it in the Guideline's "AI development conventions"), but **the default is to draw** — nothing said means draw.

