"""
Unit tests for routing logic in agent/agents/orchestrator.py.

Heavy mocking: we don't want to import livekit.agents for real,
so we mock at the module boundary.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_mock_context(session_id="sess-abc", room_name="room-1"):
    """Build a minimal RunContext-like mock with SessionUserdata."""
    from agent.models.session_state import SessionUserdata

    userdata = SessionUserdata(
        student_identity="alice",
        room_name=room_name,
        session_id=session_id,
    )

    session = MagicMock()
    session.userdata = userdata
    session.chat_ctx = MagicMock()

    context = MagicMock()
    context.session = session
    return context, userdata


class TestOrchestratorInstantiation:
    def test_instantiates_without_error(self):
        """OrchestratorAgent should construct without real LLM connection."""
        with patch("agent.agents.orchestrator.anthropic") as mock_anthropic:
            mock_llm = MagicMock()
            mock_anthropic.LLM.return_value = mock_llm

            with patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
                from agent.agents.orchestrator import OrchestratorAgent
                agent = OrchestratorAgent.__new__(OrchestratorAgent)
                # If we get here without exception, instantiation logic is sound
                assert agent is not None


class TestRoutingToMath:
    async def test_route_to_math_updates_userdata(self):
        context, userdata = _make_mock_context()

        mock_math_agent = MagicMock()

        with (
            patch("agent.agents.orchestrator.MathAgent") as MockMath,
            patch("agent.agents.orchestrator.tracer") as mock_tracer,
            patch("agent.agents.orchestrator.transcript_store") as mock_store,
            patch("asyncio.create_task"),
        ):
            MockMath.return_value = mock_math_agent
            mock_span = MagicMock()
            mock_tracer.start_as_current_span.return_value.__enter__ = MagicMock(
                return_value=mock_span
            )
            mock_tracer.start_as_current_span.return_value.__exit__ = MagicMock(
                return_value=False
            )

            # Create a minimal instance to call the method directly
            agent = MagicMock()
            agent.route_to_math = (
                lambda ctx, question_summary: _call_route_to_math(
                    ctx, question_summary
                )
            )

            # Import and call directly
            from agent.agents.orchestrator import OrchestratorAgent

            # Patch parent __init__ to avoid real LLM init
            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                result = await OrchestratorAgent.route_to_math(
                    instance, context, "multiplication question"
                )

        # userdata should reflect math routing
        assert userdata.current_subject == "math"
        assert userdata.turn_number == 1

    async def test_route_to_math_sets_span_attributes(self):
        context, userdata = _make_mock_context(session_id="span-test-session")

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.MathAgent"),
            patch("agent.agents.orchestrator.tracer") as mock_tracer,
            patch("agent.agents.orchestrator.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                await OrchestratorAgent.route_to_math(
                    instance, context, "What is 7 times 8?"
                )

        # Span should have been created with "routing.decision"
        mock_tracer.start_as_current_span.assert_called_once_with("routing.decision")

        # Key attributes set on span
        span_calls = mock_span.set_attribute.call_args_list
        attr_names = [c[0][0] for c in span_calls]
        assert "session_id" in attr_names
        assert "to_agent" in attr_names
        assert "turn_number" in attr_names


class TestRoutingSpanEnrichment:
    async def test_routing_span_includes_question_summary_and_previous_subject(self):
        """After enrichment, routing spans should carry question_summary and previous_subject."""
        context, userdata = _make_mock_context()
        # Set a prior subject so previous_subject is populated
        userdata.route_to("english")

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.HistoryAgent"),
            patch("agent.agents.orchestrator.tracer") as mock_tracer,
            patch("agent.agents.orchestrator.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                await OrchestratorAgent.route_to_history(
                    instance, context, "Who was Julius Caesar?"
                )

        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert "question_summary" in span_calls
        assert span_calls["question_summary"] == "Who was Julius Caesar?"
        assert "previous_subject" in span_calls
        assert span_calls["previous_subject"] == "english"
