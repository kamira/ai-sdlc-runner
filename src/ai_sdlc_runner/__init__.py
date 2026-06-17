"""ai-sdlc-runner — external orchestrator that drives the ai-sdlc skill.

The runner *references* the skill (never copies it) and *reads or calls* the skill's
governance logic (halt-points, role table, CHG/ACC fields) rather than re-implementing it.
Dependency is one-way: the runner depends on the skill; the skill never depends on the runner.
"""

__version__ = "0.1.0"
