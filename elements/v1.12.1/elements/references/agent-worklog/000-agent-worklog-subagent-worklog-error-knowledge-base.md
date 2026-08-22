---
name: agent-worklog
description: >
  Subagent worklog and error knowledge base: when one agent dispatches subagents to run tasks (which
  can happen solo or in a team), each subagent must first write down "what it's about to do", and on
  error must record "what error + how it was resolved" before continuing; the orchestrating agent
  then consolidates all errors into a knowledge base so future tasks don't repeat them. Read this
  when you're about to dispatch subagents, or when you're a dispatched subagent about to start.
---

# agent-worklog — subagent worklog & error knowledge base

> 語言 / Language: [繁體中文](agent-worklog.zh-tw.md) · **English**

