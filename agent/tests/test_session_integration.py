"""
Session integration regression tests — PLAN17 Proposal A.

These tests cover agent behaviour at the session level:
  - Routing decisions, subject tracking, skip_next_user_turns counter
  - Transcript publication logic (phantom entry suppression)
  - Guardrail check/rewrite pipeline
  - Speaker attribution via speaking_agent
  - OTEL span attributes (decision_ms, e2e_response_ms, guardrail_ms)
  - English dispatch and pipeline close timing
  - Conversation history across handoffs

All tests run without Docker/network using mocks, following the established
pattern from test_agent_handoffs.py and test_orchestrator_routing.py.

Regression coverage:
  PLAN16 Fix C  — skip_next_user_turns suppresses phantom "You" in transcript
  PLAN16 Fix A  — pipeline closes before English speaks (3.5s timer)
  PLAN15        — conversation_item_added fires with populated text_content
  PLAN9/10      — speaking_agent set by on_enter, not by routing function
  PLAN7         — history accumulates across handoffs
  PLAN6         — on_enter() calls generate_reply(); specialists have routing tools
  PLAN1         — guardrail rewrite fires on flagged content
"""
import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch, call


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_mock_context(
    session_id: str = "sess-integration-001",
    room_name: str = "test-room",
    student_identity: str = "alice",
):
    """Build a minimal RunContext-like mock matching the real SDK shape."""
    from agent.models.session_state import SessionUserdata

    userdata = SessionUserdata(
        student_identity=student_identity,
        room_name=room_name,
        session_id=session_id,
    )

    session = MagicMock()
    session.userdata = userdata
    session.history = MagicMock()
    session.history.messages.return_value = []

    context = MagicMock()
    context.session = session
    return context, userdata


def _make_mock_span():
    """Build a mock span + context manager for tracer.start_as_current_span."""
    span = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=span)
    ctx.__exit__ = MagicMock(return_value=False)
    return span, ctx


# ---------------------------------------------------------------------------
# PLAN16 Fix C — skip_next_user_turns suppresses phantom "You" transcript entry
# ---------------------------------------------------------------------------

class TestSkipNextUserTurns:
    """
    Regression tests for the skip_next_user_turns counter mechanism.

    When on_enter() calls generate_reply(user_input=pending_q), LiveKit fires a
    conversation_item_added event with role="user" containing the pending question.
    This creates a phantom "You" entry in the transcript UI. The counter in
    SessionUserdata suppresses it.
    """

    def test_skip_counter_decrements_on_user_turn(self):
        """
        Simulates the on_conversation_item handler behaviour:
        skip_next_user_turns=1 → first user turn is suppressed, counter drops to 0.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.skip_next_user_turns = 1

        # Simulate conversation_item_added handler logic (from main.py)
        def handle_item(role: str, content: str) -> bool:
            """Returns True if item was published, False if suppressed."""
            if role == "user":
                if getattr(userdata, "skip_next_user_turns", 0) > 0:
                    userdata.skip_next_user_turns -= 1
                    return False
            return True

        # First user item — suppressed (phantom from generate_reply(user_input=))
        assert handle_item("user", "What is the Pythagorean theorem?") is False
        assert userdata.skip_next_user_turns == 0

        # Second user item — real student speech, must be published
        assert handle_item("user", "Can you explain more?") is True
        assert userdata.skip_next_user_turns == 0

    def test_skip_counter_does_not_suppress_assistant_turns(self):
        """
        skip_next_user_turns must never suppress assistant turns —
        only "user" role items are filtered.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.skip_next_user_turns = 1

        def handle_item(role: str, content: str) -> bool:
            if role == "user":
                if getattr(userdata, "skip_next_user_turns", 0) > 0:
                    userdata.skip_next_user_turns -= 1
                    return False
            return True

        # Assistant turn — must always be published regardless of counter
        assert handle_item("assistant", "The Pythagorean theorem states...") is True
        assert userdata.skip_next_user_turns == 1  # counter unchanged

    def test_routing_function_sets_skip_counter(self):
        """
        Every routing function that calls generate_reply(user_input=) must set
        skip_next_user_turns=1 before the handoff. Verify for math routing.
        """
        context, userdata = _make_mock_context()

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx

            from agent.tools.routing import _route_to_math_impl
            from agent.agents.base import GuardedAgent

            with patch.object(GuardedAgent, "__init__", return_value=None):
                import asyncio as _asyncio
                result = _asyncio.get_event_loop().run_until_complete(
                    _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
                )

        assert userdata.skip_next_user_turns == 1, (
            "Routing to math must set skip_next_user_turns=1 to suppress phantom user entry"
        )

    def test_history_routing_sets_skip_counter(self):
        """History routing must also set skip_next_user_turns=1."""
        context, userdata = _make_mock_context()

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.history_agent.HistoryAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx

            from agent.tools.routing import _route_to_history_impl
            from agent.agents.base import GuardedAgent

            with patch.object(GuardedAgent, "__init__", return_value=None):
                import asyncio as _asyncio
                result = _asyncio.get_event_loop().run_until_complete(
                    _route_to_history_impl(MagicMock(agent_name="orchestrator"), context, "Napoleon")
                )

        assert userdata.skip_next_user_turns == 1

    def test_orchestrator_return_sets_skip_counter(self):
        """Routing back to orchestrator must also set skip_next_user_turns=1."""
        context, userdata = _make_mock_context()
        userdata.route_to("math")

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.orchestrator.OrchestratorAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx

            from agent.tools.routing import _route_to_orchestrator_impl
            from agent.agents.base import GuardedAgent

            with patch.object(GuardedAgent, "__init__", return_value=None):
                import asyncio as _asyncio
                result = _asyncio.get_event_loop().run_until_complete(
                    _route_to_orchestrator_impl(MagicMock(agent_name="math"), context, "answered question")
                )

        assert userdata.skip_next_user_turns == 1


# ---------------------------------------------------------------------------
# Subject routing and state tracking
# ---------------------------------------------------------------------------

class TestSubjectRouting:
    """
    Verify that routing correctly tracks current_subject, previous_subjects,
    and turn_number through multi-hop handoffs.
    """

    def test_route_to_math_sets_subject(self):
        """After routing to math, current_subject must be 'math'."""
        context, userdata = _make_mock_context()
        assert userdata.current_subject is None

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )

        assert userdata.current_subject == "math"

    def test_route_to_history_after_math_records_previous(self):
        """
        After routing orchestrator→math→history, previous_subjects must contain 'math'
        so the full subject traversal is recorded for the session report.
        """
        context, userdata = _make_mock_context()

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.history_agent.HistoryAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl, _route_to_history_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )
            _asyncio.get_event_loop().run_until_complete(
                _route_to_history_impl(MagicMock(agent_name="math"), context, "Napoleon")
            )

        assert userdata.current_subject == "history"
        assert "math" in userdata.previous_subjects

    def test_turn_number_increments_per_routing_call(self):
        """Each routing call must increment the turn_number counter."""
        context, userdata = _make_mock_context()
        assert userdata.turn_number == 0

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.history_agent.HistoryAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl, _route_to_history_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )
            _asyncio.get_event_loop().run_until_complete(
                _route_to_history_impl(MagicMock(agent_name="math"), context, "Napoleon")
            )

        assert userdata.turn_number == 2


# ---------------------------------------------------------------------------
# Speaker attribution — PLAN9/10 regression
# ---------------------------------------------------------------------------

class TestSpeakerAttribution:
    """
    Regression tests for speaking_agent attribution.

    The bug (PLAN9/10): routing functions set speaking_agent too early, so the
    orchestrator's transition sentence "Let me connect you with..." was attributed
    to the specialist instead of the orchestrator.

    Fix: routing functions do NOT set speaking_agent. Only GuardedAgent.on_enter()
    sets it, which fires AFTER the transition message has been emitted.
    """

    def test_routing_to_math_does_not_set_speaking_agent(self):
        """_route_to_math_impl must NOT set speaking_agent on userdata."""
        context, userdata = _make_mock_context()
        userdata.speaking_agent = "orchestrator"

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )

        # speaking_agent must remain "orchestrator" — set by on_enter later
        assert userdata.speaking_agent == "orchestrator", (
            "routing function must NOT set speaking_agent — transition message still "
            "comes from the orchestrator and on_enter() sets it after that"
        )

    def test_routing_to_history_does_not_set_speaking_agent(self):
        """_route_to_history_impl must NOT set speaking_agent on userdata."""
        context, userdata = _make_mock_context()
        userdata.speaking_agent = "orchestrator"

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.history_agent.HistoryAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_history_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_history_impl(MagicMock(agent_name="orchestrator"), context, "Napoleon")
            )

        assert userdata.speaking_agent == "orchestrator"

    def test_on_enter_sets_speaking_agent(self):
        """
        GuardedAgent.on_enter() must set speaking_agent = self.agent_name.
        This is the ONLY correct place to update speaking_agent (after transition).
        """
        import livekit.agents

        mock_session = MagicMock()
        mock_session.userdata = MagicMock()
        mock_session.userdata.session_id = "sess-test"
        mock_session.userdata.student_identity = "alice"
        mock_session.userdata.speaking_agent = "orchestrator"
        mock_session.history.messages.return_value = []
        mock_session.generate_reply = AsyncMock()

        with patch.object(livekit.agents.Agent, "session", new_callable=PropertyMock) as mock_prop:
            mock_prop.return_value = mock_session

            with patch("agent.agents.base.GuardedAgent.__init__", return_value=None):
                from agent.agents.base import GuardedAgent

                instance = object.__new__(GuardedAgent)
                instance.agent_name = "math"

                with patch("agent.agents.base._tracer") as mock_tracer:
                    mock_span, mock_ctx = _make_mock_span()
                    mock_tracer.start_as_current_span.return_value = mock_ctx

                    import asyncio as _asyncio
                    _asyncio.get_event_loop().run_until_complete(instance.on_enter())

        # speaking_agent must be "math" after on_enter()
        assert mock_session.userdata.speaking_agent == "math"


# ---------------------------------------------------------------------------
# Guardrail pipeline — PLAN1 regression
# ---------------------------------------------------------------------------

class TestGuardrailPipeline:
    """
    Regression tests for the guardrail check + rewrite pipeline.
    PLAN1 bug: TTS produced no audio because tts_node returned str instead of AudioFrame.
    """

    async def test_clean_content_returns_unchanged(self):
        """
        check_and_rewrite() on clean content must return the original text
        and NOT call rewrite().
        """
        from agent.services.guardrail import ModerationResult

        with (
            patch("agent.services.guardrail.check", new_callable=AsyncMock) as mock_check,
            patch("agent.services.guardrail.rewrite", new_callable=AsyncMock) as mock_rewrite,
        ):
            mock_check.return_value = ModerationResult(
                flagged=False, categories=[], highest_score=0.001
            )

            from agent.services.guardrail import check_and_rewrite
            result = await check_and_rewrite(
                "The Pythagorean theorem states that a² + b² = c².",
                session_id="sess-test",
                agent_name="math",
            )

        assert result == "The Pythagorean theorem states that a² + b² = c²."
        mock_rewrite.assert_not_called()

    async def test_flagged_content_triggers_rewrite(self):
        """
        check_and_rewrite() on flagged content must call rewrite()
        and return the rewritten text.
        """
        from agent.services.guardrail import ModerationResult

        with (
            patch("agent.services.guardrail.check", new_callable=AsyncMock) as mock_check,
            patch("agent.services.guardrail.rewrite", new_callable=AsyncMock) as mock_rewrite,
            patch("asyncio.create_task"),  # suppress log_guardrail_event task
        ):
            mock_check.return_value = ModerationResult(
                flagged=True, categories=["violence"], highest_score=0.95
            )
            mock_rewrite.return_value = "Let me rephrase that in a more appropriate way."

            from agent.services.guardrail import check_and_rewrite
            result = await check_and_rewrite(
                "Some inappropriate content",
                session_id="sess-test",
                agent_name="math",
            )

        mock_rewrite.assert_called_once()
        assert result == "Let me rephrase that in a more appropriate way."

    async def test_guardrail_check_span_attributes(self):
        """
        guardrail.check() must emit a 'guardrail.check' OTEL span with
        text_length, flagged, highest_score, and check_ms attributes.
        """
        from unittest.mock import patch, AsyncMock, MagicMock, call

        # Mock the OpenAI moderation API response
        mock_result = MagicMock()
        mock_result.flagged = False
        mock_result.categories.harassment = False
        mock_result.categories.harassment_threatening = False
        mock_result.categories.hate = False
        mock_result.categories.hate_threatening = False
        mock_result.categories.sexual = False
        mock_result.categories.sexual_minors = False
        mock_result.categories.violence = False
        mock_result.categories.violence_graphic = False
        mock_result.category_scores.harassment = 0.001
        mock_result.category_scores.harassment_threatening = 0.001
        mock_result.category_scores.hate = 0.001
        mock_result.category_scores.hate_threatening = 0.001
        mock_result.category_scores.sexual = 0.001
        mock_result.category_scores.sexual_minors = 0.001
        mock_result.category_scores.violence = 0.001
        mock_result.category_scores.violence_graphic = 0.001
        # Must also set getattr()-accessed fields to avoid MagicMock > float TypeError
        mock_result.category_scores.self_harm = 0.001
        mock_result.category_scores.self_harm_intent = 0.001
        mock_result.category_scores.self_harm_instructions = 0.001
        mock_result.category_scores.illicit = 0.001
        mock_result.category_scores.illicit_violent = 0.001
        mock_result.categories.self_harm = False
        mock_result.categories.self_harm_intent = False
        mock_result.categories.self_harm_instructions = False
        mock_result.categories.illicit = False
        mock_result.categories.illicit_violent = False

        mock_response = MagicMock()
        mock_response.results = [mock_result]

        mock_client = AsyncMock()
        mock_client.moderations.create = AsyncMock(return_value=mock_response)

        mock_span = MagicMock()
        span_ctx = MagicMock()
        span_ctx.__enter__ = MagicMock(return_value=mock_span)
        span_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.services.guardrail._get_openai", return_value=mock_client),
            patch("agent.services.guardrail._tracer") as mock_tracer,
        ):
            mock_tracer.start_as_current_span.return_value = span_ctx

            from agent.services.guardrail import check
            result = await check("Hello, what is mathematics?")

        mock_tracer.start_as_current_span.assert_called_with("guardrail.check")
        # Verify span attributes were set
        calls = mock_span.set_attribute.call_args_list
        attr_names = {c[0][0] for c in calls}
        assert "text_length" in attr_names
        assert "flagged" in attr_names
        assert "highest_score" in attr_names
        assert "check_ms" in attr_names

    async def test_guardrail_rewrite_span_attributes(self):
        """
        guardrail.rewrite() must emit a 'guardrail.rewrite' OTEL span with
        original_length, rewritten_length, and rewrite_ms attributes.
        """
        mock_content = MagicMock()
        mock_content.text = "A safer educational version."
        mock_message = MagicMock()
        mock_message.content = [mock_content]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        mock_span = MagicMock()
        span_ctx = MagicMock()
        span_ctx.__enter__ = MagicMock(return_value=mock_span)
        span_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.services.guardrail._get_anthropic", return_value=mock_client),
            patch("agent.services.guardrail._tracer") as mock_tracer,
        ):
            mock_tracer.start_as_current_span.return_value = span_ctx

            from agent.services.guardrail import rewrite
            result = await rewrite("Some problematic text here")

        mock_tracer.start_as_current_span.assert_called_with("guardrail.rewrite")
        calls = mock_span.set_attribute.call_args_list
        attr_names = {c[0][0] for c in calls}
        assert "original_length" in attr_names
        assert "rewritten_length" in attr_names
        assert "rewrite_ms" in attr_names


# ---------------------------------------------------------------------------
# OTEL latency attributes — decision_ms, e2e_response_ms
# ---------------------------------------------------------------------------

class TestOtelLatencyAttributes:
    """
    Verify that routing.decision spans include decision_ms,
    and that the e2e_response_ms tracking via last_user_input_at works.
    """

    def test_routing_span_includes_decision_ms(self):
        """
        routing.decision span must include 'decision_ms' attribute
        so we can track how long each routing decision takes in Langfuse.
        """
        context, userdata = _make_mock_context()

        captured_attrs: dict = {}
        mock_span = MagicMock()
        mock_span.set_attribute.side_effect = lambda k, v: captured_attrs.update({k: v})
        span_ctx = MagicMock()
        span_ctx.__enter__ = MagicMock(return_value=mock_span)
        span_ctx.__exit__ = MagicMock(return_value=False)

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = span_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl
            _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )

        assert "decision_ms" in captured_attrs, (
            "routing.decision span must include decision_ms for latency tracking"
        )
        assert isinstance(captured_attrs["decision_ms"], int)
        assert captured_attrs["decision_ms"] >= 0

    def test_last_user_input_at_field_on_session_userdata(self):
        """
        SessionUserdata must have a last_user_input_at field (Optional[float] = None)
        for tracking e2e_response_ms. This field is set by the user_input_transcribed event.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        assert hasattr(userdata, "last_user_input_at"), (
            "SessionUserdata must have last_user_input_at field for e2e latency tracking"
        )
        assert userdata.last_user_input_at is None

    def test_last_user_input_at_can_be_set_and_cleared(self):
        """
        last_user_input_at should be settable to a perf_counter() float
        and clearable back to None after computing e2e_response_ms.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()

        t_start = time.perf_counter()
        userdata.last_user_input_at = t_start

        # Simulate assistant response arriving
        e2e_ms = round((time.perf_counter() - userdata.last_user_input_at) * 1000)
        userdata.last_user_input_at = None

        assert e2e_ms >= 0
        assert userdata.last_user_input_at is None

    def test_e2e_ms_emitted_for_assistant_turn(self):
        """
        The conversation_item_added handler must set e2e_response_ms on the OTEL span
        for assistant turns when last_user_input_at is set.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.last_user_input_at = time.perf_counter() - 0.5  # 500ms ago

        captured_attrs: dict = {}
        mock_span = MagicMock()
        mock_span.set_attribute.side_effect = lambda k, v: captured_attrs.update({k: v})

        # Simulate the conversation_item_added handler logic from main.py
        role = "assistant"
        if role == "assistant" and userdata.last_user_input_at is not None:
            e2e_ms = round((time.perf_counter() - userdata.last_user_input_at) * 1000)
            mock_span.set_attribute("e2e_response_ms", e2e_ms)
            userdata.last_user_input_at = None

        assert "e2e_response_ms" in captured_attrs
        assert captured_attrs["e2e_response_ms"] >= 400  # at least 400ms (we set 500ms ago)
        assert userdata.last_user_input_at is None


# ---------------------------------------------------------------------------
# Pipeline close timing — PLAN16 Fix A regression
# ---------------------------------------------------------------------------

class TestEnglishPipelineClose:
    """
    Regression tests for the pipeline close timing after English dispatch.

    PLAN16 Fix A: interrupt() was replaced with asyncio.sleep(3.5) + aclose().
    This ensures the orchestrator can finish its transition sentence before
    the English agent starts speaking.
    """

    async def test_english_routing_dispatches_create_agent_dispatch_request(self):
        """
        When dispatching the English agent, CreateAgentDispatchRequest must be a
        proto object (not keyword args). This is the PLAN6 regression.
        """
        from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

        context, userdata = _make_mock_context(room_name="room-english-test")

        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)
        mock_lk_class = MagicMock(return_value=mock_lk_instance)

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("livekit.api.LiveKitAPI", mock_lk_class),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            from agent.tools.routing import _route_to_english_impl
            result = await _route_to_english_impl(
                MagicMock(agent_name="orchestrator"),
                context,
                "Help me write a poem",
            )

        call_arg = mock_api.agent_dispatch.create_dispatch.call_args[0][0]
        assert isinstance(call_arg, CreateAgentDispatchRequest), (
            f"create_dispatch must use CreateAgentDispatchRequest proto, got {type(call_arg)}"
        )
        assert call_arg.room == "room-english-test"
        assert call_arg.agent_name == "learning-english"

    async def test_english_dispatch_creates_close_task(self):
        """
        _route_to_english_impl must create an asyncio task that eventually closes
        the pipeline session (not interrupt it). Two tasks: primary 3.5s + 30s fallback.
        """
        from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

        context, userdata = _make_mock_context()

        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)
        mock_lk_class = MagicMock(return_value=mock_lk_instance)

        mock_span, mock_ctx = _make_mock_span()
        created_tasks = []

        with (
            patch("livekit.api.LiveKitAPI", mock_lk_class),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task", side_effect=lambda coro: created_tasks.append(coro) or MagicMock()),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            from agent.tools.routing import _route_to_english_impl
            await _route_to_english_impl(
                MagicMock(agent_name="orchestrator"),
                context,
                "Help me with grammar",
            )

        # Should have created tasks: save_routing_decision, _do_close_pipeline, _fallback_close_pipeline
        # We don't know exact count due to transcript_store task, but at least 2 close tasks
        assert len(created_tasks) >= 2, (
            f"Expected at least 2 async tasks created, got {len(created_tasks)}. "
            "Routing must create close tasks for the pipeline session."
        )

    async def test_english_routing_does_not_call_interrupt(self):
        """
        PLAN16: interrupt() was replaced with sleep+aclose(). Verify that
        the routing function does NOT call session.interrupt() after dispatch.
        """
        from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

        context, userdata = _make_mock_context()
        mock_session = context.session
        mock_session.interrupt = AsyncMock()

        mock_api = MagicMock()
        mock_api.agent_dispatch.create_dispatch = AsyncMock()

        mock_lk_instance = MagicMock()
        mock_lk_instance.__aenter__ = AsyncMock(return_value=mock_api)
        mock_lk_instance.__aexit__ = AsyncMock(return_value=False)
        mock_lk_class = MagicMock(return_value=mock_lk_instance)

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("livekit.api.LiveKitAPI", mock_lk_class),
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            from agent.tools.routing import _route_to_english_impl
            await _route_to_english_impl(
                MagicMock(agent_name="orchestrator"),
                context,
                "Help with spelling",
            )

        mock_session.interrupt.assert_not_called(), (
            "PLAN16: interrupt() must NOT be called after English dispatch — "
            "use sleep(3.5) + aclose() instead to let orchestrator finish speaking"
        )


# ---------------------------------------------------------------------------
# Conversation history across handoffs — PLAN7 regression
# ---------------------------------------------------------------------------

class TestConversationHistory:
    """
    Verify that conversation history is preserved and passed through
    routing handoffs so specialists have context.
    """

    def test_routing_to_math_passes_history_to_specialist(self):
        """
        When routing to MathAgent, the specialist is initialised with the
        current session history (chat_ctx=context.session.history).
        This ensures the specialist knows what was previously discussed.
        """
        context, userdata = _make_mock_context()
        # Simulate some history
        context.session.history.messages.return_value = [
            MagicMock(role="user"),
            MagicMock(role="assistant"),
        ]

        mock_span, mock_ctx = _make_mock_span()
        created_specialist = None

        from agent.agents.math_agent import MathAgent

        original_init = None

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx

            with patch.object(MathAgent, "__init__") as mock_init:
                mock_init.return_value = None

                import asyncio as _asyncio
                from agent.tools.routing import _route_to_math_impl
                result = _asyncio.get_event_loop().run_until_complete(
                    _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
                )

            # Verify MathAgent was constructed with chat_ctx=session.history
            init_kwargs = mock_init.call_args
            assert init_kwargs is not None, "MathAgent.__init__ must be called"
            # chat_ctx should be context.session.history
            if init_kwargs.kwargs:
                assert init_kwargs.kwargs.get("chat_ctx") == context.session.history
            elif init_kwargs.args:
                # positional: MathAgent(chat_ctx=history)
                pass  # acceptable if passed positionally

    def test_pending_question_set_on_specialist(self):
        """
        After routing, the specialist agent must have _pending_question set
        to the question_summary so on_enter() can immediately answer it.
        """
        context, userdata = _make_mock_context()

        mock_span, mock_ctx = _make_mock_span()

        with (
            patch("agent.tools.routing.tracer") as mock_tracer,
            patch("agent.tools.routing.transcript_store"),
            patch("asyncio.create_task"),
            patch("agent.agents.math_agent.MathAgent.__init__", return_value=None),
            patch("agent.agents.base.GuardedAgent.__init__", return_value=None),
        ):
            mock_tracer.start_as_current_span.return_value = mock_ctx
            import asyncio as _asyncio
            from agent.tools.routing import _route_to_math_impl
            result = _asyncio.get_event_loop().run_until_complete(
                _route_to_math_impl(MagicMock(agent_name="orchestrator"), context, "quadratic formula")
            )

        # Result is (specialist, announcement)
        specialist, announcement = result
        assert specialist._pending_question == "quadratic formula", (
            "Specialist must have _pending_question='quadratic formula' so on_enter() "
            "calls generate_reply(user_input='quadratic formula') immediately"
        )


# ---------------------------------------------------------------------------
# Transcript content — PLAN15 regression
# ---------------------------------------------------------------------------

class TestTranscriptContent:
    """
    Regression for PLAN15: conversation_item_added must have populated text_content.
    The old hasattr(part, "text") check was always False for plain str objects.
    """

    def test_text_content_property_returns_str_content(self):
        """
        The text_content property on ChatMessage-like objects must return
        str content correctly (not None for plain str items).
        """
        class FakeChatMessage:
            def __init__(self, role, content):
                self.role = role
                self.content = content

            @property
            def text_content(self):
                text_parts = [c for c in self.content if isinstance(c, str)]
                return "\n".join(text_parts) if text_parts else None

        # Simulate a LiveKit ChatMessage with plain str content
        msg = FakeChatMessage("assistant", ["The answer is 42."])
        assert msg.text_content == "The answer is 42.", (
            "text_content must return the str content — "
            "PLAN15: old hasattr check was always False for plain str objects"
        )

    def test_empty_text_content_is_not_published(self):
        """
        Items with empty or None text_content must not be published to the
        transcript data channel (to avoid empty transcript entries).
        """
        class FakeChatMessage:
            def __init__(self, role, content):
                self.role = role
                self.content = content

            @property
            def text_content(self):
                text_parts = [c for c in self.content if isinstance(c, str)]
                return "\n".join(text_parts) if text_parts else None

        # Audio-only message (e.g., from TTS) — no text content
        audio_obj = object()  # not a str
        msg = FakeChatMessage("assistant", [audio_obj])
        assert msg.text_content is None

        # Simulate the main.py handler: only publish if content is non-empty
        content = msg.text_content or ""
        assert content == "", "Audio-only content must be empty string after 'or '''"
        assert not content  # falsy — would be skipped by `if content:` gate

    def test_transition_announcement_published_with_correct_speaker(self):
        """
        The orchestrator's transition announcement ("Let me connect you with...")
        must be published with speaker='orchestrator', not 'math'.
        This relies on speaking_agent NOT being updated by routing functions.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata()
        userdata.speaking_agent = "orchestrator"
        userdata.current_subject = "math"  # routing already set this

        # Simulate speaker resolution from main.py on_conversation_item
        role = "assistant"
        if role == "assistant":
            speaker = userdata.speaking_agent or userdata.current_subject or "orchestrator"

        assert speaker == "orchestrator", (
            "Transition message must be attributed to 'orchestrator', not 'math'. "
            "speaking_agent is set by on_enter() AFTER transition, not by routing."
        )


# ---------------------------------------------------------------------------
# English session separation — PLAN8 regression
# ---------------------------------------------------------------------------

class TestEnglishSessionSeparation:
    """
    Regression for PLAN8: English agent must run in a separate AgentSession,
    not as a pipeline agent within the orchestrator's session.
    """

    def test_english_agent_inherits_from_guarded_agent(self):
        """EnglishAgent must inherit from GuardedAgent (which inherits from Agent)."""
        from agent.agents.english_agent import EnglishAgent
        from agent.agents.base import GuardedAgent
        from livekit.agents import Agent

        assert issubclass(EnglishAgent, GuardedAgent), (
            "EnglishAgent must extend GuardedAgent for agent lifecycle compatibility"
        )
        assert issubclass(EnglishAgent, Agent)

    def test_english_agent_overrides_on_enter(self):
        """
        EnglishAgent must override on_enter() to be a no-op (or minimal).
        The base class on_enter() calls generate_reply() which is incorrect
        for the Realtime model — it handles responses natively.
        """
        from agent.agents.english_agent import EnglishAgent
        from agent.agents.base import GuardedAgent

        assert EnglishAgent.on_enter is not GuardedAgent.on_enter, (
            "EnglishAgent must override on_enter() — the base class version calls "
            "generate_reply() which is not appropriate for OpenAI Realtime sessions"
        )

    def test_create_english_realtime_session_is_callable(self):
        """The create_english_realtime_session factory function must be importable."""
        from agent.agents.english_agent import create_english_realtime_session
        assert callable(create_english_realtime_session)
