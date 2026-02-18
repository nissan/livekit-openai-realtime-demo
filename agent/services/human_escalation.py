"""
Human escalation service.

When the orchestrator lacks confidence, it calls escalate_to_teacher():
1. Generate a teacher LiveKit JWT (roomAdmin=True) for the existing room
2. Store token + reason in escalation_events (Supabase Realtime broadcasts to teacher portal)
3. Return a spoken confirmation message to the student
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

from livekit.api import AccessToken, VideoGrants

logger = logging.getLogger(__name__)


def generate_teacher_token(room_name: str, teacher_identity: str = "teacher") -> str:
    """
    Generate a pre-signed LiveKit JWT for a teacher to join an existing room.
    Token is valid for 2 hours and grants roomAdmin privileges.
    """
    api_key = os.environ["LIVEKIT_API_KEY"]
    api_secret = os.environ["LIVEKIT_API_SECRET"]

    token = AccessToken(api_key=api_key, api_secret=api_secret)
    token.identity = teacher_identity
    token.name = "Teacher"
    token.ttl = timedelta(hours=2)
    token.video = VideoGrants(
        room_join=True,
        room=room_name,
        room_admin=True,
        can_publish=True,
        can_subscribe=True,
    )
    return token.to_jwt()


async def escalate_to_teacher(
    session_id: str,
    room_name: str,
    reason: str,
) -> str:
    """
    Full escalation flow:
    1. Generate teacher JWT
    2. Write escalation_events row (triggers Supabase Realtime → teacher portal)
    3. Return spoken confirmation for the student

    Returns the spoken message to play to the student.
    """
    teacher_token = generate_teacher_token(room_name=room_name)

    try:
        from agent.services.transcript_store import get_client
        client = await get_client()
        await client.table("escalation_events").insert({
            "session_id": session_id,
            "room_name": room_name,
            "reason": reason,
            "teacher_token": teacher_token,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        }).execute()
        logger.info(
            "Escalation event created [session=%s, room=%s, reason=%s]",
            session_id, room_name, reason[:100]
        )
    except Exception:
        logger.exception(
            "Failed to store escalation event for session %s", session_id
        )

    return (
        "I'd like to get your teacher involved to help with this. "
        "I've sent a notification to your teacher — they'll be joining us shortly. "
        "Please hold on for a moment."
    )
