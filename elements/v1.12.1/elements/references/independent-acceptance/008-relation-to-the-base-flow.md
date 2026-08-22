## Relation to the base flow

- Extends this skill's `acceptance-verification`: same "align to source, evidence per item, run what's scriptable", but upgrades "who verifies and under how many scenarios" to **independent + multi-scenario**.
- Pairs with `cross-agent`: the verifying agent gets the criteria and current result via docs/, no verbal handoff from the implementer.
- Pairs with `ci-cd` (optional): the scenarios that can be automated (clean environment, many inputs, regression) are run repeatedly by the pipeline.
