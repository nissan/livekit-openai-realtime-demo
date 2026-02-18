"""
Unit tests for agent/models/session_state.py — SessionUserdata.
No mocking required; pure dataclass logic.
"""
import pytest
from agent.models.session_state import SessionUserdata


def test_initial_state():
    ud = SessionUserdata(student_identity="alice", room_name="room-1")
    assert ud.turn_number == 0
    assert ud.current_subject is None
    assert ud.previous_subjects == []
    assert ud.escalated is False
    assert ud.escalation_reason is None
    assert ud.student_identity == "alice"
    assert ud.room_name == "room-1"
    assert ud.session_id  # non-empty uuid


def test_advance_turn_increments_and_returns():
    ud = SessionUserdata()
    assert ud.advance_turn() == 1
    assert ud.advance_turn() == 2
    assert ud.advance_turn() == 3
    assert ud.turn_number == 3


def test_route_to_sets_current_subject():
    ud = SessionUserdata()
    ud.route_to("math")
    assert ud.current_subject == "math"
    assert ud.previous_subjects == []


def test_route_to_appends_previous_on_change():
    ud = SessionUserdata()
    ud.route_to("math")
    ud.route_to("history")
    assert ud.current_subject == "history"
    assert "math" in ud.previous_subjects


def test_route_to_same_subject_does_not_duplicate():
    ud = SessionUserdata()
    ud.route_to("math")
    ud.route_to("math")  # same subject again
    assert ud.current_subject == "math"
    assert ud.previous_subjects == []  # no duplicate appended


def test_route_to_tracks_full_history():
    ud = SessionUserdata()
    ud.route_to("math")
    ud.route_to("english")
    ud.route_to("history")
    assert ud.current_subject == "history"
    assert ud.previous_subjects == ["math", "english"]


def test_to_dict_contains_all_fields():
    ud = SessionUserdata(student_identity="bob", room_name="room-42")
    d = ud.to_dict()
    assert "session_id" in d
    assert d["student_identity"] == "bob"
    assert d["room_name"] == "room-42"
    assert "current_subject" in d
    assert "previous_subjects" in d
    assert "turn_number" in d
    assert "escalated" in d
    assert "escalation_reason" in d
    assert "created_at" in d


def test_to_dict_created_at_is_iso_string():
    ud = SessionUserdata()
    d = ud.to_dict()
    created_at = d["created_at"]
    assert isinstance(created_at, str)
    # Should be parseable as ISO 8601
    from datetime import datetime
    parsed = datetime.fromisoformat(created_at)
    assert parsed is not None


def test_session_id_is_unique():
    ud1 = SessionUserdata()
    ud2 = SessionUserdata()
    assert ud1.session_id != ud2.session_id
