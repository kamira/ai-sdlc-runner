"""Shared pytest fixtures."""
import os
from pathlib import Path

import pytest


@pytest.fixture
def _skill_path():
    """Path to the ai-sdlc skill cache, from AI_SDLC_SKILL_PATH; skip the test if unavailable."""
    p = os.environ.get("AI_SDLC_SKILL_PATH")
    if not p or not Path(p).is_dir():
        pytest.skip("skill cache not provided via AI_SDLC_SKILL_PATH")
    return p
