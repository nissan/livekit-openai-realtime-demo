"""
EnglishAgent — OpenAI Realtime API (gpt-realtime) for English tutoring.

⚠️ CRITICAL ARCHITECTURAL CONSTRAINT:
RealtimeModel replaces the entire audio pipeline — it cannot be mixed with
traditional STT+LLM+TTS pipeline agents in a single AgentSession.

This agent runs in a SEPARATE AgentSession (worker name: "learning-english")
in the SAME LiveKit room as the orchestrator pipeline session.

See PLAN.md: English Agent section + Critical Gotchas #11.

Guardrail approach for Realtime:
  tts_node does NOT apply to RealtimeModel (audio is native speech-to-speech).
  Instead, use conversation_item_added callback for post-hoc audit logging.
  If content is flagged, interrupt playback and trigger a safe regeneration.
  This is an accepted trade-off for the ~230–290ms TTFB latency benefit.

Two-session architecture:
  - Pipeline session (learning-orchestrator): Orchestrator, Math, History
  - Realtime session (learning-english): English agent (this file)

  When orchestrator routes to English → dispatches learning-english worker
  → pipeline session goes silent.
  When English agent routes back → dispatches learning-orchestrator worker
  → English session exits.

Fallback: If two-session coordination is too complex, degrade to:
  openai.LLM(model="gpt-4o") in the pipeline session (+~500ms latency).
  See PLAN.md: English Agent Fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from livekit.agents import AgentSession, RunContext, function_tool
from livekit.plugins import openai
from livekit.plugins.openai import realtime
from livekit.plugins.openai.realtime.realtime_model import InputAudioTranscription
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

from agent.agents.base import GuardedAgent
from agent.services import guardrail as guardrail_service
from agent.services.langfuse_setup import get_tracer as _get_tracer

logger = logging.getLogger(__name__)
_tracer = _get_tracer("english-realtime-session")

ENGLISH_SYSTEM_PROMPT = """You are an expert English language and literature tutor for students aged 8–16.

Your role:
- Help with reading comprehension, writing skills, grammar, and vocabulary
- Explain literary devices (metaphor, simile, alliteration, etc.) with engaging examples
- Assist with essay structure, argument development, and creative writing
- Read extracts and analyse them together with the student
- Use encouraging language and build confidence in communication skills
- Adapt to the student's language level — from basic literacy to advanced literature

Topics: grammar and punctuation, creative writing, poetry analysis, novel studies,
essay writing, public speaking, vocabulary development, reading comprehension.

Keep responses conversational and engaging — you are speaking directly with the student.

When the student says goodbye, thank them for the session, and ALWAYS call
route_back_to_orchestrator so the main tutor can give a proper farewell.
When the student asks about maths, history, or any other subject outside English,
ALWAYS call route_back_to_orchestrator immediately.
"""

# Realtime model — GA model released Aug 2025 (was gpt-4o-realtime-preview)
# 20% cheaper than preview. See PLAN.md Critical Gotchas #15.
_REALTIME_MODEL = "gpt-realtime"


class EnglishAgent(GuardedAgent):
    """
    English specialist agent using OpenAI Realtime for native speech-to-speech.

    NOTE: tts_node guardrail is NOT active here — RealtimeModel bypasses the
    TTS pipeline entirely. Guardrail is handled via conversation_item_added
    callback in the Realtime session configuration.
    """
    agent_name = "english"

    def __init__(self, chat_ctx=None):
        # For the Realtime session, the agent itself is simpler —
        # the RealtimeModel handles everything
        super().__init__(
            instructions=ENGLISH_SYSTEM_PROMPT,
            chat_ctx=chat_ctx,
        )
        logger.info("EnglishAgent initialised (realtime, model=%s)", _REALTIME_MODEL)

    async def on_enter(self) -> None:
        # English Realtime session calls generate_reply() with initial_question
        # from dispatch metadata — we skip the default no-context on_enter.
        pass

    @function_tool(
        description=(
            "Route back to the orchestrator when: the student asks about a different "
            "subject (maths, history, etc.); OR the student says goodbye, thanks, or "
            "wants to end or pause the tutoring session."
        )
    )
    async def route_back_to_orchestrator(
        self,
        context: RunContext,
        reason: str,
    ) -> str:
        """
        Signal that the student has moved to a different topic or wants to end.
        The Realtime session will dispatch the pipeline orchestrator back to the
        room and this English session will close.
        """
        logger.info("English agent routing back to orchestrator: %s", reason)
        session_id = context.session.userdata.session_id
        room_name = context.session.userdata.room_name

        # Dispatch pipeline orchestrator back to the room
        try:
            livekit_url = os.environ["LIVEKIT_URL"]
            api_key = os.environ["LIVEKIT_API_KEY"]
            api_secret = os.environ["LIVEKIT_API_SECRET"]

            from livekit.api import LiveKitAPI
            async with LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret) as api:
                await api.agent_dispatch.create_dispatch(
                    CreateAgentDispatchRequest(
                        agent_name="learning-orchestrator",
                        room=room_name,
                        metadata=f"return_from_english:{session_id}|question:{reason}",
                    )
                )
        except Exception:
            logger.exception("Failed to dispatch orchestrator on English→back handoff")

        # Close this English session so it cannot compete with the newly dispatched
        # pipeline session (both sessions share the same room and student audio).
        english_session = context.session

        async def _close_english_after_dispatch():
            await asyncio.sleep(3.0)
            try:
                await english_session.aclose()
                logger.info("English session closed after routing back [session=%s]", session_id)
            except Exception:
                logger.exception("Failed to close English session after routing back")

        asyncio.create_task(_close_english_after_dispatch())

        return "Let me pass you back to the main tutor who can help with that."


async def create_english_realtime_session(
    room,
    participant,
    session_userdata,
    initial_question: str = "",
) -> AgentSession:
    """
    Factory for the English Realtime AgentSession.
    Called by the learning-english worker entrypoint.

    The session is configured with RealtimeModel — no STT/TTS/VAD needed
    (Realtime API handles everything natively).
    """
    session = AgentSession(
        userdata=session_userdata,
        llm=realtime.RealtimeModel(
            model=_REALTIME_MODEL,
            voice="shimmer",
            modalities=["audio", "text"],
            input_audio_transcription=InputAudioTranscription(
                model="gpt-4o-mini-transcribe",
            ),
        ),
    )

    agent = EnglishAgent()

    # Post-hoc guardrail + transcript publishing for Realtime session.
    # FIXED (PLAN13): livekit-agents v1.4.2 rejects async callbacks in .on()
    # Use a sync dispatcher that spawns an async task.
    async def _handle_conversation_item(event):
        # FIXED (PLAN15): unwrap ConversationItemAddedEvent — SDK wraps ChatMessage in this event.
        # event.item is the actual ChatMessage; event itself has no .text_content or .role.
        item = event.item
        # PLAN16 diagnostic: log unconditionally to confirm handler fires + content shape.
        # If text_content is None/empty → forwarded_text="" in SDK → explains missing transcript.
        logger.info(
            "English conversation_item_added: role=%s text_content=%r",
            getattr(item, "role", None), getattr(item, "text_content", None)
        )
        content_text = item.text_content or ""

        if item.role == "assistant" and content_text:
            # OTEL span for Langfuse visibility into English Realtime session
            with _tracer.start_as_current_span("conversation.item") as span:
                span.set_attribute("langfuse.session_id", session_userdata.session_id)
                span.set_attribute("langfuse.user_id", session_userdata.student_identity)
                span.set_attribute("session.id", session_userdata.session_id)
                span.set_attribute("user.id", session_userdata.student_identity)
                span.set_attribute("subject_area", "english")
                span.set_attribute("role", "assistant")
                span.set_attribute("session_type", "realtime")
                span.set_attribute("turn", getattr(session_userdata, "turn_number", 0))

            # Guardrail check (post-hoc — cannot interrupt Realtime audio already playing)
            result = await guardrail_service.check(content_text)
            if result.flagged:
                logger.warning(
                    "English Realtime: flagged content detected post-hoc "
                    "[session=%s, categories=%s]",
                    session_userdata.session_id,
                    result.categories,
                )
                await guardrail_service.log_guardrail_event(
                    session_id=session_userdata.session_id,
                    agent_name="english",
                    original_text=content_text,
                    rewritten_text="[post-hoc detection only — Realtime API]",
                    categories=result.categories,
                    moderation_score=result.highest_score,
                    action_taken="audit_only",
                )

            # Publish assistant turn to data channel for real-time transcript display
            payload = json.dumps({
                "speaker": "english",
                "role": "assistant",
                "content": content_text,
                "subject": "english",
                "turn": getattr(session_userdata, "turn_number", 0),
                "session_id": session_userdata.session_id,
            })
            await room.local_participant.publish_data(
                payload.encode(), topic="transcript"
            )

        elif item.role == "user" and content_text:
            # OTEL span for user turns in English Realtime session
            with _tracer.start_as_current_span("conversation.item") as span:
                span.set_attribute("langfuse.session_id", session_userdata.session_id)
                span.set_attribute("langfuse.user_id", session_userdata.student_identity)
                span.set_attribute("session.id", session_userdata.session_id)
                span.set_attribute("subject_area", "english")
                span.set_attribute("role", "user")
                span.set_attribute("session_type", "realtime")

            # Publish user turns so the transcript is complete on both sides
            payload = json.dumps({
                "speaker": "student",
                "role": "user",
                "content": content_text,
                "subject": "english",
                "turn": 0,
                "session_id": session_userdata.session_id,
            })
            await room.local_participant.publish_data(
                payload.encode(), topic="transcript"
            )

    @session.on("conversation_item_added")
    def on_item_added(event):
        asyncio.create_task(_handle_conversation_item(event))

    await session.start(agent, room=room)

    if initial_question:
        # Delay to allow the Realtime WebRTC audio pipeline to fully establish (~1–2s).
        # Calling generate_reply() immediately after session.start() results in silence
        # because the audio channel is not yet ready to transmit the reply.
        async def _greet_with_initial_question():
            await asyncio.sleep(3.0)  # extra time for WebRTC audio pipeline setup
            await session.generate_reply(user_input=initial_question)

        asyncio.create_task(_greet_with_initial_question())

    return session
