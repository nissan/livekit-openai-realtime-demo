"""
MathAgent — Claude Sonnet 4.6 pipeline agent for mathematics tutoring.

Data flow:
  Student speaks → STT → Claude Sonnet (text) → [tts_node GUARDRAIL] → TTS → audio

Inherits GuardedAgent so tts_node guardrail is fully active.
Expected latency: ~900–1200ms (Claude Sonnet reasoning) + ~50–200ms guardrail/sentence
"""
from __future__ import annotations

import logging

from livekit.agents import function_tool, llm, RunContext
from livekit.plugins import anthropic

from agent.agents.base import GuardedAgent

logger = logging.getLogger(__name__)

MATH_SYSTEM_PROMPT = """You are an expert mathematics tutor for students aged 8–16.

Your role:
- Explain mathematical concepts step by step, clearly and patiently
- Use concrete examples and visual descriptions where helpful
- Never just give the answer — guide the student to understand the solution
- Use encouraging, supportive language
- Adapt your language complexity to match the student's apparent age/level
- For complex problems, break them into smaller manageable steps

Topics you cover: arithmetic, algebra, geometry, statistics, calculus basics,
number theory, and problem-solving strategies.

Always verify your calculations before responding. If you make an error, acknowledge
it clearly and correct it.

If asked about history, English, or anything outside mathematics,
route immediately to the appropriate specialist — do not attempt to answer.
"""


class MathAgent(GuardedAgent):
    """
    Mathematics specialist agent.
    Overrides the session LLM with Claude Sonnet 4.6 at low temperature
    for precise step-by-step mathematical reasoning.
    """
    agent_name = "math"

    def __init__(self, chat_ctx: llm.ChatContext | None = None):
        super().__init__(
            instructions=MATH_SYSTEM_PROMPT,
            llm=anthropic.LLM(
                model="claude-sonnet-4-6",
                temperature=0.3,  # low temp for precise maths
            ),
            chat_ctx=chat_ctx,
        )
        logger.info("MathAgent initialised (claude-sonnet-4-6, temp=0.3)")

    @function_tool(description="Route the student to the history specialist")
    async def route_to_history(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        from agent.tools.routing import _route_to_history_impl
        return await _route_to_history_impl(self, context, question_summary)

    @function_tool(description="Route the student to the English language and literature specialist")
    async def route_to_english(
        self,
        context: RunContext,
        question_summary: str,
    ) -> tuple:
        from agent.tools.routing import _route_to_english_impl
        return await _route_to_english_impl(self, context, question_summary)

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
