"""
OrchestratorAgent — Claude Haiku routing agent.

Routes student questions to the appropriate subject specialist:
  - route_to_english   → EnglishAgent (OpenAI Realtime, separate session)
  - route_to_math      → MathAgent (Claude Sonnet 3.5)
  - route_to_history   → HistoryAgent (GPT-5.2)
  - escalate_to_teacher → human teacher joins the live room

Inherits GuardedAgent so orchestrator responses (greetings, transitions)
are also safety-checked via tts_node.

See PLAN.md: Orchestrator → Routing
"""
from __future__ import annotations

import logging
import os

from livekit.agents import function_tool, llm, RunContext
from livekit.plugins import anthropic

from agent.agents.base import GuardedAgent
from agent.agents.math_agent import MathAgent
from agent.agents.history_agent import HistoryAgent
from agent.services import transcript_store, human_escalation
from agent.services.langfuse_setup import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer("orchestrator")

ORCHESTRATOR_SYSTEM_PROMPT = """You are a friendly and encouraging educational assistant
for students aged 8–16. Your job is to:

1. Welcome the student warmly and ask how you can help them today
2. Listen carefully to their question or topic
3. Route them to the appropriate subject specialist:
   - English language, literature, grammar, writing, reading → route_to_english
   - Mathematics, arithmetic, algebra, geometry, statistics → route_to_math
   - History, historical events, civilisations, geography (historical) → route_to_history

4. If the student's question is unclear, ask a clarifying question before routing

5. If you are unsure how to help, or if the student seems distressed or asks about
   something inappropriate for a school setting, escalate to a teacher immediately

Keep your routing responses brief — a simple "Let me connect you with our {subject} tutor!"
before calling the routing function. The specialist will handle the detailed teaching.

Always be warm, encouraging, and age-appropriate in your language.
"""


class OrchestratorAgent(GuardedAgent):
    """
    Routing orchestrator using Claude Haiku for fast classification.
    Does NOT do subject teaching — routes to specialists.
    """
    agent_name = "orchestrator"

    def __init__(self, chat_ctx: llm.ChatContext | None = None):
        super().__init__(
            instructions=ORCHESTRATOR_SYSTEM_PROMPT,
            llm=anthropic.LLM(
                model="claude-haiku-4-5-20251001",
                temperature=0.1,  # very low temp for consistent routing
            ),
            chat_ctx=chat_ctx,
        )
        logger.info("OrchestratorAgent initialised (claude-haiku-4-5-20251001)")

    @function_tool(description="Route the student to the English language and literature specialist")
    async def route_to_english(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        """
        Dispatch the English Realtime agent to this room.
        The pipeline session goes silent while the Realtime session handles the conversation.

        Returns a spoken handoff announcement + dispatches the English worker.
        """
        userdata = context.session.userdata
        session_id = userdata.session_id
        room_name = userdata.room_name
        previous_subject = userdata.current_subject or ""
        turn_number = userdata.advance_turn()
        userdata.route_to("english")

        with tracer.start_as_current_span("routing.decision") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("from_agent", "orchestrator")
            span.set_attribute("to_agent", "english")
            span.set_attribute("turn_number", turn_number)
            span.set_attribute("question_summary", question_summary)
            span.set_attribute("previous_subject", previous_subject)
            span.set_attribute("langfuse.session_id", session_id)
            span.set_attribute("langfuse.user_id", userdata.student_identity)

        # Log routing decision to Supabase
        import asyncio
        asyncio.create_task(transcript_store.save_routing_decision(
            session_id=session_id,
            turn_number=turn_number,
            from_agent="orchestrator",
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
            # Fallback: return EnglishAgent in pipeline mode (no Realtime)
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
                FallbackEnglishAgent(chat_ctx=context.session.chat_ctx),
                "Let me connect you with our English tutor!"
            )

        # Signal this pipeline session to go quiet while Realtime session handles it
        # The return string is spoken, then the orchestrator agent goes idle
        return "Let me connect you with our English tutor right away!"

    @function_tool(description="Route the student to the mathematics specialist")
    async def route_to_math(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        """
        Hand off to MathAgent (Claude Sonnet 3.5) within the same pipeline session.
        Returns tuple[Agent, str] as per LiveKit Agents v1.4 handoff pattern.
        """
        userdata = context.session.userdata
        session_id = userdata.session_id
        previous_subject = userdata.current_subject or ""
        turn_number = userdata.advance_turn()
        userdata.route_to("math")

        with tracer.start_as_current_span("routing.decision") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("from_agent", "orchestrator")
            span.set_attribute("to_agent", "math")
            span.set_attribute("turn_number", turn_number)
            span.set_attribute("question_summary", question_summary)
            span.set_attribute("previous_subject", previous_subject)
            span.set_attribute("langfuse.session_id", session_id)
            span.set_attribute("langfuse.user_id", userdata.student_identity)

        import asyncio
        asyncio.create_task(transcript_store.save_routing_decision(
            session_id=session_id,
            turn_number=turn_number,
            from_agent="orchestrator",
            to_agent="math",
            question_summary=question_summary,
        ))

        logger.info("Routing to MathAgent [session=%s]", session_id)
        return (
            MathAgent(chat_ctx=context.session.chat_ctx),
            "Let me connect you with our Mathematics tutor!"
        )

    @function_tool(description="Route the student to the history specialist")
    async def route_to_history(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        """
        Hand off to HistoryAgent (GPT-5.2) within the same pipeline session.
        Returns tuple[Agent, str] as per LiveKit Agents v1.4 handoff pattern.
        """
        userdata = context.session.userdata
        session_id = userdata.session_id
        previous_subject = userdata.current_subject or ""
        turn_number = userdata.advance_turn()
        userdata.route_to("history")

        with tracer.start_as_current_span("routing.decision") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("from_agent", "orchestrator")
            span.set_attribute("to_agent", "history")
            span.set_attribute("turn_number", turn_number)
            span.set_attribute("question_summary", question_summary)
            span.set_attribute("previous_subject", previous_subject)
            span.set_attribute("langfuse.session_id", session_id)
            span.set_attribute("langfuse.user_id", userdata.student_identity)

        import asyncio
        asyncio.create_task(transcript_store.save_routing_decision(
            session_id=session_id,
            turn_number=turn_number,
            from_agent="orchestrator",
            to_agent="history",
            question_summary=question_summary,
        ))

        logger.info("Routing to HistoryAgent [session=%s]", session_id)
        return (
            HistoryAgent(chat_ctx=context.session.chat_ctx),
            "Let me connect you with our History tutor!"
        )

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
        """
        Generate a teacher JWT, store in Supabase (triggers Realtime notification
        to teacher portal), return spoken confirmation for the student.
        """
        userdata = context.session.userdata
        session_id = userdata.session_id
        room_name = userdata.room_name
        userdata.escalated = True
        userdata.escalation_reason = reason

        import asyncio
        asyncio.create_task(transcript_store.save_routing_decision(
            session_id=session_id,
            turn_number=userdata.advance_turn(),
            from_agent="orchestrator",
            to_agent="teacher_escalation",
            question_summary=reason,
        ))

        logger.warning(
            "Escalating to teacher [session=%s, reason=%s]",
            session_id, reason[:100]
        )

        spoken_message = await human_escalation.escalate_to_teacher(
            session_id=session_id,
            room_name=room_name,
            reason=reason,
        )
        return spoken_message
