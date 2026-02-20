"""
Integration test conftest — real API key capture and singleton reset.

Keys are captured at module-load time (before any monkeypatching by the parent
conftest's autouse mock_env_vars fixture). This is the only safe moment to read them.
"""
import os
import pytest

# Capture BEFORE any monkeypatching (module-load time is the only safe moment)
_REAL_OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
_REAL_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


@pytest.fixture(autouse=True)
def require_real_api_keys(monkeypatch):
    """
    Skip integration test if real API keys are not present.
    Override the fake keys injected by tests/conftest.py mock_env_vars fixture.
    Reset guardrail singleton clients so they reinitialise with real keys.
    """
    if not _REAL_OPENAI_KEY or _REAL_OPENAI_KEY.startswith("test-"):
        pytest.skip("OPENAI_API_KEY not configured — skipping integration test")
    if not _REAL_ANTHROPIC_KEY or _REAL_ANTHROPIC_KEY.startswith("test-"):
        pytest.skip("ANTHROPIC_API_KEY not configured — skipping integration test")

    # Override fakes from parent conftest
    monkeypatch.setenv("OPENAI_API_KEY", _REAL_OPENAI_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", _REAL_ANTHROPIC_KEY)

    # Reset lazy singletons so they reinitialise with the real keys
    import agent.services.guardrail as gm
    gm._openai_client = None
    gm._anthropic_client = None
