"""
Tests that routing functions set speaking_agent proactively (PLAN10).

Bug: speaking_agent was only set in on_enter(), which fires AFTER the drain-phase
response. So the math tutor's FIRST response showed as "orchestrator" in the
transcript because speaking_agent still held the old agent name.

Fix: Set speaking_agent in each _route_to_*_impl() immediately after route_to(),
so drain-phase responses are correctly attributed from the first token.
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


class TestRoutingSetsSpeakingAgent:
    """
    Verify routing functions set userdata.speaking_agent proactively — immediately
    after route_to(), before on_enter() can fire.
    """

    @pytest.mark.asyncio
    async def test_route_to_math_sets_speaking_agent(self):
        """
        _route_to_math_impl must set userdata.speaking_agent = "math" right after
        calling route_to("math"), not wait for MathAgent.on_enter().
        """
        from agent.models.session_state import SessionUserdata
        from agent.tools.routing import _route_to_math_impl

        userdata = SessionUserdata(student_identity="alice", room_name="room-1")
        userdata.speaking_agent = "orchestrator"   # simulates prior orchestrator turn

        mock_context = _make_mock_context(userdata)
        mock_agent = MagicMock()
        mock_agent.agent_name = "orchestrator"

        # Patch the tracer span and transcript save to avoid side effects
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

        # speaking_agent must be "math" immediately — before on_enter() runs
        assert userdata.speaking_agent == "math", (
            f"Expected speaking_agent='math' immediately after _route_to_math_impl, "
            f"got '{userdata.speaking_agent}'. "
            "Drain-phase responses would be mis-attributed without this fix."
        )
        assert isinstance(result, tuple)
        assert result[0].agent_name == "math"   # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_route_to_history_sets_speaking_agent(self):
        """
        _route_to_history_impl must set userdata.speaking_agent = "history" immediately.
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

        assert userdata.speaking_agent == "history", (
            f"Expected speaking_agent='history' immediately after _route_to_history_impl, "
            f"got '{userdata.speaking_agent}'."
        )
        assert isinstance(result, tuple)
        assert result[0].agent_name == "history"   # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_route_back_to_orchestrator_sets_speaking_agent(self):
        """
        _route_to_orchestrator_impl must set userdata.speaking_agent = "orchestrator"
        immediately after route_to("orchestrator").
        """
        from agent.models.session_state import SessionUserdata
        from agent.tools.routing import _route_to_orchestrator_impl

        userdata = SessionUserdata(student_identity="carol", room_name="room-3")
        userdata.route_to("math")
        userdata.speaking_agent = "math"   # math agent was active

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

        assert userdata.speaking_agent == "orchestrator", (
            f"Expected speaking_agent='orchestrator' immediately after _route_to_orchestrator_impl, "
            f"got '{userdata.speaking_agent}'."
        )
        assert isinstance(result, tuple)
