"""
Shared pytest fixtures for agent unit tests.

All external API calls (OpenAI, Anthropic, Supabase, LiveKit) are mocked here.
Tests run without Docker or network access.
"""
import os
import pytest


@pytest.fixture(autouse=True)
def mock_env_vars(monkeypatch):
    """Ensure required env vars exist so lazy singletons don't raise KeyError."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.livekit.io")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test-lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "test-lk-secret")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-lf-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-lf-secret")
