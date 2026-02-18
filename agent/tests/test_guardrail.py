"""
Unit tests for agent/services/guardrail.py.

All OpenAI and Anthropic calls are mocked — no network access needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_moderation_response(flagged: bool, categories: list[str] | None = None):
    """Build a minimal mock that matches the OpenAI moderation response shape."""
    categories = categories or []

    # Use SimpleNamespace so attribute access returns actual booleans/floats
    from types import SimpleNamespace

    cat_obj = SimpleNamespace(
        harassment="harassment" in categories,
        harassment_threatening="harassment/threatening" in categories,
        hate="hate" in categories,
        hate_threatening="hate/threatening" in categories,
        sexual="sexual" in categories,
        sexual_minors="sexual/minors" in categories,
        violence="violence" in categories,
        violence_graphic="violence/graphic" in categories,
        self_harm="self-harm" in categories,
        self_harm_intent="self-harm/intent" in categories,
        self_harm_instructions="self-harm/instructions" in categories,
        illicit="illicit" in categories,
        illicit_violent="illicit/violent" in categories,
    )

    score_obj = SimpleNamespace(
        harassment=0.9 if "harassment" in categories else 0.01,
        harassment_threatening=0.01,
        hate=0.01,
        hate_threatening=0.01,
        sexual=0.01,
        sexual_minors=0.01,
        violence=0.01,
        violence_graphic=0.01,
        self_harm=0.01,
        self_harm_intent=0.01,
        self_harm_instructions=0.01,
        illicit=0.01,
        illicit_violent=0.01,
    )

    result = SimpleNamespace(
        flagged=flagged,
        categories=cat_obj,
        category_scores=score_obj,
    )

    response = SimpleNamespace(results=[result])
    return response


class TestCheck:
    async def test_clean_text_returns_not_flagged(self):
        mock_response = _make_moderation_response(flagged=False)

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)
            from agent.services.guardrail import check
            result = await check("What is 7 times 8?")

        assert result.flagged is False
        assert result.categories == []

    async def test_flagged_text_returns_flagged_with_categories(self):
        mock_response = _make_moderation_response(
            flagged=True, categories=["harassment"]
        )

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)
            from agent.services.guardrail import check
            result = await check("Some inappropriate text")

        assert result.flagged is True
        assert "harassment" in result.categories

    async def test_check_exception_returns_not_flagged(self):
        """On API error, fail safe: do not flag."""
        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(
                side_effect=Exception("API error")
            )
            from agent.services.guardrail import check
            result = await check("some text")

        assert result.flagged is False
        assert result.categories == []
        assert result.highest_score == 0.0


class TestRewrite:
    async def test_rewrite_returns_rewritten_text(self):
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Rewritten safe text")]

        with patch("agent.services.guardrail._anthropic_client") as mock_client:
            mock_client.messages.create = AsyncMock(return_value=mock_message)
            from agent.services.guardrail import rewrite
            result = await rewrite("original problematic text")

        assert result == "Rewritten safe text"

    async def test_rewrite_exception_returns_safe_fallback(self):
        with patch("agent.services.guardrail._anthropic_client") as mock_client:
            mock_client.messages.create = AsyncMock(
                side_effect=Exception("Anthropic error")
            )
            from agent.services.guardrail import rewrite
            result = await rewrite("original text")

        # Should return the hardcoded safe fallback
        assert "learn" in result.lower() or "help" in result.lower()
        assert len(result) > 0


class TestCheckAndRewrite:
    async def test_clean_text_passes_through_unchanged(self):
        clean_response = _make_moderation_response(flagged=False)

        with patch("agent.services.guardrail._openai_client") as mock_oai:
            mock_oai.moderations.create = AsyncMock(return_value=clean_response)
            from agent.services.guardrail import check_and_rewrite
            result = await check_and_rewrite(
                "What is the Pythagorean theorem?",
                session_id="session-123",
                agent_name="math",
            )

        assert result == "What is the Pythagorean theorem?"

    async def test_flagged_text_triggers_rewrite(self):
        flagged_response = _make_moderation_response(
            flagged=True, categories=["harassment"]
        )
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Here is a school-appropriate response.")]

        with (
            patch("agent.services.guardrail._openai_client") as mock_oai,
            patch("agent.services.guardrail._anthropic_client") as mock_ant,
            patch("asyncio.create_task"),  # suppress fire-and-forget log task
        ):
            mock_oai.moderations.create = AsyncMock(return_value=flagged_response)
            mock_ant.messages.create = AsyncMock(return_value=mock_message)

            from agent.services.guardrail import check_and_rewrite
            result = await check_and_rewrite(
                "flagged content here",
                session_id="session-123",
                agent_name="test",
            )

        assert result == "Here is a school-appropriate response."
