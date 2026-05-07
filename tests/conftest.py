from __future__ import annotations

import pytest

from interview_agent.app.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_live_model_settings(monkeypatch: pytest.MonkeyPatch):
    for key in (
        "INTERVIEW_AGENT_LLM_BASE_URL",
        "INTERVIEW_AGENT_LLM_API_KEY",
        "INTERVIEW_AGENT_EMBEDDING_BASE_URL",
        "INTERVIEW_AGENT_EMBEDDING_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
