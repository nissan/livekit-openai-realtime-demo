"""
Shared routing implementations for all pipeline agents.

Extracted from OrchestratorAgent so that specialist agents (MathAgent,
HistoryAgent) can also route between subjects without circular imports.

All impl functions take (agent, context, ...) where `agent` is the GuardedAgent
instance calling the routing tool. This lets us set the `from_agent` OTEL
span attribute correctly regardless of which agent initiates the handoff.

Lazy imports of MathAgent / HistoryAgent inside each function body prevent
circular imports (they import GuardedAgent from base.py, which would otherwise
create a cycle if imported at module level here).
"""
from __future__ import annotations

import asyncio
import logging
import os

from livekit.agents import RunContext

from agent.services import transcript_store, human_escalation
from agent.services.langfuse_setup import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("routing")


async def _route_to_math_impl(agent, context: RunContext, question_summary: str):
    """Hand off to MathAgent within the same pipeline session."""
    from agent.agents.math_agent import MathAgent  # lazy — avoids circular import

    userdata = context.session.userdata
    session_id = userdata.session_id
    from_agent = getattr(agent, "agent_name", "unknown")
    previous_subject = userdata.current_subject or ""
    turn_number = userdata.advance_turn()
    userdata.route_to("math")

    with tracer.start_as_current_span("routing.decision") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("from_agent", from_agent)
        span.set_attribute("to_agent", "math")
        span.set_attribute("turn_number", turn_number)
        span.set_attribute("question_summary", question_summary)
        span.set_attribute("previous_subject", previous_subject)
        span.set_attribute("langfuse.session_id", session_id)
        span.set_attribute("langfuse.user_id", userdata.student_identity)

    asyncio.create_task(transcript_store.save_routing_decision(
        session_id=session_id,
        turn_number=turn_number,
        from_agent=from_agent,
        to_agent="math",
        question_summary=question_summary,
    ))

    logger.info("Routing to MathAgent [from=%s, session=%s]", from_agent, session_id)
    return (
        MathAgent(chat_ctx=context.session.history),
        "Let me connect you with our Mathematics tutor!",
    )


async def _route_to_history_impl(agent, context: RunContext, question_summary: str):
    """Hand off to HistoryAgent within the same pipeline session."""
    from agent.agents.history_agent import HistoryAgent  # lazy — avoids circular import

    userdata = context.session.userdata
    session_id = userdata.session_id
    from_agent = getattr(agent, "agent_name", "unknown")
    previous_subject = userdata.current_subject or ""
    turn_number = userdata.advance_turn()
    userdata.route_to("history")

    with tracer.start_as_current_span("routing.decision") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("from_agent", from_agent)
        span.set_attribute("to_agent", "history")
        span.set_attribute("turn_number", turn_number)
        span.set_attribute("question_summary", question_summary)
        span.set_attribute("previous_subject", previous_subject)
        span.set_attribute("langfuse.session_id", session_id)
        span.set_attribute("langfuse.user_id", userdata.student_identity)

    asyncio.create_task(transcript_store.save_routing_decision(
        session_id=session_id,
        turn_number=turn_number,
        from_agent=from_agent,
        to_agent="history",
        question_summary=question_summary,
    ))

    logger.info("Routing to HistoryAgent [from=%s, session=%s]", from_agent, session_id)
    return (
        HistoryAgent(chat_ctx=context.session.history),
        "Let me connect you with our History tutor!",
    )


async def _route_to_english_impl(agent, context: RunContext, question_summary: str):
    """Dispatch EnglishAgent (OpenAI Realtime) to this room."""
    userdata = context.session.userdata
    session_id = userdata.session_id
    room_name = userdata.room_name
    from_agent = getattr(agent, "agent_name", "unknown")
    previous_subject = userdata.current_subject or ""
    turn_number = userdata.advance_turn()
    userdata.route_to("english")

    with tracer.start_as_current_span("routing.decision") as span:
        span.set_attribute("session_id", session_id)
        span.set_attribute("from_agent", from_agent)
        span.set_attribute("to_agent", "english")
        span.set_attribute("turn_number", turn_number)
        span.set_attribute("question_summary", question_summary)
        span.set_attribute("previous_subject", previous_subject)
        span.set_attribute("langfuse.session_id", session_id)
        span.set_attribute("langfuse.user_id", userdata.student_identity)

    asyncio.create_task(transcript_store.save_routing_decision(
        session_id=session_id,
        turn_number=turn_number,
        from_agent=from_agent,
        to_agent="english",
        question_summary=question_summary,
    ))

    # Dispatch the English Realtime worker to this room
    try:
        from livekit.api import LiveKitAPI
        livekit_url = os.environ["LIVEKIT_URL"]
        api_key = os.environ["LIVEKIT_API_KEY"]
        api_secret = os.environ["LIVEKIT_API_SECRET"]

        async with LiveKitAPI(url=livekit_url, api_key=api_key, api_secret=api_secret) as api:
            await api.agent_dispatch.create_dispatch(
                room_name=room_name,
                agent_name="learning-english",
                metadata=f"session:{session_id}",
            )
        logger.info("Dispatched learning-english worker to room %s", room_name)
    except Exception:
        logger.exception("Failed to dispatch English worker — falling back to pipeline English")
        from livekit.plugins import openai as openai_plugin
        from agent.agents.base import GuardedAgent

        class FallbackEnglishAgent(GuardedAgent):
            agent_name = "english"

            def __init__(self, chat_ctx=None):
                from agent.agents.english_agent import ENGLISH_SYSTEM_PROMPT
                super().__init__(
                    instructions=ENGLISH_SYSTEM_PROMPT,
                    llm=openai_plugin.LLM(model="gpt-4o"),
                    chat_ctx=chat_ctx,
                )

        return (
            FallbackEnglishAgent(chat_ctx=context.session.history),
            "Let me connect you with our English tutor!",
        )

    return "Let me connect you with our English tutor right away!"


async def _escalate_impl(agent, context: RunContext, reason: str) -> str:
    """Escalate to a human teacher."""
    userdata = context.session.userdata
    session_id = userdata.session_id
    room_name = userdata.room_name
    from_agent = getattr(agent, "agent_name", "unknown")
    userdata.escalated = True
    userdata.escalation_reason = reason

    asyncio.create_task(transcript_store.save_routing_decision(
        session_id=session_id,
        turn_number=userdata.advance_turn(),
        from_agent=from_agent,
        to_agent="teacher_escalation",
        question_summary=reason,
    ))

    logger.warning(
        "Escalating to teacher [from=%s, session=%s, reason=%s]",
        from_agent, session_id, reason[:100],
    )

    spoken_message = await human_escalation.escalate_to_teacher(
        session_id=session_id,
        room_name=room_name,
        reason=reason,
    )
    return spoken_message
