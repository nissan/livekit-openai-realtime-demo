"""
Tests that routing functions do NOT change speaking_agent (PLAN10 revert).

PLAN10 originally added proactive speaking_agent setting inside routing functions,
which caused a regression: the orchestrator's transition message ("Let me connect
you with our Mathematics tutor!") fired AFTER the routing function set speaking_agent
to "math", so the transition message was mislabelled as "Math Tutor" in the transcript.

Correct behaviour: speaking_agent is set ONLY in GuardedAgent.on_enter(), which fires
AFTER the transition message has been committed to history. The routing function must
leave speaking_agent unchanged so the transition message is attributed to the correct
outgoing agent.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_mock_context(userdata):
    """Build a minimal RunContext mock backed by the given userdata."""
    mock_session = MagicMock()
    mock_session.userdata = userdata
    mock_history = MagicMock()
    mock_history.messages.return_value = []
    mock_session.history = mock_history

    mock_context = MagicMock()
    mock_context.session = mock_session
    return mock_context


class TestRoutingDoesNotChangeSpeakingAgent:
    """
    Verify routing functions leave userdata.speaking_agent UNCHANGED.

    The transition message ("Let me connect you with our Mathematics tutor!") is
    spoken by the outgoing agent AFTER the routing function returns. If we set
    speaking_agent="math" inside the routing function, the transition message gets
    mislabelled as "Math Tutor" in the transcript — a regression introduced by
    the original PLAN10 implementation that was later reverted.
    """

    @pytest.mark.asyncio
    async def test_route_to_math_leaves_speaking_agent_unchanged(self):
        """
        _route_to_math_impl must NOT modify userdata.speaking_agent.
        The transition message is still spoken by the orchestrator after this call.
        """
        from agent.models.session_state import SessionUserdata
        from agent.tools.routing import _route_to_math_impl

        userdata = SessionUserdata(student_identity="alice", room_name="room-1")
        userdata.speaking_agent = "orchestrator"   # set by orchestrator.on_enter

        mock_context = _make_mock_context(userdata)
        mock_agent = MagicMock()
        mock_agent.agent_name = "orchestrator"

        import agent.tools.routing as routing_module
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span

        from unittest.mock import patch
        with patch.object(routing_module, "tracer", mock_tracer), \
             patch.object(routing_module.transcript_store, "save_routing_decision", AsyncMock()):
            result = await _route_to_math_impl(mock_agent, mock_context, "7 times 8")

        # speaking_agent must remain "orchestrator" — the transition message
        # "Let me connect you with our Mathematics tutor!" fires AFTER this
        # call and must still be attributed to the orchestrator.
        assert userdata.speaking_agent == "orchestrator", (
            f"Expected speaking_agent='orchestrator' (unchanged) but got "
            f"'{userdata.speaking_agent}'. Routing functions must NOT change "
            "speaking_agent — that is on_enter()'s responsibility."
        )
        assert isinstance(result, tuple)
        assert result[0].agent_name == "math"   # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_route_to_history_leaves_speaking_agent_unchanged(self):
        """
        _route_to_history_impl must NOT modify userdata.speaking_agent.
        """
        from agent.models.session_state import SessionUserdata
        from agent.tools.routing import _route_to_history_impl

        userdata = SessionUserdata(student_identity="bob", room_name="room-2")
        userdata.speaking_agent = "orchestrator"

        mock_context = _make_mock_context(userdata)
        mock_agent = MagicMock()
        mock_agent.agent_name = "orchestrator"

        import agent.tools.routing as routing_module
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span

        from unittest.mock import patch
        with patch.object(routing_module, "tracer", mock_tracer), \
             patch.object(routing_module.transcript_store, "save_routing_decision", AsyncMock()):
            result = await _route_to_history_impl(mock_agent, mock_context, "WW2 causes")

        assert userdata.speaking_agent == "orchestrator", (
            f"Expected speaking_agent='orchestrator' (unchanged) but got '{userdata.speaking_agent}'."
        )
        assert isinstance(result, tuple)
        assert result[0].agent_name == "history"   # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_route_back_to_orchestrator_leaves_speaking_agent_unchanged(self):
        """
        _route_to_orchestrator_impl must NOT modify userdata.speaking_agent.
        The math agent's farewell sentence fires after this call and must still
        be attributed to "math".
        """
        from agent.models.session_state import SessionUserdata
        from agent.tools.routing import _route_to_orchestrator_impl

        userdata = SessionUserdata(student_identity="carol", room_name="room-3")
        userdata.route_to("math")
        userdata.speaking_agent = "math"   # set by math.on_enter

        mock_context = _make_mock_context(userdata)
        mock_agent = MagicMock()
        mock_agent.agent_name = "math"

        import agent.tools.routing as routing_module
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span

        from unittest.mock import patch
        with patch.object(routing_module, "tracer", mock_tracer), \
             patch.object(routing_module.transcript_store, "save_routing_decision", AsyncMock()):
            result = await _route_to_orchestrator_impl(mock_agent, mock_context, "answered maths q")

        assert userdata.speaking_agent == "math", (
            f"Expected speaking_agent='math' (unchanged) but got '{userdata.speaking_agent}'."
        )
        assert isinstance(result, tuple)
