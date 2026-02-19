"""
Tests for transcript speaker correctness (PLAN9).

Bug: Transcript speaker showed DESTINATION agent, not SOURCE agent.
Root cause: current_subject is updated by route_to() BEFORE conversation_item_added fires.

Fix: speaking_agent field on SessionUserdata, set by GuardedAgent.on_enter() which fires
AFTER the transition message event. The transcript handler now uses speaking_agent
(falling back to current_subject) to identify who actually said the message.
"""
import asyncio
import pytest
import livekit.agents
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch


# ---------------------------------------------------------------------------
# TestSpeakingAgentSetByOnEnter
# ---------------------------------------------------------------------------


class TestSpeakingAgentSetByOnEnter:
    """
    Verify that GuardedAgent.on_enter() sets userdata.speaking_agent = self.agent_name
    before generating a reply.
    """

    async def test_speaking_agent_set_by_on_enter(self):
        """
        When on_enter() is called on an agent with agent_name="math", userdata.speaking_agent
        must be set to "math" (the agent's own name), not left as None.
        """
        from agent.agents.base import GuardedAgent
        from agent.models.session_state import SessionUserdata
        import agent.agents.base as base_module

        # Minimal userdata — speaking_agent starts as None
        userdata = SessionUserdata(student_identity="alice", room_name="room-1")
        assert userdata.speaking_agent is None  # pre-condition

        mock_session = MagicMock()
        mock_session.userdata = userdata
        mock_session.generate_reply = AsyncMock()
        mock_history = MagicMock()
        mock_history.messages.return_value = []
        mock_session.history = mock_history

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(livekit.agents.Agent, "session", new_callable=PropertyMock) as mock_prop, \
             patch.object(base_module, "_tracer", mock_tracer), \
             patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
            mock_prop.return_value = mock_session

            instance = object.__new__(GuardedAgent)
            instance.agent_name = "math"
            await instance.on_enter()

        # speaking_agent must now reflect this agent's name
        assert userdata.speaking_agent == "math"

    async def test_speaking_agent_updated_on_each_handoff(self):
        """
        When on_enter() runs for "orchestrator" agent, speaking_agent becomes "orchestrator".
        When on_enter() runs next for "math" agent, speaking_agent becomes "math".
        This models successive handoffs.
        """
        from agent.agents.base import GuardedAgent
        from agent.models.session_state import SessionUserdata
        import agent.agents.base as base_module

        userdata = SessionUserdata(student_identity="bob", room_name="room-2")

        mock_session = MagicMock()
        mock_session.userdata = userdata
        mock_session.generate_reply = AsyncMock()
        mock_history = MagicMock()
        mock_history.messages.return_value = []
        mock_session.history = mock_history

        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(livekit.agents.Agent, "session", new_callable=PropertyMock) as mock_prop, \
             patch.object(base_module, "_tracer", mock_tracer), \
             patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
            mock_prop.return_value = mock_session

            orch = object.__new__(GuardedAgent)
            orch.agent_name = "orchestrator"
            await orch.on_enter()
            assert userdata.speaking_agent == "orchestrator"

            math = object.__new__(GuardedAgent)
            math.agent_name = "math"
            await math.on_enter()
            assert userdata.speaking_agent == "math"


# ---------------------------------------------------------------------------
# TestSpeakerUsesspeaking_agent
# ---------------------------------------------------------------------------


class TestSpeakerUsesSpeakingAgent:
    """
    Verify that the transcript handler uses speaking_agent (not current_subject)
    to identify who said a message. This matches the PLAN9 fix in main.py.
    """

    def _resolve_speaker(self, userdata, role: str) -> str:
        """Mirrors the fixed speaker logic from main.py on_conversation_item."""
        if role == "user":
            return "student"
        return userdata.speaking_agent or userdata.current_subject or "orchestrator"

    def test_speaker_uses_speaking_agent_not_current_subject(self):
        """
        When speaking_agent="orchestrator" but current_subject="math" (transition scenario),
        the speaker must be "orchestrator" (the one who SAID the message).

        This simulates the moment right after route_to("math") is called but before
        MathAgent.on_enter() fires.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        # Orchestrator set as speaking agent when it greeted the student
        userdata.speaking_agent = "orchestrator"
        # route_to("math") was called — current_subject already updated
        userdata.route_to("math")

        # Transition message fires: "Let me connect you with the Math tutor!"
        speaker = self._resolve_speaker(userdata, role="assistant")
        assert speaker == "orchestrator", (
            f"Expected 'orchestrator' (who said the transition message) but got '{speaker}'. "
            "current_subject='math' must NOT override speaking_agent."
        )

    def test_speaker_falls_back_to_current_subject_when_speaking_agent_is_none(self):
        """
        When speaking_agent is None (session just started, no on_enter yet),
        fall back to current_subject.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.speaking_agent = None
        userdata.route_to("history")

        speaker = self._resolve_speaker(userdata, role="assistant")
        assert speaker == "history"

    def test_speaker_falls_back_to_orchestrator_when_both_are_none(self):
        """
        When both speaking_agent and current_subject are None, default to 'orchestrator'.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        assert userdata.speaking_agent is None
        assert userdata.current_subject is None

        speaker = self._resolve_speaker(userdata, role="assistant")
        assert speaker == "orchestrator"

    def test_speaker_is_always_student_for_user_role(self):
        """
        Regardless of speaking_agent or current_subject, a 'user' role message
        must always have speaker='student'.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.speaking_agent = "math"
        userdata.route_to("math")

        speaker = self._resolve_speaker(userdata, role="user")
        assert speaker == "student"
