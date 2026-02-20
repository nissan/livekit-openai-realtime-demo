"""
Unit tests for agent/services/guardrail.py.

All OpenAI and Anthropic calls are mocked — no network access needed.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_moderation_response(
    flagged: bool,
    categories: list[str] | None = None,
    scores: dict[str, float] | None = None,
):
    """Build a minimal mock that matches the OpenAI moderation response shape.

    Args:
        flagged: Overall flagged status.
        categories: List of category names that are flagged (boolean True).
        scores: Optional dict of category_name → score overrides.
                Defaults to 0.9 for harassment if in categories, else 0.01.
    """
    categories = categories or []
    scores = scores or {}

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

    def _score(key: str, default: float) -> float:
        return scores.get(key, default)

    score_obj = SimpleNamespace(
        harassment=_score("harassment", 0.9 if "harassment" in categories else 0.01),
        harassment_threatening=_score("harassment/threatening", 0.01),
        hate=_score("hate", 0.01),
        hate_threatening=_score("hate/threatening", 0.01),
        sexual=_score("sexual", 0.01),
        sexual_minors=_score("sexual/minors", 0.01),
        violence=_score("violence", 0.9 if "violence" in categories else 0.01),
        violence_graphic=_score("violence/graphic", 0.01),
        self_harm=_score("self-harm", 0.01),
        self_harm_intent=_score("self-harm/intent", 0.01),
        self_harm_instructions=_score("self-harm/instructions", 0.01),
        illicit=_score("illicit", 0.01),
        illicit_violent=_score("illicit/violent", 0.01),
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

    async def test_multiple_categories_all_returned(self):
        """When both harassment and violence are flagged, both appear in categories."""
        mock_response = _make_moderation_response(
            flagged=True, categories=["harassment", "violence"]
        )

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)
            from agent.services.guardrail import check
            result = await check("Some multiply-flagged text")

        assert result.flagged is True
        assert "harassment" in result.categories
        assert "violence" in result.categories

    async def test_highest_score_is_maximum_across_categories(self):
        """highest_score reflects the maximum score across all categories."""
        mock_response = _make_moderation_response(
            flagged=True,
            categories=["harassment", "violence"],
            scores={"harassment": 0.9, "violence": 0.7},
        )

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)
            from agent.services.guardrail import check
            result = await check("Some text with multiple scores")

        assert result.highest_score == pytest.approx(0.9)

    async def test_empty_text_does_not_crash(self):
        """Passing empty string to check() must not raise an exception."""
        mock_response = _make_moderation_response(flagged=False)

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)
            from agent.services.guardrail import check
            result = await check("")

        assert result.flagged is False


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
