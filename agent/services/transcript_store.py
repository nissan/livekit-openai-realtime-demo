"""
Supabase async transcript storage.
Uses SUPABASE_SERVICE_KEY — bypasses RLS for agent writes.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from supabase import acreate_client, AsyncClient

logger = logging.getLogger(__name__)

_client: Optional[AsyncClient] = None


async def get_client() -> AsyncClient:
    """Lazy-initialise and return the Supabase async client."""
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]
        _client = await acreate_client(url, key)
    return _client


async def create_session_record(
    session_id: str,
    room_name: str,
    student_identity: str,
) -> None:
    """Insert a new learning_sessions row at session start."""
    try:
        client = await get_client()
        await client.table("learning_sessions").insert({
            "session_id": session_id,
            "room_name": room_name,
            "student_identity": student_identity,
        }).execute()
        logger.info("Session record created: %s", session_id)
    except Exception:
        logger.exception("Failed to create session record for %s", session_id)


async def close_session_record(
    session_id: str,
    session_report: dict,
) -> None:
    """Update learning_sessions with ended_at + session_report JSONB."""
    try:
        client = await get_client()
        from datetime import datetime, timezone
        await client.table("learning_sessions").update({
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "session_report": session_report,
        }).eq("session_id", session_id).execute()
        logger.info("Session record closed: %s", session_id)
    except Exception:
        logger.exception("Failed to close session record for %s", session_id)


async def save_transcript_turn(
    session_id: str,
    turn_number: int,
    speaker: str,
    role: str,
    content: str,
    subject_area: Optional[str] = None,
) -> None:
    """
    Insert one transcript turn.
    speaker: "student" | "orchestrator" | "math" | "english" | "history" | "teacher"
    role: "user" | "assistant"
    """
    try:
        client = await get_client()
        await client.table("transcript_turns").insert({
            "session_id": session_id,
            "turn_number": turn_number,
            "speaker": speaker,
            "role": role,
            "content": content,
            "subject_area": subject_area,
        }).execute()
    except Exception:
        logger.exception(
            "Failed to save transcript turn %d for session %s",
            turn_number, session_id
        )


async def save_routing_decision(
    session_id: str,
    turn_number: int,
    from_agent: str,
    to_agent: str,
    question_summary: str,
    confidence: Optional[float] = None,
) -> None:
    """Record an agent handoff decision."""
    try:
        client = await get_client()
        await client.table("routing_decisions").insert({
            "session_id": session_id,
            "turn_number": turn_number,
            "from_agent": from_agent,
            "to_agent": to_agent,
            "question_summary": question_summary,
            "confidence": confidence,
        }).execute()
    except Exception:
        logger.exception(
            "Failed to save routing decision for session %s", session_id
        )
