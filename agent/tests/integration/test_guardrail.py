"""
Integration tests — guardrail service with real APIs.

Calls the real omni-moderation-latest endpoint and real Claude Haiku rewriter
via the guardrail service functions directly (not mocked).

Tests skip gracefully when real API keys are absent.
Timeout: 30s per test.
"""
import pytest

from agent.services.guardrail import check, rewrite, check_and_rewrite


@pytest.mark.timeout(30)
class TestModerationCheck:
    """OpenAI omni-moderation-latest — clean content should not be flagged."""

    async def test_clean_math_question_not_flagged(self):
        """A benign math question should not be flagged by moderation."""
        result = await check("What is 7 times 8?")
        assert result.flagged is False, (
            f"Expected clean math question not to be flagged, got flagged=True "
            f"categories={result.categories}"
        )
        assert result.highest_score < 0.5, (
            f"Expected highest_score < 0.5 for clean text, got {result.highest_score:.4f}"
        )

    async def test_clean_history_question_not_flagged(self):
        """A standard history question should not be flagged by moderation."""
        result = await check("Who was Julius Caesar?")
        assert result.flagged is False, (
            f"Expected clean history question not to be flagged, got flagged=True "
            f"categories={result.categories}"
        )


@pytest.mark.timeout(30)
class TestGuardrailRewrite:
    """Claude Haiku rewriter — verifies live rewrite capability."""

    async def test_rewrite_returns_non_empty_string(self):
        """Rewriting a valid educational text should return a non-empty string."""
        result = await rewrite(
            "The lesson covered the history of medieval warfare."
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert len(result) > 0, "Expected non-empty rewrite result"

    async def test_check_and_rewrite_passes_clean_text(self):
        """Clean text should pass through check_and_rewrite unchanged."""
        input_text = "What is the capital of France?"
        result = await check_and_rewrite(
            text=input_text,
            session_id="integration-test-session",
            agent_name="test",
        )
        assert result == input_text, (
            f"Expected clean text to be returned unchanged, got: {result!r}"
        )
