"""
Shared session state dataclass — passed as AgentSession userdata.
Mutated by OrchestratorAgent on routing decisions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SessionUserdata:
    """
    Shared across all agent handoffs within a single student session.
    Access via: context.session.userdata (typed as SessionUserdata)
    """
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    student_identity: str = ""
    room_name: str = ""
    current_subject: Optional[str] = None          # "math" | "english" | "history" | None
    previous_subjects: list[str] = field(default_factory=list)
    turn_number: int = 0
    escalated: bool = False
    escalation_reason: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def advance_turn(self) -> int:
        """Increment and return the current turn number."""
        self.turn_number += 1
        return self.turn_number

    def route_to(self, subject: str) -> None:
        """Record a subject routing decision."""
        if self.current_subject and self.current_subject != subject:
            self.previous_subjects.append(self.current_subject)
        self.current_subject = subject

    def to_dict(self) -> dict:
        """Serialise to dict for Supabase JSONB storage."""
        return {
            "session_id": self.session_id,
            "student_identity": self.student_identity,
            "room_name": self.room_name,
            "current_subject": self.current_subject,
            "previous_subjects": self.previous_subjects,
            "turn_number": self.turn_number,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
            "created_at": self.created_at.isoformat(),
        }
