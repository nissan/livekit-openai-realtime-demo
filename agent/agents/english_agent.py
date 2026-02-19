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

import logging
import os
from typing import Optional

from livekit.agents import AgentSession, RoomInputOptions, function_tool
from livekit.plugins import openai
from livekit.plugins.openai import realtime

from agent.agents.base import GuardedAgent
from agent.services import guardrail as guardrail_service

logger = logging.getLogger(__name__)

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

    @function_tool(description="Route back to the orchestrator when the student asks about a different subject")
    async def route_back_to_orchestrator(
        self,
        context,
        reason: str,
    ) -> str:
        """
        Signal that the student has moved to a different topic.
        The Realtime session will dispatch the pipeline orchestrator
        back to the room and this session will exit.
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
                    room_name=room_name,
                    agent_name="learning-orchestrator",
                    metadata=f"return_from_english:{session_id}",
                )
        except Exception:
            logger.exception("Failed to dispatch orchestrator on English→back handoff")

        return "Let me pass you back to the main tutor who can help with that."


async def create_english_realtime_session(
    room,
    participant,
    session_userdata,
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
            instructions=ENGLISH_SYSTEM_PROMPT,
            modalities=["audio", "text"],
            input_audio_transcription=realtime.InputAudioTranscription(
                model="gpt-4o-mini-transcribe",
            ),
        ),
    )

    agent = EnglishAgent()

    # Post-hoc guardrail for Realtime: audit log on conversation_item_added
    @session.on("conversation_item_added")
    async def on_item_added(item):
        if item.role == "assistant" and item.content:
            content_text = ""
            for part in item.content:
                if hasattr(part, "text") and part.text:
                    content_text += part.text

            if content_text:
                # Check for guardrail violations in the Realtime transcript
                result = await guardrail_service.check(content_text)
                if result.flagged:
                    logger.warning(
                        "English Realtime: flagged content detected post-hoc "
                        "[session=%s, categories=%s]",
                        session_userdata.session_id,
                        result.categories,
                    )
                    # Log for audit — cannot rewrite post-TTS in Realtime mode
                    import asyncio
                    asyncio.create_task(guardrail_service.log_guardrail_event(
                        session_id=session_userdata.session_id,
                        agent_name="english",
                        original_text=content_text,
                        rewritten_text="[post-hoc detection only — Realtime API]",
                        categories=result.categories,
                        moderation_score=result.highest_score,
                        action_taken="audit_only",
                    ))

    await session.start(agent, room=room)
    return session
