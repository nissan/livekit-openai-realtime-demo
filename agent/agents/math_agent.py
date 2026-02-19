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
from livekit.plugins import anthropic, openai

from agent.agents.base import GuardedAgent

logger = logging.getLogger(__name__)

MATH_TTS_VOICE = "onyx"

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

When you have fully answered the student's question (including any immediate
follow-up clarifications on the same mathematics topic), call
route_back_to_orchestrator to return control to the main tutor.

If the student asks about history, English, or ANYTHING outside mathematics:
do NOT explain or describe the off-topic topic at all.
Say exactly one brief sentence like 'That sounds like an English question — let me pass you to the right tutor!'
then IMMEDIATELY call route_back_to_orchestrator.
Do not provide any information about the off-topic subject.
"""


class MathAgent(GuardedAgent):
    """
    Mathematics specialist agent.
    Overrides the session LLM with Claude Sonnet 4.6 at low temperature
    for precise step-by-step mathematical reasoning.
    """
    agent_name = "math"
    tts_voice = MATH_TTS_VOICE

    def __init__(self, chat_ctx: llm.ChatContext | None = None):
        super().__init__(
            instructions=MATH_SYSTEM_PROMPT,
            llm=anthropic.LLM(
                model="claude-sonnet-4-6",
                temperature=0.3,  # low temp for precise maths
            ),
            tts=openai.TTS(model="gpt-4o-mini-tts", voice=MATH_TTS_VOICE),
            chat_ctx=chat_ctx,
        )
        logger.info("MathAgent initialised (claude-sonnet-4-6, temp=0.3)")

    @function_tool(
        description=(
            "Return control to the main tutor after fully answering the student's "
            "mathematics question, including any immediate follow-up clarifications. "
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
