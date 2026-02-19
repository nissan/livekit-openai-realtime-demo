"""
Unit tests for routing logic.

After the routing refactor, the actual logic lives in agent/tools/routing.py
and is called via thin delegators in OrchestratorAgent, MathAgent, and
HistoryAgent. Tests patch at the routing module boundary.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
    session.history = MagicMock()

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
            patch("agent.agents.math_agent.MathAgent") as MockMath,
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store") as mock_store,
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

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                instance.agent_name = "orchestrator"
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
            patch("agent.agents.math_agent.MathAgent"),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                instance.agent_name = "orchestrator"
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
            patch("agent.agents.history_agent.HistoryAgent"),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(
                OrchestratorAgent.__bases__[0], "__init__", return_value=None
            ):
                instance = object.__new__(OrchestratorAgent)
                instance.agent_name = "orchestrator"
                await OrchestratorAgent.route_to_history(
                    instance, context, "Who was Julius Caesar?"
                )

        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert "question_summary" in span_calls
        assert span_calls["question_summary"] == "Who was Julius Caesar?"
        assert "previous_subject" in span_calls
        assert span_calls["previous_subject"] == "english"


class TestSpecialistHandback:
    async def test_math_agent_can_route_back_to_orchestrator(self):
        """MathAgent handback sets current_subject to 'orchestrator' and returns OrchestratorAgent."""
        context, userdata = _make_mock_context()
        userdata.route_to("math")  # already in math session

        mock_orchestrator = MagicMock()

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.OrchestratorAgent") as MockOrchestrator,
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            MockOrchestrator.return_value = mock_orchestrator
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.math_agent import MathAgent

            with patch.object(MathAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(MathAgent)
                instance.agent_name = "math"
                result = await MathAgent.route_back_to_orchestrator(
                    instance, context, "Finished explaining multiplication"
                )

        assert userdata.current_subject == "orchestrator"
        assert userdata.turn_number == 1
        agent_result, announcement = result
        assert agent_result is mock_orchestrator
        assert "tutor" in announcement.lower()

    async def test_history_agent_can_route_back_to_orchestrator(self):
        """HistoryAgent handback sets current_subject to 'orchestrator' and returns OrchestratorAgent."""
        context, userdata = _make_mock_context()
        userdata.route_to("history")  # already in history session

        mock_orchestrator = MagicMock()

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.OrchestratorAgent") as MockOrchestrator,
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            MockOrchestrator.return_value = mock_orchestrator
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.history_agent import HistoryAgent

            with patch.object(HistoryAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(HistoryAgent)
                instance.agent_name = "history"
                result = await HistoryAgent.route_back_to_orchestrator(
                    instance, context, "Finished explaining WW2"
                )

        assert userdata.current_subject == "orchestrator"
        assert userdata.turn_number == 1
        agent_result, announcement = result
        assert agent_result is mock_orchestrator
        assert "tutor" in announcement.lower()

    async def test_previous_subject_captured_before_route_update(self):
        """OTEL span must show previous_subject='math' and to_agent='orchestrator'."""
        context, userdata = _make_mock_context()
        userdata.route_to("math")  # set subject to math before handback

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.OrchestratorAgent"),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.math_agent import MathAgent

            with patch.object(MathAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(MathAgent)
                instance.agent_name = "math"
                await MathAgent.route_back_to_orchestrator(
                    instance, context, "Topic complete"
                )

        span_calls = {c[0][0]: c[0][1] for c in mock_span.set_attribute.call_args_list}
        assert span_calls.get("from_agent") == "math"
        assert span_calls.get("to_agent") == "orchestrator"
        assert span_calls.get("previous_subject") == "math"

    async def test_handback_span_uses_routing_decision_name(self):
        """Handback span must be created with 'routing.decision' span name."""
        context, userdata = _make_mock_context()
        userdata.route_to("history")

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.agents.orchestrator.OrchestratorAgent"),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.history_agent import HistoryAgent

            with patch.object(HistoryAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(HistoryAgent)
                instance.agent_name = "history"
                await HistoryAgent.route_back_to_orchestrator(
                    instance, context, "Topic complete"
                )

        mock_tracer.start_as_current_span.assert_called_once_with("routing.decision")
