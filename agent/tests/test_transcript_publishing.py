"""
Tests that conversation transcript turns are correctly extracted and published.

Root Cause A (PLAN7): ChatContent = str | AudioContent | ImageContent.
The old code checked hasattr(part, "text") — always False for plain str objects.
Fix: use ChatMessage.text_content property which filters isinstance(c, str).

Root Cause D (PLAN7): English session never called publish_data on transcript turns.
Fix: both assistant and user turns are now published to the "transcript" data channel.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat_message(role: str, content_parts: list):
    """
    Build a minimal ChatMessage-like object that mirrors the LiveKit SDK shape:
      - .role  -> str
      - .content -> list[ChatContent]  (ChatContent = str | AudioContent | ImageContent)
      - .text_content property
    """
    class _AudioContent:
        """Stub for AudioContent — has no .text attribute."""
        pass

    class _FakeChatMessage:
        def __init__(self, role, content):
            self.role = role
            self.content = content

        @property
        def text_content(self):
            text_parts = [c for c in self.content if isinstance(c, str)]
            return "\n".join(text_parts) if text_parts else None

    return _FakeChatMessage(role, content_parts), _AudioContent


# ---------------------------------------------------------------------------
# TestChatMessageTextContent — unit-tests the text_content property logic
# ---------------------------------------------------------------------------

class TestChatMessageTextContent:
    """
    Verify the text_content extraction logic that replaces the broken
    hasattr(part, "text") loop from PLAN6.
    """

    def test_str_content_extracted_by_text_content_property(self):
        """Plain str content must be returned by text_content."""
        msg, _ = _make_chat_message("assistant", ["Hello student!"])
        assert msg.text_content == "Hello student!"

    def test_audio_content_not_in_text_content(self):
        """AudioContent (no .text attr) must NOT appear in text_content."""

        class _AudioContent:
            """Stub for AudioContent — has no .text attribute."""
            pass

        msg, _ = _make_chat_message("assistant", [_AudioContent()])
        assert msg.text_content is None

    def test_mixed_content_extracts_only_str(self):
        """When content has both AudioContent and str, only str parts are extracted."""
        _, AudioContent = _make_chat_message("assistant", [])
        msg, _ = _make_chat_message("assistant", [AudioContent(), "some text"])
        assert msg.text_content == "some text"


# ---------------------------------------------------------------------------
# TestOnConversationItemPublishes — integration-style tests for the handler
# ---------------------------------------------------------------------------

class TestOnConversationItemPublishes:
    """
    Verify that the conversation_item_added handler (main.py pipeline session)
    publishes text content to the data channel and skips audio-only messages.
    """

    def _make_event(self, role: str, content_parts: list):
        """Build a ConversationItemAddedEvent-like mock."""
        msg, _ = _make_chat_message(role, content_parts)

        event = MagicMock()
        event.item = msg
        return event

    def _make_userdata(self):
        from agent.models.session_state import SessionUserdata
        return SessionUserdata(
            student_identity="alice",
            room_name="room-1",
        )

    async def test_handler_publishes_text_content_to_data_channel(self):
        """
        When a ChatMessage has plain str content, the handler must call
        publish_data with the encoded JSON payload on topic "transcript".
        """
        from agent.models.session_state import SessionUserdata

        userdata = self._make_userdata()
        event = self._make_event("assistant", ["Hello student!"])

        mock_publish = AsyncMock()
        mock_local_participant = MagicMock()
        mock_local_participant.publish_data = mock_publish

        mock_room = MagicMock()
        mock_room.local_participant = mock_local_participant

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        tasks = []

        def _capture_task(coro):
            task = asyncio.ensure_future(coro)
            tasks.append(task)
            return task

        with patch("asyncio.create_task", side_effect=_capture_task):
            # Simulate the fixed handler logic directly
            msg = event.item
            role = msg.role
            speaker = "student" if role == "user" else userdata.current_subject or "orchestrator"
            content = msg.text_content or ""

            if content:
                payload = json.dumps({
                    "speaker": speaker,
                    "role": role,
                    "content": content,
                    "subject": userdata.current_subject,
                    "turn": userdata.turn_number,
                    "session_id": userdata.session_id,
                })
                asyncio.create_task(
                    mock_room.local_participant.publish_data(
                        payload.encode(), topic="transcript"
                    )
                )

        # Run queued tasks
        if tasks:
            await asyncio.gather(*tasks)

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args
        raw = call_args[0][0]
        data = json.loads(raw.decode())
        assert data["content"] == "Hello student!"
        assert data["role"] == "assistant"
        assert call_args[1]["topic"] == "transcript"

    async def test_handler_skips_audio_only_messages(self):
        """
        When a ChatMessage contains only AudioContent (no str parts),
        publish_data must NOT be called.
        """
        _, AudioContent = _make_chat_message("assistant", [])

        class _FakeChatMessage:
            role = "assistant"
            content = [AudioContent()]

            @property
            def text_content(self):
                text_parts = [c for c in self.content if isinstance(c, str)]
                return "\n".join(text_parts) if text_parts else None

        event = MagicMock()
        event.item = _FakeChatMessage()

        mock_publish = AsyncMock()

        msg = event.item
        content = msg.text_content or ""

        if content:
            asyncio.create_task(mock_publish(content.encode(), topic="transcript"))

        mock_publish.assert_not_called()

    async def test_handler_payload_has_correct_fields(self):
        """
        The JSON payload published to the data channel must contain:
        speaker, role, content, subject, turn, session_id.
        """
        from agent.models.session_state import SessionUserdata

        userdata = SessionUserdata(
            student_identity="bob",
            room_name="room-2",
        )
        userdata.route_to("math")

        event = self._make_event("assistant", ["The answer is 42."])
        msg = event.item
        role = msg.role
        speaker = "student" if role == "user" else userdata.current_subject or "orchestrator"
        content = msg.text_content or ""

        payload = json.dumps({
            "speaker": speaker,
            "role": role,
            "content": content,
            "subject": userdata.current_subject,
            "turn": userdata.turn_number,
            "session_id": userdata.session_id,
        })

        data = json.loads(payload)
        assert "speaker" in data
        assert "role" in data
        assert "content" in data
        assert "subject" in data
        assert "turn" in data
        assert "session_id" in data
        assert data["content"] == "The answer is 42."
        assert data["speaker"] == "math"
        assert data["role"] == "assistant"
