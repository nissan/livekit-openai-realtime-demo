"""
Parametrised routing and guardrail tests using synthetic question fixtures.

Design:
- All routing tests call impl functions directly — no LLM calls needed.
- Guardrail tests mock the OpenAI moderation API response — no harmful content needed.
- Adding a new question category means adding one row to the fixtures file.

Six test classes:
  TestSyntheticMathRouting        10 params — routing to MathAgent
  TestSyntheticHistoryRouting     10 params — routing to HistoryAgent
  TestSyntheticEnglishRouting     10 params — routing to EnglishAgent (dispatch)
  TestSyntheticGuardrailTrigger   13 params — one per moderation category
  TestSyntheticEscalation          6 params — distress signal escalation
  TestAgentSystemPromptValidation  1 test   — structural / static assertions
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

from agent.tests.fixtures.synthetic_questions import (
    MATH_QUESTIONS,
    HISTORY_QUESTIONS,
    ENGLISH_QUESTIONS,
    GUARDRAIL_INPUTS,
    ESCALATION_SIGNALS,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_mock_context(session_id="sess-synthetic", room_name="room-synthetic"):
    """Build a minimal RunContext-like mock with SessionUserdata."""
    from agent.models.session_state import SessionUserdata

    userdata = SessionUserdata(
        student_identity="student-test",
        room_name=room_name,
        session_id=session_id,
    )

    session = MagicMock()
    session.userdata = userdata
    session.history = MagicMock()

    context = MagicMock()
    context.session = session
    return context, userdata


def _make_mock_agent(agent_name="orchestrator"):
    """Minimal agent mock with agent_name attribute."""
    agent = MagicMock()
    agent.agent_name = agent_name
    return agent


def _make_tracer_mock():
    """Return (mock_tracer, mock_span) configured as a sync context manager."""
    mock_span = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_span)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_ctx
    return mock_tracer, mock_span


def _make_moderation_response_for_category(category: str):
    """
    Build a mock OpenAI moderation response with exactly one category flagged.
    The input text is irrelevant — only the category matters.
    """
    # Maps category name → SimpleNamespace attribute name
    cat_attr_map = {
        "harassment": "harassment",
        "harassment/threatening": "harassment_threatening",
        "hate": "hate",
        "hate/threatening": "hate_threatening",
        "sexual": "sexual",
        "sexual/minors": "sexual_minors",
        "violence": "violence",
        "violence/graphic": "violence_graphic",
        "self-harm": "self_harm",
        "self-harm/intent": "self_harm_intent",
        "self-harm/instructions": "self_harm_instructions",
        "illicit": "illicit",
        "illicit/violent": "illicit_violent",
    }

    attr_name = cat_attr_map[category]

    # All False except the target category
    cat_kwargs = {v: False for v in cat_attr_map.values()}
    cat_kwargs[attr_name] = True
    cat_obj = SimpleNamespace(**cat_kwargs)

    # All 0.01 except the target (0.9)
    score_kwargs = {v: 0.01 for v in cat_attr_map.values()}
    score_kwargs[attr_name] = 0.9
    score_obj = SimpleNamespace(**score_kwargs)

    result = SimpleNamespace(
        flagged=True,
        categories=cat_obj,
        category_scores=score_obj,
    )
    return SimpleNamespace(results=[result])


# ---------------------------------------------------------------------------
# 1. TestSyntheticMathRouting — 10 parametrised cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    MATH_QUESTIONS,
    ids=[q.category for q in MATH_QUESTIONS],
)
class TestSyntheticMathRouting:
    async def test_route_to_math_updates_state_and_span(self, question):
        """Routing to math sets userdata, pending question, skip flag, and span attributes."""
        context, userdata = _make_mock_context()
        agent = _make_mock_agent("orchestrator")
        mock_specialist = MagicMock()
        mock_tracer, mock_span = _make_tracer_mock()

        with (
            patch("agent.agents.math_agent.MathAgent") as MockMath,
            patch("agent.tools.routing.tracer", mock_tracer),
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            MockMath.return_value = mock_specialist

            from agent.tools.routing import _route_to_math_impl
            result = await _route_to_math_impl(agent, context, question.question)

        # userdata state
        assert userdata.current_subject == "math"
        assert userdata.skip_next_user_turns == 1

        # returned specialist and pending question
        specialist, announcement = result
        assert specialist._pending_question == question.question

        # OTEL span attributes
        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert span_calls.get("to_agent") == "math"
        assert span_calls.get("question_summary") == question.question
        assert "session_id" in span_calls
        assert "turn_number" in span_calls


# ---------------------------------------------------------------------------
# 2. TestSyntheticHistoryRouting — 10 parametrised cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    HISTORY_QUESTIONS,
    ids=[q.category for q in HISTORY_QUESTIONS],
)
class TestSyntheticHistoryRouting:
    async def test_route_to_history_updates_state_and_span(self, question):
        """Routing to history sets userdata, pending question, skip flag, and span attributes."""
        context, userdata = _make_mock_context()
        agent = _make_mock_agent("orchestrator")
        mock_specialist = MagicMock()
        mock_tracer, mock_span = _make_tracer_mock()

        with (
            patch("agent.agents.history_agent.HistoryAgent") as MockHistory,
            patch("agent.tools.routing.tracer", mock_tracer),
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            MockHistory.return_value = mock_specialist

            from agent.tools.routing import _route_to_history_impl
            result = await _route_to_history_impl(agent, context, question.question)

        # userdata state
        assert userdata.current_subject == "history"
        assert userdata.skip_next_user_turns == 1

        # returned specialist and pending question
        specialist, announcement = result
        assert specialist._pending_question == question.question

        # OTEL span attributes
        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert span_calls.get("to_agent") == "history"
        assert span_calls.get("question_summary") == question.question
        assert "session_id" in span_calls
        assert "turn_number" in span_calls


# ---------------------------------------------------------------------------
# 3. TestSyntheticEnglishRouting — 10 parametrised cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "question",
    ENGLISH_QUESTIONS,
    ids=[q.category for q in ENGLISH_QUESTIONS],
)
class TestSyntheticEnglishRouting:
    async def test_route_to_english_dispatches_agent(self, question):
        """Routing to English updates userdata and dispatches learning-english worker."""
        context, userdata = _make_mock_context()
        agent = _make_mock_agent("orchestrator")
        mock_tracer, mock_span = _make_tracer_mock()

        # Build async context manager mock for LiveKitAPI
        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()
        mock_lk_instance = AsyncMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=None)
        MockLiveKitAPI = MagicMock(return_value=mock_lk_instance)

        with (
            patch("livekit.api.LiveKitAPI", MockLiveKitAPI),
            patch("agent.tools.routing.tracer", mock_tracer),
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            from agent.tools.routing import _route_to_english_impl
            result = await _route_to_english_impl(agent, context, question.question)

        # userdata updated
        assert userdata.current_subject == "english"

        # Dispatch was called exactly once
        mock_api.agent_dispatch.create_dispatch.assert_called_once()

        # Dispatch request has the right agent name and question in metadata
        dispatch_request = mock_api.agent_dispatch.create_dispatch.call_args[0][0]
        assert dispatch_request.agent_name == "learning-english"
        assert question.question in dispatch_request.metadata

        # Return value is the handoff announcement string
        assert isinstance(result, str)
        assert "english" in result.lower()

        # Span has correct attributes
        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert span_calls.get("to_agent") == "english"
        assert span_calls.get("question_summary") == question.question


# ---------------------------------------------------------------------------
# 4. TestSyntheticGuardrailTrigger — 13 parametrised cases (one per category)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "guardrail_input",
    GUARDRAIL_INPUTS,
    ids=[g.category for g in GUARDRAIL_INPUTS],
)
class TestSyntheticGuardrailTrigger:
    async def test_check_returns_flagged_for_category(self, guardrail_input):
        """check() returns flagged=True and the category appears in result.categories."""
        mock_response = _make_moderation_response_for_category(guardrail_input.category)

        with patch("agent.services.guardrail._openai_client") as mock_client:
            mock_client.moderations.create = AsyncMock(return_value=mock_response)

            from agent.services.guardrail import check
            result = await check(guardrail_input.input_text)

        assert result.flagged is True, (
            f"Expected flagged=True for category '{guardrail_input.category}'"
        )
        assert guardrail_input.category in result.categories, (
            f"Expected '{guardrail_input.category}' in result.categories, got {result.categories}"
        )

    async def test_check_and_rewrite_calls_rewrite_once_when_flagged(self, guardrail_input):
        """check_and_rewrite() calls rewrite() exactly once when content is flagged."""
        mock_response = _make_moderation_response_for_category(guardrail_input.category)

        with (
            patch("agent.services.guardrail._openai_client") as mock_oai,
            patch("agent.services.guardrail.rewrite", new_callable=AsyncMock) as mock_rewrite,
            patch("asyncio.create_task"),
        ):
            mock_oai.moderations.create = AsyncMock(return_value=mock_response)
            mock_rewrite.return_value = "Safe educational content."

            from agent.services.guardrail import check_and_rewrite
            result = await check_and_rewrite(
                guardrail_input.input_text,
                session_id="sess-guardrail-test",
                agent_name="test-agent",
            )

        mock_rewrite.assert_called_once()
        assert result == "Safe educational content."


# ---------------------------------------------------------------------------
# 5. TestSyntheticEscalation — 6 parametrised cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "signal",
    ESCALATION_SIGNALS,
    ids=[s.category for s in ESCALATION_SIGNALS],
)
class TestSyntheticEscalation:
    async def test_escalation_sets_userdata_and_calls_teacher(self, signal):
        """_escalate_impl sets escalated=True, stores reason, and calls human_escalation."""
        context, userdata = _make_mock_context()
        agent = _make_mock_agent("orchestrator")
        mock_tracer, mock_span = _make_tracer_mock()

        with (
            patch("agent.tools.routing.tracer", mock_tracer),
            patch("agent.tools.routing.transcript_store"),
            patch(
                "agent.tools.routing.human_escalation.escalate_to_teacher",
                new_callable=AsyncMock,
                return_value="A teacher has been notified and will join shortly.",
            ),
            patch("asyncio.create_task"),
        ):
            from agent.tools.routing import _escalate_impl
            result = await _escalate_impl(agent, context, signal.question)

        # userdata flags
        assert userdata.escalated is True
        assert userdata.escalation_reason == signal.question

        # Return value is the spoken message from human_escalation
        assert isinstance(result, str)
        assert len(result) > 0

        # Span recorded the escalation reason
        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert "reason" in span_calls
        assert signal.question[:500] == span_calls["reason"]


# ---------------------------------------------------------------------------
# 6. TestAgentSystemPromptValidation — structural / static assertions
# ---------------------------------------------------------------------------

class TestAgentSystemPromptValidation:
    def test_orchestrator_prompt_contains_routing_keywords(self):
        """OrchestratorAgent system prompt must reference all routing tools."""
        from agent.agents.orchestrator import ORCHESTRATOR_SYSTEM_PROMPT as prompt

        assert "route_to_math" in prompt, "Orchestrator prompt missing route_to_math"
        assert "route_to_history" in prompt, "Orchestrator prompt missing route_to_history"
        assert "route_to_english" in prompt, "Orchestrator prompt missing route_to_english"
        assert "escalate_to_teacher" in prompt, "Orchestrator prompt missing escalate_to_teacher"

    def test_math_prompt_covers_expected_topics(self):
        """MathAgent system prompt must reference core math topic areas."""
        from agent.agents.math_agent import MATH_SYSTEM_PROMPT as prompt

        lower = prompt.lower()
        assert "arithmetic" in lower, "Math prompt missing 'arithmetic'"
        assert "algebra" in lower, "Math prompt missing 'algebra'"
        assert "geometry" in lower, "Math prompt missing 'geometry'"

    def test_history_prompt_covers_expected_topics(self):
        """HistoryAgent system prompt must reference core history topic areas."""
        from agent.agents.history_agent import HISTORY_SYSTEM_PROMPT as prompt

        lower = prompt.lower()
        assert "history" in lower, "History prompt missing 'history'"
        assert "civilisation" in lower or "civilization" in lower, (
            "History prompt missing 'civilisations'/'civilizations'"
        )
        assert "events" in lower or "event" in lower, "History prompt missing 'events'"

    def test_english_prompt_covers_expected_topics(self):
        """EnglishAgent system prompt must reference core English topic areas."""
        from agent.agents.english_agent import ENGLISH_SYSTEM_PROMPT as prompt

        lower = prompt.lower()
        assert "grammar" in lower, "English prompt missing 'grammar'"
        assert "writing" in lower, "English prompt missing 'writing'"
        assert "vocabulary" in lower, "English prompt missing 'vocabulary'"

    def test_all_specialist_prompts_contain_route_back(self):
        """All specialist agents must instruct the LLM to call route_back_to_orchestrator."""
        from agent.agents.math_agent import MATH_SYSTEM_PROMPT
        from agent.agents.history_agent import HISTORY_SYSTEM_PROMPT
        from agent.agents.english_agent import ENGLISH_SYSTEM_PROMPT

        for prompt, name in [
            (MATH_SYSTEM_PROMPT, "math"),
            (HISTORY_SYSTEM_PROMPT, "history"),
            (ENGLISH_SYSTEM_PROMPT, "english"),
        ]:
            assert "route_back_to_orchestrator" in prompt, (
                f"{name} prompt missing 'route_back_to_orchestrator'"
            )

    def test_moderation_categories_count(self):
        """MODERATION_CATEGORIES must contain exactly 13 items — regression guard."""
        from agent.services.guardrail import MODERATION_CATEGORIES

        assert len(MODERATION_CATEGORIES) == 13, (
            f"Expected 13 moderation categories, got {len(MODERATION_CATEGORIES)}: "
            f"{MODERATION_CATEGORIES}"
        )

    def test_guardrail_inputs_fixture_covers_all_moderation_categories(self):
        """GUARDRAIL_INPUTS fixture must cover every entry in MODERATION_CATEGORIES."""
        from agent.services.guardrail import MODERATION_CATEGORIES
        from agent.tests.fixtures.synthetic_questions import GUARDRAIL_INPUTS

        fixture_categories = {g.category for g in GUARDRAIL_INPUTS}
        missing = [c for c in MODERATION_CATEGORIES if c not in fixture_categories]
        assert not missing, (
            f"GUARDRAIL_INPUTS missing categories: {missing}"
        )
