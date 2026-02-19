"""
GuardedAgent — base class for all pipeline agents (Math, History, Orchestrator).

Overrides tts_node to inject the guardrail between LLM text output and TTS.

Data flow:
  LLM streams text
    → tts_node buffers at sentence boundaries
    → guardrail.check_and_rewrite() per sentence (~5ms clean, ~150ms if flagged)
    → safe text fed to Agent.default.tts_node → audio frames → student hears it

NOTE: In livekit-agents v1.4, tts_node must return AsyncIterable[rtc.AudioFrame],
NOT AsyncIterable[str]. The override runs the guardrail on text, then delegates
to Agent.default.tts_node to get the actual audio frames.

NOTE: This does NOT apply to the English agent (OpenAI Realtime / RealtimeModel),
which processes audio natively. See english_agent.py for its guardrail approach.

See PLAN.md: GuardedAgent Base Class Pattern
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator, AsyncIterable, Optional

from livekit import rtc
from livekit.agents import Agent, ModelSettings

from agent.services import guardrail as guardrail_service
from agent.services.langfuse_setup import get_tracer as _get_tracer

logger = logging.getLogger(__name__)
_tracer = _get_tracer("agent-lifecycle")
_tts_tracer = _get_tracer("tts-pipeline")

# Sentence-boundary punctuation — fire guardrail per complete sentence
SENTENCE_ENDINGS = (".", "!", "?", ":", ";")


class GuardedAgent(Agent):
    """
    All pipeline agents inherit from this class instead of Agent directly.
    Provides sentence-boundary guardrail buffering in tts_node.
    """

    # Subclasses set this to identify themselves in guardrail audit logs
    agent_name: str = "unknown"

    def tts_node(
        self,
        text: AsyncIterable[str],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[rtc.AudioFrame, None]:
        """
        Override tts_node to run the safety guardrail between LLM and TTS.

        v1.4 API: tts_node receives text stream, must yield rtc.AudioFrame.
        We filter the text through the guardrail, then delegate to the default
        TTS implementation to synthesise audio frames.
        """
        # Capture self for use in inner generator
        agent = self

        async def _guardrailed_audio() -> AsyncGenerator[rtc.AudioFrame, None]:
            session_id = "unknown"
            try:
                session_id = agent.session.userdata.session_id
            except AttributeError:
                pass

            async def _safe_text_stream() -> AsyncGenerator[str, None]:
                buffer = ""
                async for chunk in text:
                    buffer += chunk
                    stripped = buffer.rstrip()
                    if any(stripped.endswith(p) for p in SENTENCE_ENDINGS):
                        t_guardrail_start = time.perf_counter()
                        safe_text = await guardrail_service.check_and_rewrite(
                            buffer,
                            session_id=session_id,
                            agent_name=agent.agent_name,
                        )
                        t_guardrail_done = time.perf_counter()
                        with _tts_tracer.start_as_current_span("tts.sentence") as span:
                            span.set_attribute("sentence_length", len(buffer))
                            span.set_attribute("guardrail_ms", round((t_guardrail_done - t_guardrail_start) * 1000))
                            span.set_attribute("was_rewritten", safe_text != buffer)
                            span.set_attribute("agent_name", agent.agent_name)
                        yield safe_text
                        buffer = ""

                # Flush any remaining partial sentence at end of stream
                if buffer.strip():
                    t_guardrail_start = time.perf_counter()
                    safe_text = await guardrail_service.check_and_rewrite(
                        buffer,
                        session_id=session_id,
                        agent_name=agent.agent_name,
                    )
                    t_guardrail_done = time.perf_counter()
                    with _tts_tracer.start_as_current_span("tts.sentence") as span:
                        span.set_attribute("sentence_length", len(buffer))
                        span.set_attribute("guardrail_ms", round((t_guardrail_done - t_guardrail_start) * 1000))
                        span.set_attribute("was_rewritten", safe_text != buffer)
                        span.set_attribute("agent_name", agent.agent_name)
                    yield safe_text

            # Delegate to default TTS — converts text → rtc.AudioFrame
            async for frame in Agent.default.tts_node(agent, _safe_text_stream(), model_settings):
                yield frame

        return _guardrailed_audio()

    async def on_enter(self) -> None:
        """Called by LiveKit when this agent becomes active.

        Proactively generates a reply to the current conversation state:
        - OrchestratorAgent: greets the student on session start
        - Specialist agents: immediately answers the pending question from history
        """
        # Update speaking_agent FIRST so transcript handler knows who is actively speaking.
        # This fires AFTER the transition message ("Let me connect you with...") has been
        # emitted, so the transition message correctly shows the PREVIOUS speaker.
        try:
            self.session.userdata.speaking_agent = self.agent_name
        except AttributeError:
            pass

        # OTEL span to mark agent activation — visible in Langfuse timeline
        try:
            session_id = self.session.userdata.session_id
            student_identity = self.session.userdata.student_identity
        except AttributeError:
            session_id = "unknown"
            student_identity = "unknown"

        with _tracer.start_as_current_span("agent.activated") as span:
            span.set_attribute("agent_name", self.agent_name)
            span.set_attribute("langfuse.session_id", session_id)
            span.set_attribute("langfuse.user_id", student_identity)
            span.set_attribute("session.id", session_id)

        # Diagnostic logging — captured in Langfuse via OTEL to help debug
        # cases where an agent answers a stale question from history.
        # FIXED (PLAN8): use text_content property — hasattr(part, "text") was always
        # False for plain str objects, producing empty last_user_text.
        try:
            msgs = list(self.session.history.messages())
            last_user_text = ""
            for msg in reversed(msgs):
                if msg.role == "user":
                    last_user_text = msg.text_content or ""
                    break
            logger.info(
                "%s.on_enter history_length=%d last_user=%.150r",
                self.agent_name, len(msgs), last_user_text,
            )
        except Exception:
            logger.debug("%s.on_enter: could not inspect history", self.agent_name)

        pending_q = getattr(self, "_pending_question", None)
        if pending_q:
            await self.session.generate_reply(user_input=pending_q)
        else:
            await self.session.generate_reply()
