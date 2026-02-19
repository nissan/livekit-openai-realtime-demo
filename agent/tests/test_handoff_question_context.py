"""
Tests that question context is preserved through agent handoffs.

Root causes fixed (see PLAN6.md):
  A — create_dispatch() used wrong API (keyword args instead of proto object)
  B — generate_reply() called without user_input → silence on activation
  C — English Realtime session started with empty context

These tests verify:
  - CreateAgentDispatchRequest proto is used for English dispatch and back
  - _pending_question is set on Math/History/Orchestrator agents after routing
  - GuardedAgent.on_enter() passes _pending_question as user_input when set
  - GuardedAgent.on_enter() calls generate_reply() with no args when not set
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


def _make_mock_context(session_id="sess-xyz", room_name="room-test"):
    """Build a minimal RunContext-like mock with SessionUserdata."""
    from agent.models.session_state import SessionUserdata

    userdata = SessionUserdata(
        student_identity="bob",
        room_name=room_name,
        session_id=session_id,
    )

    session = MagicMock()
    session.userdata = userdata
    session.history = MagicMock()

    context = MagicMock()
    context.session = session
    return context, userdata


class TestDispatchProto:
    """Root Cause A: verify CreateAgentDispatchRequest proto is used for all dispatches."""

    async def test_route_to_english_uses_create_agent_dispatch_request(self):
        """
        _route_to_english_impl must call create_dispatch with a CreateAgentDispatchRequest
        proto object, NOT keyword args. Keyword args cause a TypeError at runtime.
        """
        from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

        context, userdata = _make_mock_context(room_name="room-test")

        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("livekit.api.LiveKitAPI", MagicMock(return_value=mock_lk_instance)),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.tools.routing import _route_to_english_impl

            agent_mock = MagicMock()
            agent_mock.agent_name = "orchestrator"
            await _route_to_english_impl(agent_mock, context, "Help me with grammar")

        call_arg = mock_api.agent_dispatch.create_dispatch.call_args[0][0]
        assert isinstance(call_arg, CreateAgentDispatchRequest), (
            f"create_dispatch must receive CreateAgentDispatchRequest, got {type(call_arg)}"
        )
        assert call_arg.room == "room-test"
        assert call_arg.agent_name == "learning-english"
        # Question must be embedded in metadata
        assert "question:" in call_arg.metadata
        assert "Help me with grammar" in call_arg.metadata

    async def test_english_back_uses_create_agent_dispatch_request(self):
        """
        EnglishAgent.route_back_to_orchestrator must call create_dispatch with a
        CreateAgentDispatchRequest proto object for the return dispatch.
        """
        from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

        context, userdata = _make_mock_context(room_name="room-test")

        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("livekit.api.LiveKitAPI", MagicMock(return_value=mock_lk_instance)),
            patch("asyncio.create_task"),
            patch("agent.agents.english_agent.EnglishAgent.__init__", return_value=None),
        ):
            from agent.agents.english_agent import EnglishAgent

            instance = object.__new__(EnglishAgent)
            await EnglishAgent.route_back_to_orchestrator(
                instance, context, "Student asked about maths"
            )

        call_arg = mock_api.agent_dispatch.create_dispatch.call_args[0][0]
        assert isinstance(call_arg, CreateAgentDispatchRequest), (
            f"create_dispatch must receive CreateAgentDispatchRequest, got {type(call_arg)}"
        )
        assert call_arg.room == "room-test"
        assert call_arg.agent_name == "learning-orchestrator"
        assert "return_from_english:" in call_arg.metadata


class TestPendingQuestion:
    """Root Cause B: verify _pending_question is set and used correctly."""

    async def test_route_to_math_sets_pending_question(self):
        """
        _route_to_math_impl must set _pending_question on the returned MathAgent
        so that on_enter() can immediately answer the student's question.
        """
        context, userdata = _make_mock_context()

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.tools.routing import _route_to_math_impl

            agent_mock = MagicMock()
            agent_mock.agent_name = "orchestrator"
            question = "What is the quadratic formula?"
            specialist, _ = await _route_to_math_impl(agent_mock, context, question)

        assert hasattr(specialist, "_pending_question"), (
            "MathAgent returned from _route_to_math_impl must have _pending_question set"
        )
        assert specialist._pending_question == question

    async def test_route_to_history_sets_pending_question(self):
        """
        _route_to_history_impl must set _pending_question on the returned HistoryAgent
        so that on_enter() can immediately answer the student's question.
        """
        context, userdata = _make_mock_context()

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.history_agent.HistoryAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.tools.routing import _route_to_history_impl

            agent_mock = MagicMock()
            agent_mock.agent_name = "orchestrator"
            question = "Who was Julius Caesar?"
            specialist, _ = await _route_to_history_impl(agent_mock, context, question)

        assert hasattr(specialist, "_pending_question"), (
            "HistoryAgent returned from _route_to_history_impl must have _pending_question set"
        )
        assert specialist._pending_question == question

    async def test_on_enter_uses_pending_question_as_user_input(self):
        """
        GuardedAgent.on_enter() must pass _pending_question as user_input= to
        generate_reply() when the attribute is set. This causes the agent to
        immediately answer the question rather than waiting silently.
        """
        import livekit.agents

        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock()

        with patch.object(
            livekit.agents.Agent, "session", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_session

            with patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
                from agent.agents.base import GuardedAgent

                instance = object.__new__(GuardedAgent)
                instance._pending_question = "Tell me about World War II"
                await instance.on_enter()

        mock_session.generate_reply.assert_called_once_with(
            user_input="Tell me about World War II"
        )

    async def test_on_enter_without_pending_question_uses_no_user_input(self):
        """
        GuardedAgent.on_enter() must call generate_reply() with no arguments when
        _pending_question is not set, relying on conversation history for context.
        """
        import livekit.agents

        mock_session = MagicMock()
        mock_session.generate_reply = AsyncMock()

        with patch.object(
            livekit.agents.Agent, "session", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_session

            with patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
                from agent.agents.base import GuardedAgent

                instance = object.__new__(GuardedAgent)
                # No _pending_question set — should use no user_input
                await instance.on_enter()

        mock_session.generate_reply.assert_called_once_with()
