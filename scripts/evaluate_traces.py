#!/usr/bin/env python3
"""
Langfuse Trace Evaluation Script — PLAN17 Proposal B.

Queries recent traces from Langfuse, uses an LLM judge (Claude Sonnet)
to score agent behaviour, and writes scores back to Langfuse for dashboard
visibility.

Evaluation rubrics:
  routing_correctness   — did the agent route to the correct specialist?
  transcript_complete   — did all turns have non-empty text_content?
  guardrail_triggered   — was a safety guardrail event raised?
  session_coherent      — does the full conversation make educational sense?

Usage:
  # Against local Langfuse (Docker Compose stack)
  PYTHONPATH=$(pwd) uv run --directory agent python scripts/evaluate_traces.py

  # Against a specific Langfuse host with custom keys
  LANGFUSE_HOST=http://localhost:3001 \\
  LANGFUSE_PUBLIC_KEY=pk-lf-dev \\
  LANGFUSE_SECRET_KEY=sk-lf-dev \\
  ANTHROPIC_API_KEY=... \\
  PYTHONPATH=$(pwd) uv run --directory agent python scripts/evaluate_traces.py

Requirements:
  pip install langfuse anthropic

Note: This script requires real session traces to exist in Langfuse.
It is NOT a blocking CI gate — run nightly after live sessions have been collected.
Estimated cost: ~$0.01-0.05 per session evaluated (Claude Sonnet pricing).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Evaluation result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EvaluationResult:
    trace_id: str
    session_id: str
    scores: dict[str, float] = field(default_factory=dict)
    comments: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Routing correctness rubric
# ---------------------------------------------------------------------------

ROUTING_JUDGE_PROMPT = """You are evaluating an AI educational agent's routing decision.

The agent should route student questions to the correct specialist:
  - Math questions (arithmetic, algebra, geometry, calculus) → "math"
  - History questions (historical events, people, dates, geography) → "history"
  - English questions (grammar, writing, spelling, literature) → "english"
  - Questions about multiple subjects or unclear → "orchestrator" (acceptable)

Given:
  question_summary: {question_summary}
  routed_to: {to_agent}

Was this routing decision correct?

Respond with a JSON object containing:
  "score": 1.0 (correct) or 0.0 (incorrect)
  "reasoning": brief explanation (1-2 sentences)

JSON only, no preamble."""


async def judge_routing_correctness(
    client,
    question_summary: str,
    to_agent: str,
) -> tuple[float, str]:
    """Use LLM to evaluate whether a routing decision was correct."""
    prompt = ROUTING_JUDGE_PROMPT.format(
        question_summary=question_summary[:500],
        to_agent=to_agent,
    )
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # Remove markdown code block if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        return float(parsed.get("score", 0.0)), parsed.get("reasoning", "")
    except Exception as e:
        logger.warning("Routing judge failed: %s", e)
        return 0.5, f"Judge error: {e}"


# ---------------------------------------------------------------------------
# Session coherence rubric
# ---------------------------------------------------------------------------

SESSION_COHERENCE_PROMPT = """You are evaluating a tutoring conversation between a student and AI agents.

The conversation transcript (student questions and agent answers):
{transcript}

Evaluate whether this conversation is educationally coherent:
  - Agents answered questions accurately for the subject area
  - Handoffs between agents were smooth (no abrupt topic changes)
  - No inappropriate or harmful content was produced
  - The conversation made sense end-to-end

Respond with a JSON object:
  "score": float between 0.0 (incoherent/harmful) and 1.0 (perfect)
  "reasoning": 1-2 sentences

JSON only."""


async def judge_session_coherence(
    client,
    transcript_turns: list[dict],
) -> tuple[float, str]:
    """Use LLM to evaluate overall session coherence."""
    # Build a readable transcript
    lines = []
    for turn in transcript_turns[:20]:  # cap at 20 turns to avoid token limits
        role = turn.get("role", "?")
        content = turn.get("content", "")[:200]
        speaker = turn.get("speaker", role)
        lines.append(f"[{speaker}]: {content}")
    transcript_text = "\n".join(lines)

    prompt = SESSION_COHERENCE_PROMPT.format(transcript=transcript_text)
    try:
        message = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        return float(parsed.get("score", 0.5)), parsed.get("reasoning", "")
    except Exception as e:
        logger.warning("Coherence judge failed: %s", e)
        return 0.5, f"Judge error: {e}"


# ---------------------------------------------------------------------------
# Trace extraction helpers
# ---------------------------------------------------------------------------

def extract_routing_decisions(observations: list) -> list[dict]:
    """Extract routing.decision spans from Langfuse observations."""
    decisions = []
    for obs in observations:
        if getattr(obs, "name", "") == "routing.decision":
            try:
                input_data = obs.input or {}
                output_data = obs.output or {}
                metadata = obs.metadata or {}
                # Attributes are stored in metadata for OTEL spans
                decisions.append({
                    "trace_id": obs.trace_id,
                    "to_agent": metadata.get("to_agent", "unknown"),
                    "from_agent": metadata.get("from_agent", "unknown"),
                    "question_summary": metadata.get("question_summary", ""),
                    "turn_number": metadata.get("turn_number", 0),
                    "decision_ms": metadata.get("decision_ms", None),
                })
            except Exception:
                pass
    return decisions


def extract_conversation_items(observations: list) -> list[dict]:
    """Extract conversation.item spans from Langfuse observations."""
    items = []
    for obs in observations:
        if getattr(obs, "name", "") == "conversation.item":
            try:
                metadata = obs.metadata or {}
                items.append({
                    "role": metadata.get("role", "unknown"),
                    "speaker": metadata.get("speaker", "unknown"),
                    "content": str(obs.output or "")[:200],
                    "turn_number": metadata.get("turn_number", 0),
                    "e2e_response_ms": metadata.get("e2e_response_ms", None),
                    "subject_area": metadata.get("subject_area", ""),
                })
            except Exception:
                pass
    return sorted(items, key=lambda x: x.get("turn_number", 0))


def extract_escalation_events(observations: list) -> list[dict]:
    """Extract teacher.escalation spans (safety events)."""
    events = []
    for obs in observations:
        if getattr(obs, "name", "") == "teacher.escalation":
            try:
                metadata = obs.metadata or {}
                events.append({
                    "reason": metadata.get("reason", ""),
                    "from_agent": metadata.get("from_agent", ""),
                    "turn_number": metadata.get("turn_number", 0),
                })
            except Exception:
                pass
    return events


def compute_latency_stats(items: list[dict]) -> dict:
    """Compute p50/p95 of e2e_response_ms from conversation items."""
    latencies = [
        item["e2e_response_ms"]
        for item in items
        if item.get("e2e_response_ms") is not None
        and item.get("role") == "assistant"
    ]
    if not latencies:
        return {}
    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2]
    p95 = latencies[min(int(n * 0.95), n - 1)]
    return {"p50_ms": p50, "p95_ms": p95, "count": n}


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def evaluate_traces(
    langfuse_host: str,
    public_key: str,
    secret_key: str,
    limit: int = 50,
) -> list[EvaluationResult]:
    """
    Query Langfuse for recent traces and evaluate them with an LLM judge.

    Args:
        langfuse_host: Langfuse HTTP URL (e.g. http://localhost:3001)
        public_key: Langfuse public key (e.g. pk-lf-dev)
        secret_key: Langfuse secret key (e.g. sk-lf-dev)
        limit: Max number of recent traces to evaluate

    Returns:
        List of EvaluationResult, one per evaluated trace
    """
    try:
        from langfuse import Langfuse
    except ImportError:
        logger.error(
            "langfuse package not installed. Run: pip install langfuse\n"
            "Or: uv add langfuse --directory agent"
        )
        return []

    try:
        import anthropic
        llm_client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    except ImportError:
        logger.error("anthropic package not installed. Run: pip install anthropic")
        return []

    lf = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        host=langfuse_host,
    )

    results: list[EvaluationResult] = []

    try:
        logger.info("Fetching recent traces from Langfuse [host=%s, limit=%d]", langfuse_host, limit)
        traces_page = lf.get_traces(limit=limit)
        traces = traces_page.data if hasattr(traces_page, "data") else []
        logger.info("Found %d traces to evaluate", len(traces))
    except Exception as e:
        logger.error("Failed to fetch traces: %s", e)
        return []

    for trace in traces:
        trace_id = getattr(trace, "id", "unknown")
        session_id = getattr(trace, "session_id", "unknown") or "unknown"

        result = EvaluationResult(trace_id=trace_id, session_id=session_id)

        try:
            # Fetch observations (spans) for this trace
            observations = []
            try:
                trace_detail = lf.get_trace(trace_id)
                observations = getattr(trace_detail, "observations", []) or []
            except Exception as e:
                result.errors.append(f"Failed to fetch observations: {e}")
                results.append(result)
                continue

            # --- Routing correctness ---
            routing_decisions = extract_routing_decisions(observations)
            if routing_decisions:
                routing_scores = []
                for decision in routing_decisions[:5]:  # evaluate up to 5 routing decisions
                    q = decision.get("question_summary", "")
                    to = decision.get("to_agent", "unknown")
                    if q and to:
                        score, reasoning = await judge_routing_correctness(llm_client, q, to)
                        routing_scores.append(score)
                        logger.info(
                            "  Routing [to=%s, q=%.50r]: score=%.1f — %s",
                            to, q, score, reasoning,
                        )
                        # Write score to Langfuse
                        try:
                            lf.score(
                                trace_id=trace_id,
                                name="routing_correctness",
                                value=score,
                                comment=f"to={to}: {reasoning}",
                            )
                        except Exception as e:
                            result.errors.append(f"Failed to write routing score: {e}")

                if routing_scores:
                    result.scores["routing_correctness"] = sum(routing_scores) / len(routing_scores)

            # --- Transcript completeness ---
            conv_items = extract_conversation_items(observations)
            if conv_items:
                # Check what fraction of items have non-empty content
                non_empty = sum(1 for item in conv_items if item.get("content", "").strip())
                completeness = non_empty / len(conv_items) if conv_items else 1.0
                result.scores["transcript_completeness"] = completeness
                try:
                    lf.score(
                        trace_id=trace_id,
                        name="transcript_completeness",
                        value=completeness,
                        comment=f"{non_empty}/{len(conv_items)} turns have content",
                    )
                except Exception as e:
                    result.errors.append(f"Failed to write completeness score: {e}")

            # --- Guardrail trigger ---
            escalation_events = extract_escalation_events(observations)
            guardrail_triggered = 1.0 if escalation_events else 0.0
            result.scores["safety_escalation"] = guardrail_triggered
            if escalation_events:
                reasons = [e.get("reason", "")[:100] for e in escalation_events]
                logger.warning("  Safety escalation detected: %s", reasons)
                try:
                    lf.score(
                        trace_id=trace_id,
                        name="safety_escalation",
                        value=1.0,
                        comment=f"Escalation reasons: {'; '.join(reasons)}",
                    )
                except Exception as e:
                    result.errors.append(f"Failed to write escalation score: {e}")

            # --- Latency stats ---
            latency_stats = compute_latency_stats(conv_items)
            if latency_stats:
                result.scores["e2e_p50_ms"] = latency_stats.get("p50_ms", 0)
                result.scores["e2e_p95_ms"] = latency_stats.get("p95_ms", 0)
                logger.info(
                    "  Latency: p50=%dms, p95=%dms (n=%d)",
                    latency_stats.get("p50_ms", 0),
                    latency_stats.get("p95_ms", 0),
                    latency_stats.get("count", 0),
                )
                try:
                    lf.score(
                        trace_id=trace_id,
                        name="e2e_latency_p50_ms",
                        value=latency_stats.get("p50_ms", 0),
                        comment=f"n={latency_stats.get('count', 0)} turns",
                    )
                    lf.score(
                        trace_id=trace_id,
                        name="e2e_latency_p95_ms",
                        value=latency_stats.get("p95_ms", 0),
                        comment=f"n={latency_stats.get('count', 0)} turns",
                    )
                except Exception as e:
                    result.errors.append(f"Failed to write latency scores: {e}")

            # --- Session coherence (LLM judge) ---
            if conv_items:
                score, reasoning = await judge_session_coherence(llm_client, conv_items)
                result.scores["session_coherence"] = score
                result.comments["session_coherence"] = reasoning
                logger.info("  Coherence: score=%.2f — %s", score, reasoning)
                try:
                    lf.score(
                        trace_id=trace_id,
                        name="session_coherence",
                        value=score,
                        comment=reasoning,
                    )
                except Exception as e:
                    result.errors.append(f"Failed to write coherence score: {e}")

        except Exception as e:
            logger.exception("Failed to evaluate trace %s: %s", trace_id, e)
            result.errors.append(str(e))

        results.append(result)

    return results


def print_summary(results: list[EvaluationResult]) -> None:
    """Print a human-readable evaluation summary."""
    print("\n" + "=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)
    print(f"Traces evaluated: {len(results)}")

    if not results:
        print("No traces evaluated.")
        return

    # Aggregate scores
    all_scores: dict[str, list[float]] = {}
    for result in results:
        for metric, value in result.scores.items():
            all_scores.setdefault(metric, []).append(value)

    print("\nAggregate Metrics (mean across all traces):")
    for metric, values in sorted(all_scores.items()):
        mean = sum(values) / len(values) if values else 0.0
        print(f"  {metric:30s}: {mean:.3f} (n={len(values)})")

    error_count = sum(len(r.errors) for r in results)
    if error_count:
        print(f"\nErrors encountered: {error_count}")
        for result in results:
            for err in result.errors:
                print(f"  [{result.trace_id[:8]}] {err}")

    print("=" * 60)


async def main() -> None:
    langfuse_host = os.environ.get("LANGFUSE_HOST", "http://localhost:3001")
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "pk-lf-dev")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "sk-lf-dev")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error(
            "ANTHROPIC_API_KEY not set. The LLM judge requires it.\n"
            "Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
        )
        sys.exit(1)

    limit = int(os.environ.get("EVAL_TRACE_LIMIT", "50"))

    logger.info("Starting trace evaluation [host=%s, limit=%d]", langfuse_host, limit)
    results = await evaluate_traces(
        langfuse_host=langfuse_host,
        public_key=public_key,
        secret_key=secret_key,
        limit=limit,
    )

    print_summary(results)

    # Exit with error code if too many failures
    error_traces = [r for r in results if r.errors]
    if len(error_traces) > len(results) * 0.5 and results:
        logger.error("More than 50%% of traces had evaluation errors — check Langfuse connectivity")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
