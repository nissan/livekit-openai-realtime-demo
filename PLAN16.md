# Plan: Fix Two Voices + Missing English Transcript (PLAN16)

## Context

PLAN15 fixed the `ConversationItemAddedEvent` unwrapping. The event-driven pipeline
close now **works** (pipeline closes at ~18s, not the 30s fallback). But two problems
persist:

1. **Two voices**: English agent speaks at ~3-4s; pipeline isn't silent until ~18s → 14s overlap.
2. **Missing transcript**: No English turns appear — `conversation_item_added` fires but with empty `text_content`.

---

## Root Causes (Confirmed from Docker Logs + SDK Source)

### Bug A — Two Voices: Pipeline TTS Takes 13s to Commit

Timeline from logs:
- `13:06:57.907` dispatch
- `13:07:01` English agent calls `generate_reply` (3s delay after joining)
- `13:07:01` English starts speaking (~4s total from dispatch)
- `13:07:16` pipeline finally closes (18s after dispatch)
- **14 seconds of both agents speaking simultaneously**

Why 18s? The orchestrator LLM generates a full response before the tool call
(streaming text + TTS for "Let me connect you with our English tutor right away!").
The `conversation_item_added` only fires AFTER all TTS audio has been committed
(~13s of TTS). Then `_do_close_pipeline()` adds another 5s drain → 18s total.

The PLAN15 event-driven fix correctly identifies role="assistant" on the event,
but the event arrives **too late** (13s after dispatch) relative to when English
starts speaking (3s after dispatch).

**Fix**: Call `pipeline_session.interrupt()` immediately after dispatch to stop the
ongoing TTS, then use a 2s fixed timer to close. English starts at ~4s → no overlap.

---

### Bug B — Missing Transcript: `forwarded_text` Is Empty + Wrong Subscription Path

SDK source (`agent_activity.py`, `_realtime_generation_task_impl`):
```python
if msg_gen and forwarded_text:    # <-- skipped entirely if forwarded_text == ""
    msg = _create_assistant_message(message_id, forwarded_text, interrupted)
    self._session._conversation_item_added(msg)
```

`forwarded_text = text_out.text if text_out else ""`

For Realtime model: `text_out.text` is populated from `response.output_audio_transcript.delta`
events (confirmed from SDK: `realtime_model.py:933` handles this event type) OR
`response.output_text.delta` for text modality. Both write to `text_ch` → `text_stream`.

Evidence: English agent logs show "ignoring text stream with topic 'lk.transcription'"
at t=14s — this IS the English agent's audio transcription published via the
transcription node pipeline to the LiveKit room. The agent SPEAKS and its audio IS
transcribed. But `forwarded_text = ""` → `_conversation_item_added` is never called →
handler never fires → no `publish_data(topic="transcript")` → nothing in the panel.

Root cause (confirmed by SDK): `lk.transcription` IS published to the room by the English
agent's transcription node pipeline. This is a SEPARATE path from `conversation_item_added`.
The `lk.transcription` text stream flows through the room to ALL OTHER participants —
including the student's browser frontend.

**Key insight**: The LOCAL participant (English agent) cannot receive its own `lk.transcription`
stream (no loopback in LiveKit). So registering a handler in the English agent is WRONG.

**Correct Fix**: Register `room.registerTextStreamHandler("lk.transcription", ...)` in the
**FRONTEND** (`useTranscript.ts`). The browser IS a remote participant that receives the
English agent's `lk.transcription` text stream. The LiveKit JS SDK's `Room` class has
`registerTextStreamHandler(topic, callback)` with a `TextStreamReader` that supports
`readAll()` returning the complete turn text when the stream closes.

**Two-part Fix B:**
1. Add `logger.info` at the top of `_handle_conversation_item` (diagnostic only — shows if/when handler fires and with what content)
2. In `useTranscript.ts`, register `room.registerTextStreamHandler("lk.transcription", ...)` to capture English agent turns from the text stream path

---

## Files Modified

| File | Change |
|------|--------|
| `agent/tools/routing.py` | Fix A: replace event-driven close with `interrupt()` + 2s timer |
| `agent/agents/english_agent.py` | Fix B1: add diagnostic `logger.info` at top of `_handle_conversation_item` |
| `frontend/hooks/useTranscript.ts` | Fix B2: add `room.registerTextStreamHandler("lk.transcription", ...)` |

---

## Detailed Changes Implemented

### Fix A — `agent/tools/routing.py`

Replaced the PLAN15 event-driven close with:
1. `pipeline_session.interrupt()` — stops TTS immediately after dispatch
2. `asyncio.create_task(_do_close_pipeline())` — closes at 2s (before English speaks at ~4s)
3. 30s fallback retained as safety net
4. Removed `conversation_item_added` event listener entirely

### Fix B1 — `agent/agents/english_agent.py`

Added diagnostic `logger.info` at the top of `_handle_conversation_item`:
```python
logger.info(
    "English conversation_item_added: role=%s text_content=%r",
    getattr(item, "role", None), getattr(item, "text_content", None)
)
```

### Fix B2 — `frontend/hooks/useTranscript.ts`

Added `useEffect` registering `room.registerTextStreamHandler("lk.transcription", ...)`.
`TextStreamHandler` type imported from `livekit-client`.
Handler calls `reader.readAll()` and appends the complete turn to the transcript list.

---

## Risk: Duplicate Transcript Messages

If `conversation_item_added` path is fixed in a future SDK update AND `lk.transcription`
also fires, we'd get duplicate English transcript entries in the UI.

**Mitigation**: Accept potential duplicates for now — a duplicate entry is far better
than no transcript at all. Added `// NOTE: potential duplicate` comment in code.

---

## Verification

```bash
# 1. Tests still passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild agents + frontend
docker compose up -d --build agent agent-english frontend

# 3. Check English agent log — diagnostic logging should show handler firing:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "5m" | grep "English conversation_item_added"
# Example: "English conversation_item_added: role=assistant text_content=None"
# (confirms handler fires but text_content empty → explains broken conversation_item_added path)

# 4. Check pipeline agent — should close at ~2s after English dispatch:
docker logs livekit-openai-realtime-demo-agent-1 --since "5m" | grep -E "(Pipeline session closed|Dispatched)"
# Expected: pipeline closes ~2-3s after "Dispatched learning-english" (not 18s)

# 5. End-to-end test:
#    - Ask "what is an adjective?"
#    - ONE voice responds (English tutor only)    ← Fix A (no 14s overlap)
#    - Transcript shows English tutor turns       ← Fix B2 (lk.transcription path)
#    - Pipeline closes ~2-3s after dispatch       ← Fix A
```

---

## Key Files

- `agent/tools/routing.py` — `_route_to_english_impl` (lines 134–236)
- `agent/agents/english_agent.py` — `create_english_realtime_session` (lines 159–279)
- `frontend/hooks/useTranscript.ts` — data channel + text stream transcript hook
