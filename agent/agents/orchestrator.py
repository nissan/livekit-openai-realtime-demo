"""
OrchestratorAgent — Claude Haiku routing agent.

Routes student questions to the appropriate subject specialist:
  - route_to_english   → EnglishAgent (OpenAI Realtime, separate session)
  - route_to_math      → MathAgent (Claude Sonnet 4.6)
  - route_to_history   → HistoryAgent (GPT-5.2)
  - escalate_to_teacher → human teacher joins the live room

Inherits GuardedAgent so orchestrator responses (greetings, transitions)
are also safety-checked via tts_node.

Routing logic is shared with specialist agents via agent/tools/routing.py
so that any agent can hand off to any other agent.

See PLAN.md: Orchestrator → Routing
"""
from __future__ import annotations

import logging

from livekit.agents import function_tool, llm, RunContext
from livekit.plugins import anthropic

from agent.agents.base import GuardedAgent

logger = logging.getLogger(__name__)

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
        from agent.tools.routing import _route_to_english_impl
        return await _route_to_english_impl(self, context, question_summary)

    @function_tool(description="Route the student to the mathematics specialist")
    async def route_to_math(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        from agent.tools.routing import _route_to_math_impl
        return await _route_to_math_impl(self, context, question_summary)

    @function_tool(description="Route the student to the history specialist")
    async def route_to_history(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        from agent.tools.routing import _route_to_history_impl
        return await _route_to_history_impl(self, context, question_summary)

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
