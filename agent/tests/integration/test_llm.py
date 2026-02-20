"""
Integration tests — LLM connectivity.

Verifies that the three LLM backends the agent uses (Claude Haiku, Claude Sonnet,
GPT-4o-mini) respond correctly to simple prompts. Tests skip gracefully when real
API keys are absent.

Timeout: 30s per test (network latency + model inference).
"""
import pytest
import anthropic
import openai

from tests.integration.conftest import _REAL_OPENAI_KEY, _REAL_ANTHROPIC_KEY


@pytest.mark.timeout(30)
class TestClaudeLLM:
    """Anthropic Claude API connectivity."""

    async def test_claude_haiku_responds(self):
        """Claude Haiku (claude-haiku-4-5-20251001) answers a simple arithmetic question."""
        client = anthropic.AsyncAnthropic(api_key=_REAL_ANTHROPIC_KEY)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": "What is 2 + 2? Reply with only the number."}],
        )
        response_text = message.content[0].text.strip()
        assert "4" in response_text, f"Expected '4' in response, got: {response_text!r}"

    async def test_claude_sonnet_solves_arithmetic(self):
        """Claude Sonnet (claude-sonnet-4-6) solves a multiplication problem."""
        client = anthropic.AsyncAnthropic(api_key=_REAL_ANTHROPIC_KEY)
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": "What is 12 times 15? Reply with only the number.",
                }
            ],
        )
        response_text = message.content[0].text.strip()
        assert "180" in response_text, f"Expected '180' in response, got: {response_text!r}"


@pytest.mark.timeout(30)
class TestOpenAILLM:
    """OpenAI GPT API connectivity."""

    async def test_openai_gpt_answers_history(self):
        """GPT-4o-mini answers a basic history question about Julius Caesar."""
        client = openai.AsyncOpenAI(api_key=_REAL_OPENAI_KEY)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=64,
            messages=[
                {
                    "role": "user",
                    "content": "In one sentence: who was Julius Caesar?",
                }
            ],
        )
        response_text = response.choices[0].message.content.strip().lower()
        assert "rome" in response_text or "roman" in response_text, (
            f"Expected 'rome' or 'roman' in response, got: {response_text!r}"
        )
