# Plan: Fix English Tutor Handoff — Two Blocking Bugs (PLAN13)

## Context

PLAN12 removed the `instructions=` kwarg from `RealtimeModel()` (fixing a crash before session creation).
The handoff to the English tutor still produced silence. Docker logs revealed TWO remaining blocking bugs:

**Confirmed crash from `docker logs` (12:23:50 dispatch):**
```
ValueError: Cannot register an async callback with `.on()`.
Use `asyncio.create_task` within your synchronous callback instead.
  File "/workspace/agent/agents/english_agent.py", line 188, in create_english_realtime_session
    @session.on("conversation_item_added")
```

This was the NEW crash after PLAN12. The English agent crashed immediately at event
registration, before `session.start()` was ever called. The transition TTS message from
the pipeline ("Perfect! Switching to English now...") played and completed, but English
never produced audio because the session never started.

Additionally confirmed from proto inspection (`ctx.job.DESCRIPTOR.fields_by_name.keys()`):
`agent.Job` has a `metadata` field — but both entrypoints incorrectly read `ctx.room.metadata`
(the room's creation-time metadata) instead of `ctx.job.metadata` (the dispatch request metadata).
This meant `initial_question` was always `""` and session ID recovery never worked.

---

## Root Cause Analysis

### Bug 1 — Async callback rejected by EventEmitter (CRASH)

**File:** `agent/agents/english_agent.py`, line 188–189

```python
# BEFORE (crashes — livekit-agents v1.4.2 rejects async callbacks in .on()):
@session.on("conversation_item_added")
async def on_item_added(item):
    content_text = item.text_content or ""
    ...
    result = await guardrail_service.check(content_text)   # async — requires async def
    ...
```

In livekit-agents v1.4.2, `EventEmitter.on()` validates the callback at registration time
and raises `ValueError` if it's an `async def`. This change is SDK-side (not our code).
The crash occurred at `@session.on(...)` decoration, before `session.start()` was called.

**Fix:** Convert to a sync dispatcher that spawns a task:
```python
async def _handle_conversation_item(item):
    # all async logic here, using direct `await`
    ...

@session.on("conversation_item_added")
def on_item_added(item):
    asyncio.create_task(_handle_conversation_item(item))
```

### Bug 2 — Wrong metadata source: `ctx.room.metadata` vs `ctx.job.metadata`

**File:** `agent/main.py`, lines 100 and 298

```python
# BEFORE (wrong — reads room creation-time metadata, always empty for dispatches):
meta = _parse_dispatch_metadata(ctx.room.metadata or "")
```

`ctx.room.metadata` is the LiveKit room's metadata set at room creation time.
`CreateAgentDispatchRequest(..., metadata=f"session:{id}|question:{text}")` stores its
metadata on the Job proto, accessible via `ctx.job.metadata`.

Confirmed: `agent.Job` proto has `metadata` field (from `agent.Job().DESCRIPTOR.fields_by_name.keys()`).

**Fix (two locations):**
```python
# BOTH entrypoints → use ctx.job.metadata:
meta = _parse_dispatch_metadata(ctx.job.metadata or "")
```

- `pipeline_session_entrypoint` line 100: return-from-English session ID recovery
- `english_session_entrypoint` line 298: initial_question and session_id for English

---

## Files Modified

| File | Line | Change |
|------|------|--------|
| `agent/agents/english_agent.py` | 186–265 | Convert `async def on_item_added` → sync dispatcher + `async def _handle_conversation_item` |
| `agent/main.py` | 100 | `ctx.room.metadata` → `ctx.job.metadata` |
| `agent/main.py` | 298 | `ctx.room.metadata` → `ctx.job.metadata` |

---

## Changes Applied

### `agent/agents/english_agent.py` — Sync dispatcher + async helper

```python
    # Post-hoc guardrail + transcript publishing for Realtime session.
    # FIXED (PLAN13): livekit-agents v1.4.2 rejects async callbacks in .on()
    # Use a sync dispatcher that spawns an async task.
    async def _handle_conversation_item(item):
        content_text = item.text_content or ""

        if item.role == "assistant" and content_text:
            with _tracer.start_as_current_span("conversation.item") as span:
                span.set_attribute("langfuse.session_id", session_userdata.session_id)
                span.set_attribute("langfuse.user_id", session_userdata.student_identity)
                span.set_attribute("session.id", session_userdata.session_id)
                span.set_attribute("user.id", session_userdata.student_identity)
                span.set_attribute("subject_area", "english")
                span.set_attribute("role", "assistant")
                span.set_attribute("session_type", "realtime")
                span.set_attribute("turn", getattr(session_userdata, "turn_number", 0))

            result = await guardrail_service.check(content_text)
            if result.flagged:
                logger.warning(...)
                await guardrail_service.log_guardrail_event(...)

            payload = json.dumps({...})
            await room.local_participant.publish_data(payload.encode(), topic="transcript")

        elif item.role == "user" and content_text:
            with _tracer.start_as_current_span("conversation.item") as span:
                ...

            payload = json.dumps({...})
            await room.local_participant.publish_data(payload.encode(), topic="transcript")

    @session.on("conversation_item_added")
    def on_item_added(item):
        asyncio.create_task(_handle_conversation_item(item))
```

### `agent/main.py` lines 100 and 298

```python
# FIXED (PLAN13): ctx.job.metadata holds dispatch request metadata, not ctx.room.metadata
meta = _parse_dispatch_metadata(ctx.job.metadata or "")
```

---

## Verification

```bash
# 1. Run tests — 72 still passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild + restart
docker compose up -d --build agent agent-english

# 3. Check agent-english logs — no ValueError:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "5m"

# 4. Test session:
#    - Ask English question ("what is a pronoun?")
#    - Pipeline says "Switching to English now..."  ← plays fully ✓
#    - English tutor SPEAKS (Bug 1 crash fixed)    ← key fix ✓
#    - English greets with the specific question   ← Bug 2 metadata fix ✓
#    - Langfuse: English session.start span appears ← confirms session started ✓
```

## Results

- 72/72 tests pass
- `agent-english` starts cleanly — no `ValueError` at startup
- Commit: `482de9f` — fix(agent): fix English async callback crash + metadata source (PLAN13)

---

## Why Previous Plans Didn't Fix This

- **PLAN11**: Fixed missing `await` on `generate_reply()` — correct, but crash at line 188 happened first
- **PLAN12**: Fixed `instructions=` kwarg on `RealtimeModel()` — correct, but new crash at line 188 (async callback) still blocked session creation
- **PLAN13**: Fixes the actual crash that persisted through PLAN11 and PLAN12, plus the metadata routing that caused `initial_question` to always be empty
