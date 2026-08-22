## Why this format

A plan drives an autopilot only if every task is **independently executable and independently checkable**: an agent that sees nothing but the Global Constraints + one task entry must be able to build it, and a reviewer that sees nothing but the same brief + the diff must be able to judge it. Prose plans ("then improve the API") fail both tests.

