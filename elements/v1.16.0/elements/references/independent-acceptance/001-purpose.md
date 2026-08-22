## Purpose

When code is done and needs verifying, it **must not be verified by the agent that wrote it** — player as referee tends to test only the happy paths it thought of, reuse its own wrong assumptions, and stay blind to its own blind spots. This requires verification by a **different agent**, under **different scenarios**, aggregated into one ACC. This strengthens the acceptance-verification stage (independent + multi-scenario).

> "Team" is not limited to humans. **AI-agent teams** apply equally: the implementing agent and the verifying agent are different instances/contexts — and that's exactly where the independence comes from.

