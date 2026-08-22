---
name: doc-integrity
description: >
  Document anti-drift and verification: ai-sdlc uses docs/ as the basis for later work, so the
  documents themselves must be continuously verified and must not drift from the code or from each
  other — solo development drifts too (you change code and forget to update the docs), and it's
  worse in a team / multi-agent setting. Read this to confirm existing docs are still trustworthy,
  when closing a change, or on takeover. Covers code↔doc bidirectional consistency, doc↔doc
  consistency, scriptable drift detection, and independent review. Applies to solo and teams.
---

# doc-integrity — document anti-drift & verification

> 語言 / Language: [繁體中文](doc-integrity.zh-tw.md) · **English**

