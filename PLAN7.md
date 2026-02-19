# Plan: Fix Transcript Display + English Stability + Langfuse OTEL (PLAN7)

## Context

Live testing after PLAN6 revealed three new issues:

1. **"Conversation will appear here" box never updates** — transcripts never appear for any
   agent, even when the agent is clearly responding (audio plays, routing works).
2. **English session "stuck on Listening"** — after routing to English, the Realtime session
   never speaks first; student has to re-prompt.
3. **Langfuse OTEL "Connection refused"** — traces fail to export throughout the session.

---

## Root Cause Analysis

### Root Cause A — `ChatContent` is `str`, not an object with `.text` (CRITICAL)

Inspected via Docker:
```python
from livekit.agents.llm import ChatContent
# ChatContent = ImageContent | AudioContent | str
```

`ChatMessage.content` is `list[ChatContent]` where text parts are **plain `str` objects**.

The current `on_conversation_item` handler in `main.py` (and English agent) does:
```python
for part in msg.content:
    if hasattr(part, "text") and part.text:  # ← ALWAYS False for str!
        content += part.text
```

`str` in Python does NOT have a `.text` attribute. So `content` is always `""`, the
`if content:` guard is always False, and **`publish_data` is never called**. The data
channel is permanently silent.

`ChatMessage` has a built-in `text_content` property that handles this correctly:
```python
@property
def text_content(self) -> str | None:
    text_parts = [c for c in self.content if isinstance(c, str)]
    return "\n".join(text_parts) if text_parts else None
```

**Fix**: Replace the broken loop with `msg.text_content or ""`.

### Root Cause B — `generate_reply()` called before Realtime WebRTC is ready

`create_english_realtime_session()` calls `session.generate_reply(user_input=initial_question)`
immediately after `await session.start(agent, room=room)`. The Realtime model needs time
(~1–2 seconds) to establish the WebRTC audio pipeline. Calling `generate_reply()` too early
results in silence — the reply is generated but has no audio channel to send through.

**Fix**: Wrap in `asyncio.create_task(_delayed_reply())` with a 1.5s sleep.

### Root Cause C — Agent does not wait for `langfuse-worker`

`docker-compose.yml` has:
```yaml
agent:
  depends_on:
    langfuse:
      condition: service_healthy  # ← only waits for web app, not the trace worker
```

The `langfuse-worker` service (which processes BullMQ queues) is not in the chain.
The agent starts sending OTEL spans immediately, but Langfuse's OTEL HTTP endpoint
may not be fully ready to accept and process traces until the worker is up.

**Fix**: Add `langfuse-worker: condition: service_started` to agent's `depends_on`.

### Root Cause D — English session never publishes transcripts

The English `conversation_item_added` handler in `english_agent.py` only does
guardrail checking — it never calls `publish_data` to send turns to the frontend.
Same content parsing bug as Root Cause A applies here too.

**Fix**: Add `publish_data` call in English handler, using `item.text_content`.

---

## Files Modified

| File | Change |
|---|---|
| `agent/main.py` | Fix content parsing: replace broken loop with `msg.text_content` |
| `agent/agents/english_agent.py` | Fix content parsing; add `publish_data`; delay `generate_reply` by 1.5s |
| `docker-compose.yml` | Add `langfuse-worker: service_started` to agent `depends_on` |
| `agent/tests/test_transcript_publishing.py` | 6 new tests covering content parsing + publish flow |

---

## Net Test Count

| File | Before | Added | After |
|---|---|---|---|
| `test_transcript_publishing.py` | 0 | 6 | 6 |
| All other test files | 52 | 0 | 52 |
| **Total** | **52** | **+6** | **58** |

---

## Key API Reference (confirmed by Docker exec)

- `ChatContent = str | AudioContent | ImageContent` (NOT an object with `.text`)
- `ChatMessage.text_content` property: `"\n".join([c for c in self.content if isinstance(c, str)])`
- `LocalParticipant.publish_data(payload, *, reliable=True, destination_identities=[], topic='')` — IS a coroutine function
- `session.generate_reply(user_input=...)` — NOT async, returns SpeechHandle (do not await)

---

## Verification

```bash
# Run all tests — target 58 passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Rebuild agent only (docker-compose.yml change requires full stack restart)
docker compose down && docker compose up -d --build

# Manual test:
# 1. Connect → Orchestrator greets → check transcript shows greeting
# 2. Ask "What is the Pythagorean theorem?" → transcript shows question + math response
# 3. Ask English question → transcript shows English agent responses
# 4. Say goodbye in English → transcript shows farewell
# 5. Open Langfuse UI → verify traces appear (no Connection refused errors)
```
