"""
Regression tests for the two agent handoff bugs fixed in commit 8ce9a56:

Bug 1: Specialist agents were silent on first activation after handoff.
  Fix: Added on_enter() to GuardedAgent calling self.session.generate_reply().

Bug 2: Specialist agents couldn't route students to other subjects.
  Fix: Added @function_tool routing methods to each specialist via shared routing.py.

These tests ensure that:
  1. on_enter() always calls generate_reply()              (Bug 1 regression)
  2. Every specialist has all required routing tool methods (Bug 2 regression)
  3. English routing and escalation paths work correctly   (additional coverage)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


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


class TestOnEnterCallsGenerateReply:
    """
    Bug 1 regression: GuardedAgent.on_enter() must call session.generate_reply().

    If someone removes on_enter() from GuardedAgent, or removes the generate_reply()
    call from it, one of these tests will fail immediately.
    """

    async def test_on_enter_calls_generate_reply(self):
        """GuardedAgent.on_enter() should call session.generate_reply() exactly once."""
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
                await instance.on_enter()

        mock_session.generate_reply.assert_called_once()

    def test_specialists_do_not_override_on_enter(self):
        """
        OrchestratorAgent, MathAgent, and HistoryAgent must NOT define their own
        on_enter(). If any subclass accidentally shadows it with a no-op, this fails.
        """
        from agent.agents.base import GuardedAgent
        from agent.agents.orchestrator import OrchestratorAgent
        from agent.agents.math_agent import MathAgent
        from agent.agents.history_agent import HistoryAgent

        assert OrchestratorAgent.on_enter is GuardedAgent.on_enter, (
            "OrchestratorAgent must NOT override GuardedAgent.on_enter()"
        )
        assert MathAgent.on_enter is GuardedAgent.on_enter, (
            "MathAgent must NOT override GuardedAgent.on_enter()"
        )
        assert HistoryAgent.on_enter is GuardedAgent.on_enter, (
            "HistoryAgent must NOT override GuardedAgent.on_enter()"
        )

    async def test_on_enter_does_not_double_call(self):
        """on_enter() must call generate_reply() exactly once — not zero or two times."""
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
                await instance.on_enter()

        assert mock_session.generate_reply.call_count == 1, (
            f"Expected generate_reply called once, "
            f"got {mock_session.generate_reply.call_count} call(s)"
        )


class TestSpecialistHasRoutingTools:
    """
    Bug 2 regression: Each specialist must have all required @function_tool methods.

    If any routing method is accidentally deleted from MathAgent, HistoryAgent,
    or OrchestratorAgent, the corresponding test fails immediately.
    Pure class-level inspection — no instantiation or network calls required.
    """

    # ── MathAgent routing tools ────────────────────────────────────────────────

    def test_math_agent_has_route_back_to_orchestrator(self):
        from agent.agents.math_agent import MathAgent

        assert callable(getattr(MathAgent, "route_back_to_orchestrator", None)), (
            "MathAgent.route_back_to_orchestrator must exist as a callable @function_tool"
        )

    def test_math_agent_has_escalate_to_teacher(self):
        from agent.agents.math_agent import MathAgent

        assert callable(getattr(MathAgent, "escalate_to_teacher", None)), (
            "MathAgent.escalate_to_teacher must exist as a callable @function_tool"
        )

    def test_math_agent_does_not_have_direct_cross_routing(self):
        from agent.agents.math_agent import MathAgent

        assert not hasattr(MathAgent, "route_to_history"), (
            "MathAgent must NOT have route_to_history — specialists route back via orchestrator"
        )

    # ── HistoryAgent routing tools ─────────────────────────────────────────────

    def test_history_agent_has_route_back_to_orchestrator(self):
        from agent.agents.history_agent import HistoryAgent

        assert callable(getattr(HistoryAgent, "route_back_to_orchestrator", None)), (
            "HistoryAgent.route_back_to_orchestrator must exist as a callable @function_tool"
        )

    def test_history_agent_has_escalate_to_teacher(self):
        from agent.agents.history_agent import HistoryAgent

        assert callable(getattr(HistoryAgent, "escalate_to_teacher", None)), (
            "HistoryAgent.escalate_to_teacher must exist as a callable @function_tool"
        )

    def test_history_agent_does_not_have_direct_cross_routing(self):
        from agent.agents.history_agent import HistoryAgent

        assert not hasattr(HistoryAgent, "route_to_math"), (
            "HistoryAgent must NOT have route_to_math — specialists route back via orchestrator"
        )

    # ── OrchestratorAgent routing tools ───────────────────────────────────────

    def test_orchestrator_has_route_to_math(self):
        from agent.agents.orchestrator import OrchestratorAgent

        assert callable(getattr(OrchestratorAgent, "route_to_math", None)), (
            "OrchestratorAgent.route_to_math must exist as a callable @function_tool"
        )

    def test_orchestrator_has_route_to_history(self):
        from agent.agents.orchestrator import OrchestratorAgent

        assert callable(getattr(OrchestratorAgent, "route_to_history", None)), (
            "OrchestratorAgent.route_to_history must exist as a callable @function_tool"
        )

    def test_orchestrator_has_route_to_english(self):
        from agent.agents.orchestrator import OrchestratorAgent

        assert callable(getattr(OrchestratorAgent, "route_to_english", None)), (
            "OrchestratorAgent.route_to_english must exist as a callable @function_tool"
        )


class TestEnglishRoutingAndEscalation:
    """
    Cover English routing and teacher escalation paths not exercised by existing tests.

    English routing: _route_to_english_impl dispatches a separate LiveKit worker.
    Escalation:      _escalate_impl sets userdata flags and calls human_escalation service.
    """

    async def test_orchestrator_can_route_to_english(self):
        """
        When the LiveKit API dispatch succeeds, OrchestratorAgent.route_to_english must return a
        plain string announcement (not a tuple) and set current_subject to "english".
        """
        context, userdata = _make_mock_context()

        # Build a mock async-context-manager for LiveKitAPI
        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)
        mock_lk_class = MagicMock(return_value=mock_lk_instance)

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("livekit.api.LiveKitAPI", mock_lk_class),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            with patch.object(OrchestratorAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(OrchestratorAgent)
                instance.agent_name = "orchestrator"
                result = await OrchestratorAgent.route_to_english(
                    instance, context, "Help me write a poem"
                )

        assert isinstance(result, str), (
            "On successful dispatch, route_to_english must return a string announcement, "
            f"got {type(result).__name__!r} instead"
        )
        assert userdata.current_subject == "english"

    async def test_english_routing_fallback_on_dispatch_failure(self):
        """
        When the LiveKit API dispatch fails, OrchestratorAgent.route_to_english must return a
        (FallbackEnglishAgent, announcement) tuple and still mark subject as "english".
        """
        context, userdata = _make_mock_context()

        # Make the async context manager raise on __aenter__
        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(
            side_effect=Exception("LiveKit: connection refused")
        )
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)
        mock_lk_class = MagicMock(return_value=mock_lk_instance)

        mock_span = MagicMock()
        mock_ctx_manager = MagicMock()
        mock_ctx_manager.__enter__ = MagicMock(return_value=mock_span)
        mock_ctx_manager.__exit__ = MagicMock(return_value=False)

        with (
            patch("livekit.api.LiveKitAPI", mock_lk_class),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            # Prevent FallbackEnglishAgent.__init__ → super().__init__() from
            # touching real Agent/LLM internals
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx_manager

            from agent.agents.orchestrator import OrchestratorAgent

            instance = object.__new__(OrchestratorAgent)
            instance.agent_name = "orchestrator"
            result = await OrchestratorAgent.route_to_english(
                instance, context, "Help me with grammar"
            )

        assert isinstance(result, tuple), (
            "On dispatch failure, route_to_english must return a (FallbackAgent, str) tuple, "
            f"got {type(result).__name__!r} instead"
        )
        fallback_agent, announcement = result
        assert "English" in announcement
        assert userdata.current_subject == "english"

    async def test_math_agent_escalates_to_teacher(self):
        """
        MathAgent.escalate_to_teacher() must:
          - set userdata.escalated = True
          - set userdata.escalation_reason to the provided reason string
          - return the spoken escalation message from human_escalation service
        """
        context, userdata = _make_mock_context()
        userdata.route_to("math")
        reason = "Student is very upset and crying"
        mock_spoken = "Teacher Sarah is joining your session — please hold on."

        with (
            patch("agent.tools.routing.human_escalation") as mock_escalation,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_escalation.escalate_to_teacher = AsyncMock(return_value=mock_spoken)

            from agent.agents.math_agent import MathAgent

            with patch.object(MathAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(MathAgent)
                instance.agent_name = "math"
                result = await MathAgent.escalate_to_teacher(instance, context, reason)

        assert userdata.escalated is True
        assert userdata.escalation_reason == reason
        assert result == mock_spoken

    async def test_history_agent_escalates_to_teacher(self):
        """
        HistoryAgent.escalate_to_teacher() must set the same escalation state,
        confirming that _escalate_impl covers all specialists via the shared impl.
        """
        context, userdata = _make_mock_context()
        userdata.route_to("history")
        reason = "Student asked about something inappropriate for school"
        mock_spoken = "I'm getting your teacher now — please stay calm."

        with (
            patch("agent.tools.routing.human_escalation") as mock_escalation,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_escalation.escalate_to_teacher = AsyncMock(return_value=mock_spoken)

            from agent.agents.history_agent import HistoryAgent

            with patch.object(HistoryAgent.__bases__[0], "__init__", return_value=None):
                instance = object.__new__(HistoryAgent)
                instance.agent_name = "history"
                result = await HistoryAgent.escalate_to_teacher(instance, context, reason)

        assert userdata.escalated is True
        assert userdata.escalation_reason == reason
        assert result == mock_spoken
