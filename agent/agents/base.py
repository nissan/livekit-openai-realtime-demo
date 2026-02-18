"""
GuardedAgent — base class for all pipeline agents (Math, History, Orchestrator).

Overrides tts_node to inject the guardrail between LLM text output and TTS.

Data flow:
  LLM streams text
    → tts_node buffers at sentence boundaries
    → guardrail.check_and_rewrite() per sentence (~5ms clean, ~150ms if flagged)
    → yield safe text to TTS
    → TTS synthesises audio → student hears it

NOTE: This does NOT apply to the English agent (OpenAI Realtime / RealtimeModel),
which processes audio natively. See english_agent.py for its guardrail approach.

See PLAN.md: GuardedAgent Base Class Pattern
"""
from __future__ import annotations

import logging
from typing import AsyncIterable, Optional

from livekit.agents import Agent, ModelSettings

from agent.services import guardrail as guardrail_service

logger = logging.getLogger(__name__)

# Sentence-boundary punctuation — fire guardrail per complete sentence
SENTENCE_ENDINGS = (".", "!", "?", ":", ";")


class GuardedAgent(Agent):
    """
    All pipeline agents inherit from this class instead of Agent directly.
    Provides sentence-boundary guardrail buffering in tts_node.
    """

    # Subclasses set this to identify themselves in guardrail audit logs
    agent_name: str = "unknown"

    async def tts_node(
        self,
        text_stream: AsyncIterable[str],
        model_settings: Optional[ModelSettings] = None,
    ) -> AsyncIterable[str]:
        """
        Override tts_node to run the safety guardrail between LLM and TTS.

        Buffers streamed text at sentence boundaries, runs moderation per sentence,
        rewrites flagged content via Claude Haiku, then yields safe text to TTS.
        """
        buffer = ""
        session_id = "unknown"

        # Get session_id from userdata if available
        try:
            session_id = self.session.userdata.session_id
        except AttributeError:
            pass

        async for chunk in text_stream:
            buffer += chunk

            # Fire guardrail at sentence boundaries — low latency vs per-token
            stripped = buffer.rstrip()
            if any(stripped.endswith(p) for p in SENTENCE_ENDINGS):
                safe_text = await guardrail_service.check_and_rewrite(
                    buffer,
                    session_id=session_id,
                    agent_name=self.agent_name,
                )
                yield safe_text
                buffer = ""

        # Flush any remaining partial sentence at end of stream
        if buffer.strip():
            safe_text = await guardrail_service.check_and_rewrite(
                buffer,
                session_id=session_id,
                agent_name=self.agent_name,
            )
            yield safe_text
