# Third-party notices — ai-sdlc-autopilot

The execution methodology in this skill is adapted from **Superpowers** by Jesse Vincent (obra)
— <https://github.com/obra/superpowers> — under the MIT License. Adapted concepts (no source
code copied): the plan's Global Constraints / per-task Interfaces blocks; single-reviewer dual
verdict (spec + quality) with a legitimate "cannot-verify from diff" outcome; end-of-run
whole-branch review; test-driven development and systematic-debugging discipline. All adapted
material has been rewritten as platform-neutral contracts that land in the ai-sdlc ledger.

## MIT License (Superpowers)

Copyright (c) 2025 Jesse Vincent

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Matt Pocock's agent skills (requirement interview + user stories)

Two contracts in this skill are adapted from **mattpocock/skills** by Matt Pocock —
<https://github.com/mattpocock/skills> — under the MIT License. Adapted concepts (no source code
copied):

- **The user-stories section of the CHG template** — adapted from the `to-spec` skill's spec
  template (Problem / Solution / User Stories / Implementation Decisions), specifically the
  "As a &lt;role&gt;, I want &lt;capability&gt;, so that &lt;benefit&gt;" form and the demand that the list
  cover every aspect rather than the happy path alone.
- **The interview discipline in `requirement-analysis`** — adapted from the `grilling` / `grill-me`
  skills: walk the decision tree one question at a time, give a recommended answer with each
  question, look up facts from the environment instead of asking, and treat the user's
  confirmation of shared understanding as the stopping condition.

**Differences from the originals.** The upstream `to-spec` publishes its spec to an issue tracker;
here the stories live **inside the CHG** — this suite forbids a parallel ledger, so one artifact
carries plan, decisions, and stories together, and the stories become the first-choice source of
acceptance criteria in the ACC. The upstream `grill-with-docs` writes separate ADR files; this
suite's CHG "Decisions & trade-offs" table already serves that role, so no ADR directory is
created. Upstream skills are user-invoked slash commands; here the same discipline is written into
the staged flow that the governance layer already runs.

## MIT License (mattpocock/skills)

Copyright (c) Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Note

The `ai-sdlc-autopilot` skill carries its own third-party notice (Superpowers, MIT) at
`skills/ai-sdlc-autopilot/THIRD-PARTY-NOTICES.md`, and the suite plugin carries one for
i-have-adhd at `plugins/ai-sdlc-suite/THIRD-PARTY-NOTICES.md`.
