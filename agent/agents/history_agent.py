"""
HistoryAgent — GPT-5.2 pipeline agent for history tutoring.

Explicit data flow (every turn):
  Student speaks
    → [LiveKit VAD] end-of-turn detection
    → [STT: gpt-4o-transcribe] speech → text
    → [GPT-5.2 LLM] text response streamed out
    → [tts_node GUARDRAIL] sentence-buffered moderation + rewrite
    → [TTS: gpt-4o-mini-tts, voice=ash] safe text → audio
    → Student hears response

Expected latency: STT ~150ms + GPT-5.2 TTFB ~300ms + guardrail ~50–200ms/sentence + TTS ~100ms
= ~600–750ms to first audio

Model configured via OPENAI_HISTORY_MODEL env var (see PLAN.md Critical Gotchas #18).
"""
from __future__ import annotations

import logging
import os

from livekit.agents import function_tool, llm, RunContext
from livekit.plugins import openai

from agent.agents.base import GuardedAgent

logger = logging.getLogger(__name__)

HISTORY_SYSTEM_PROMPT = """You are an expert history tutor for students aged 8–16.

Your role:
- Present historical facts accurately and in an age-appropriate way
- Provide balanced perspectives on historical events
- Avoid glorifying violence, warfare, or atrocities — describe them factually but sensitively
- Present disputed history (e.g., colonial history, political events) from multiple perspectives
- Connect historical events to their causes and consequences
- Use engaging storytelling while maintaining factual accuracy
- Encourage critical thinking about primary sources and historical interpretation

When discussing sensitive topics (wars, slavery, genocide, etc.):
- Acknowledge the gravity without graphic detail
- Focus on human experiences, resilience, and lessons learned
- Always place events in their historical context

Topics: world history, ancient civilisations, medieval period, industrial revolution,
20th century conflicts, political history, cultural history, geography and its influence.

When you have fully answered the student's question (including any immediate
follow-up clarifications on the same history topic), call
route_back_to_orchestrator to return control to the main tutor.

If the student asks about mathematics, English, or anything outside history,
do NOT attempt to answer. Acknowledge briefly and call route_back_to_orchestrator
so the main tutor can route to the correct specialist.
"""

# Default to gpt-5.2 — update via env var without code changes
_DEFAULT_HISTORY_MODEL = "gpt-5.2"

HISTORY_TTS_VOICE = "fable"


class HistoryAgent(GuardedAgent):
    """
    History specialist agent.
    Uses GPT-5.2 (400K context) for rich historical narrative.
    Guardrail is fully active via inherited tts_node.
    """
    agent_name = "history"
    tts_voice = HISTORY_TTS_VOICE

    def __init__(self, chat_ctx: llm.ChatContext | None = None):
        model = os.environ.get("OPENAI_HISTORY_MODEL", _DEFAULT_HISTORY_MODEL)
        super().__init__(
            instructions=HISTORY_SYSTEM_PROMPT,
            llm=openai.LLM(model=model),
            tts=openai.TTS(model="gpt-4o-mini-tts", voice=HISTORY_TTS_VOICE),
            chat_ctx=chat_ctx,
        )
        logger.info("HistoryAgent initialised (model=%s)", model)

    @function_tool(
        description=(
            "Return control to the main tutor after fully answering the student's "
            "history question, including any immediate follow-up clarifications. "
            "Do NOT call this mid-explanation. Call it when the current topic is "
            "complete. The main tutor will handle routing for the next question."
        )
    )
    async def route_back_to_orchestrator(
        self,
        context: RunContext,
        reason: str,
    ) -> tuple:
        from agent.tools.routing import _route_to_orchestrator_impl
        return await _route_to_orchestrator_impl(self, context, reason)

    @function_tool(
        description=(
            "Escalate to a human teacher when the student is distressed, "
            "asks something inappropriate, or you are unable to help effectively"
        )
    )
    async def escalate_to_teacher(
        self,
        context: RunContext,
        reason: str,
    ) -> str:
        from agent.tools.routing import _escalate_impl
        return await _escalate_impl(self, context, reason)
