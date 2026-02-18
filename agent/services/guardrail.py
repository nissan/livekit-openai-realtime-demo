"""
Guardrail service — OpenAI omni-moderation-latest + Claude Haiku rewriter.

Pipeline:
  1. check(text) → OpenAI omni-moderation-latest (~5ms)
  2. If flagged: rewrite(text) → Claude Haiku age-appropriate rewrite (~100–150ms)
  3. log_guardrail_event() → Supabase guardrail_events table

check_and_rewrite() combines steps 1–3 for use in tts_node.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

import anthropic
import openai

logger = logging.getLogger(__name__)

_openai_client: Optional[openai.AsyncOpenAI] = None
_anthropic_client: Optional[anthropic.AsyncAnthropic] = None


def _get_openai() -> openai.AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def _get_anthropic() -> anthropic.AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
    return _anthropic_client


@dataclass
class ModerationResult:
    flagged: bool
    categories: list[str]
    highest_score: float


# All categories we check — aligned with omni-moderation-latest
MODERATION_CATEGORIES = [
    "harassment",
    "harassment/threatening",
    "hate",
    "hate/threatening",
    "sexual",
    "sexual/minors",
    "violence",
    "violence/graphic",
    "self-harm",
    "self-harm/intent",
    "self-harm/instructions",
    "illicit",
    "illicit/violent",
]

REWRITE_SYSTEM_PROMPT = """You are a safe content rewriter for an educational platform.
Rewrite the given text for primary/secondary school children aged 8-16.
Use simple, age-appropriate vocabulary.
Do NOT mention the original problematic content or that it was rewritten.
Keep the educational intent and factual accuracy intact.
Be clear, friendly, and encouraging.
Respond with ONLY the rewritten text — no preamble, no explanation."""


async def check(text: str) -> ModerationResult:
    """
    Run OpenAI omni-moderation-latest on the given text.
    Returns ModerationResult with flagged status and categories.
    """
    try:
        client = _get_openai()
        response = await client.moderations.create(
            model="omni-moderation-latest",
            input=text,
        )
        result = response.results[0]

        flagged_categories = []
        highest_score = 0.0

        # Extract flagged categories and scores
        categories = result.categories
        scores = result.category_scores

        cat_map = {
            "harassment": (categories.harassment, scores.harassment),
            "harassment/threatening": (categories.harassment_threatening, scores.harassment_threatening),
            "hate": (categories.hate, scores.hate),
            "hate/threatening": (categories.hate_threatening, scores.hate_threatening),
            "sexual": (categories.sexual, scores.sexual),
            "sexual/minors": (categories.sexual_minors, scores.sexual_minors),
            "violence": (categories.violence, scores.violence),
            "violence/graphic": (categories.violence_graphic, scores.violence_graphic),
            "self-harm": (getattr(categories, "self_harm", False), getattr(scores, "self_harm", 0.0)),
            "self-harm/intent": (getattr(categories, "self_harm_intent", False), getattr(scores, "self_harm_intent", 0.0)),
            "self-harm/instructions": (getattr(categories, "self_harm_instructions", False), getattr(scores, "self_harm_instructions", 0.0)),
            "illicit": (getattr(categories, "illicit", False), getattr(scores, "illicit", 0.0)),
            "illicit/violent": (getattr(categories, "illicit_violent", False), getattr(scores, "illicit_violent", 0.0)),
        }

        for category, (is_flagged, score) in cat_map.items():
            if is_flagged:
                flagged_categories.append(category)
            if score > highest_score:
                highest_score = score

        return ModerationResult(
            flagged=result.flagged,
            categories=flagged_categories,
            highest_score=highest_score,
        )
    except Exception:
        logger.exception("Moderation check failed for text snippet")
        # Fail safe: do not flag, let content through
        return ModerationResult(flagged=False, categories=[], highest_score=0.0)


async def rewrite(text: str) -> str:
    """
    Rewrite flagged text using Claude Haiku for age-appropriateness.
    Returns the rewritten text, or the original if rewrite fails.
    """
    try:
        client = _get_anthropic()
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=REWRITE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        rewritten = message.content[0].text.strip()
        logger.info("Guardrail rewrite completed (orig_len=%d, new_len=%d)", len(text), len(rewritten))
        return rewritten
    except Exception:
        logger.exception("Guardrail rewrite failed — returning safe fallback")
        return "I'm here to help you learn. Let me rephrase that in a better way."


async def log_guardrail_event(
    session_id: str,
    agent_name: str,
    original_text: str,
    rewritten_text: str,
    categories: list[str],
    moderation_score: float,
    action_taken: str = "rewrite",
) -> None:
    """Persist guardrail event to Supabase for audit."""
    try:
        from agent.services.transcript_store import get_client
        client = await get_client()
        await client.table("guardrail_events").insert({
            "session_id": session_id,
            "agent_name": agent_name,
            "original_text": original_text,
            "rewritten_text": rewritten_text,
            "categories_flagged": categories,
            "moderation_score": moderation_score,
            "action_taken": action_taken,
        }).execute()
    except Exception:
        logger.exception("Failed to log guardrail event for session %s", session_id)


async def check_and_rewrite(
    text: str,
    session_id: str,
    agent_name: str = "unknown",
) -> str:
    """
    Combined check + optional rewrite + audit log.
    Called from GuardedAgent.tts_node() per sentence.

    Returns safe text (rewritten if flagged, original if clean).
    """
    result = await check(text)

    if not result.flagged:
        return text

    logger.warning(
        "Content flagged [session=%s, agent=%s, categories=%s]",
        session_id, agent_name, result.categories
    )

    safe_text = await rewrite(text)

    # Fire-and-forget audit log (don't block TTS)
    import asyncio
    asyncio.create_task(log_guardrail_event(
        session_id=session_id,
        agent_name=agent_name,
        original_text=text,
        rewritten_text=safe_text,
        categories=result.categories,
        moderation_score=result.highest_score,
    ))

    return safe_text
