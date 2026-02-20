"""
Unit tests for GuardedAgent.tts_node sentence buffering + guardrail invocation.

No LiveKit infrastructure required — GuardedAgent is instantiated via object.__new__
with attributes injected directly, bypassing the LiveKit Agent.__init__.

All guardrail and TTS calls are mocked.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


async def _run_tts_node(text_chunks, rewrite_fn=None):
    """
    Helper: run GuardedAgent.tts_node with mocked guardrail and default TTS.

    Returns:
        calls: list of text strings passed to check_and_rewrite
        received_by_tts: list of text chunks the default TTS generator received
        frames: list of audio frames yielded by tts_node
    """
    from agent.agents.base import GuardedAgent
    import agent.services.guardrail as gs

    # Bypass LiveKit Agent.__init__ — we only need the tts_node method.
    # `session` is a read-only property on Agent with no setter, so we don't
    # set it here. tts_node handles AttributeError gracefully (falls back to
    # session_id="unknown"), and check_and_rewrite is fully mocked anyway.
    agent_instance = object.__new__(GuardedAgent)
    agent_instance.agent_name = "test-agent"

    async def text_gen():
        for chunk in text_chunks:
            yield chunk

    calls = []

    async def fake_check_and_rewrite(text, session_id, agent_name):
        calls.append(text)
        return rewrite_fn(text) if rewrite_fn else text

    received_by_tts = []
    dummy_frame = MagicMock()

    async def fake_default_tts(agent_self, text_stream, settings):
        async for chunk in text_stream:
            received_by_tts.append(chunk)
        yield dummy_frame

    with patch.object(gs, "check_and_rewrite", side_effect=fake_check_and_rewrite):
        with patch("livekit.agents.Agent.default") as mock_default:
            mock_default.tts_node = fake_default_tts
            frames = [
                f async for f in agent_instance.tts_node(text_gen(), MagicMock())
            ]

    return calls, received_by_tts, frames


class TestGuardedAgentTtsNode:
    async def test_complete_sentence_triggers_one_guardrail_call(self):
        """A sentence completed with '?' fires exactly one guardrail call."""
        calls, received_by_tts, frames = await _run_tts_node(
            ["What is", " the answer?"]
        )

        assert len(calls) == 1, f"Expected 1 guardrail call, got {len(calls)}: {calls}"
        assert calls[0] == "What is the answer?", (
            f"Expected full sentence, got {calls[0]!r}"
        )
        assert len(frames) == 1, "Expected exactly one audio frame from fake TTS"

    async def test_two_sentences_trigger_two_guardrail_calls(self):
        """Two complete sentences fire two separate guardrail calls."""
        calls, received_by_tts, frames = await _run_tts_node(
            ["Hello. ", "World!"]
        )

        assert len(calls) == 2, f"Expected 2 guardrail calls, got {len(calls)}: {calls}"
        assert calls[0].rstrip().endswith("."), (
            f"First call should end with '.', got {calls[0]!r}"
        )
        assert "World!" in calls[1], (
            f"Second call should contain 'World!', got {calls[1]!r}"
        )

    async def test_partial_sentence_flushed_at_stream_end(self):
        """Text without sentence-ending punctuation is flushed when the stream closes."""
        calls, received_by_tts, frames = await _run_tts_node(
            ["No punctuation here"]
        )

        assert len(calls) == 1, (
            f"Expected 1 guardrail call (flush), got {len(calls)}: {calls}"
        )
        assert calls[0] == "No punctuation here", (
            f"Expected flushed text, got {calls[0]!r}"
        )

    async def test_rewritten_text_flows_to_tts(self):
        """When guardrail rewrites text, the rewritten version reaches the TTS generator."""
        calls, received_by_tts, frames = await _run_tts_node(
            ["Bad sentence."],
            rewrite_fn=lambda _: "Safe text.",
        )

        assert received_by_tts == ["Safe text."], (
            f"TTS should receive rewritten text, got {received_by_tts}"
        )
        assert len(frames) == 1, "Expected one audio frame"
