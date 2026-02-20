"""
Integration tests — TTS and STT connectivity.

Verifies that the OpenAI TTS (gpt-4o-mini-tts) and STT (gpt-4o-transcribe) endpoints
return audio and transcriptions respectively. The round-trip test synthesises a phrase
to WAV then transcribes it to confirm the speech-to-text loop works end-to-end.

Tests skip gracefully when real API keys are absent.
Timeout: 60s per test (TTS + STT can take up to ~10s each).
"""
import io
import pytest
import openai

from tests.integration.conftest import _REAL_OPENAI_KEY


@pytest.mark.timeout(60)
class TestTTS:
    """OpenAI TTS endpoint connectivity — different voices."""

    async def test_tts_alloy_returns_audio(self):
        """gpt-4o-mini-tts with voice 'alloy' returns non-empty WAV bytes."""
        client = openai.AsyncOpenAI(api_key=_REAL_OPENAI_KEY)
        response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input="Hello, I am your tutor.",
            response_format="wav",
        )
        audio_bytes = await response.aread()
        assert len(audio_bytes) > 0, "Expected non-empty audio bytes from TTS (alloy)"

    async def test_tts_onyx_returns_audio(self):
        """gpt-4o-mini-tts with voice 'onyx' returns non-empty WAV bytes."""
        client = openai.AsyncOpenAI(api_key=_REAL_OPENAI_KEY)
        response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="onyx",
            input="The answer is forty two.",
            response_format="wav",
        )
        audio_bytes = await response.aread()
        assert len(audio_bytes) > 0, "Expected non-empty audio bytes from TTS (onyx)"

    async def test_tts_fable_returns_audio(self):
        """gpt-4o-mini-tts with voice 'fable' returns non-empty WAV bytes."""
        client = openai.AsyncOpenAI(api_key=_REAL_OPENAI_KEY)
        response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="fable",
            input="Julius Caesar was a Roman general.",
            response_format="wav",
        )
        audio_bytes = await response.aread()
        assert len(audio_bytes) > 0, "Expected non-empty audio bytes from TTS (fable)"


@pytest.mark.timeout(60)
class TestTTSToSTTRoundTrip:
    """End-to-end TTS → STT round-trip."""

    async def test_tts_to_stt_round_trip(self):
        """
        Synthesise 'The answer is forty two.' to WAV via gpt-4o-mini-tts,
        then transcribe with gpt-4o-transcribe and assert the phrase is recovered.
        """
        client = openai.AsyncOpenAI(api_key=_REAL_OPENAI_KEY)

        # Step 1: TTS
        tts_response = await client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input="The answer is forty two.",
            response_format="wav",
        )
        wav_bytes = await tts_response.aread()
        assert len(wav_bytes) > 0, "TTS returned empty audio — cannot test STT round-trip"

        # Step 2: STT
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "speech.wav"  # Required for MIME type detection

        transcription = await client.audio.transcriptions.create(
            model="gpt-4o-transcribe",
            file=audio_file,
        )
        transcript_text = transcription.text.strip().lower()

        assert "forty" in transcript_text or "42" in transcript_text, (
            f"Expected 'forty' or '42' in transcript, got: {transcript_text!r}"
        )
