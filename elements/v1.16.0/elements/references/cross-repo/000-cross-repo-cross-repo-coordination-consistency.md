---
name: cross-repo
description: >
  Cross-repo coordination and consistency: when one requirement or change spans multiple git repos
  (e.g. frontend + backend + shared lib), governance docs are scattered across repos, leading to
  contract mismatches, "which repo is the source of truth?", and half-done changes (changed repo A,
  forgot repo B). Read this when a requirement touches multiple repos, repos share a contract
  (API / data format / events), or you take over a multi-repo system. Covers authority source +
  local view + pointer, cross-repo coordinated change (XCHG), cross-repo anti-drift, and integration
  acceptance. Applies to solo and teams.
---

# cross-repo — cross-repo coordination & consistency

> 語言 / Language: [繁體中文](cross-repo.zh-tw.md) · **English**

