# Plan: Fix Two Voices + Missing Transcript (PLAN15)

## Context

After PLAN14, the English tutor session now starts successfully (no more crashes). However:
1. **Two voices heard simultaneously** — both pipeline (orchestrator) and English Realtime agents speak at the same time when a student asks about adjectives/pronouns.
2. **No transcript visible for English tutor** — transcript display and Langfuse show nothing from the English agent.

Both bugs share the **same single root cause** confirmed by docker logs + source inspection.

---

## Root Cause — `ConversationItemAddedEvent` Wrapper Not Unwrapped

**Confirmed from docker logs (`agent-english`):**
```
AttributeError: 'ConversationItemAddedEvent' object has no attribute 'text_content'
  File "/workspace/agent/agents/english_agent.py", line 191, in _handle_conversation_item
    content_text = item.text_content or ""
```

**Confirmed from SDK source inspection** (`agent_session.py:1333`):
```python
def _conversation_item_added(self, message: llm.ChatMessage) -> None:
    self._chat_ctx.insert(message)
    self.emit("conversation_item_added", ConversationItemAddedEvent(item=message))
```

`conversation_item_added` **always** fires with a `ConversationItemAddedEvent(item=ChatMessage)` wrapper — on **both** the Realtime session AND the pipeline `AgentSession`. The actual data is at `.item`.

**Two affected locations:**

### Bug A — `english_agent.py` `_handle_conversation_item` (missing transcript)

```python
# CURRENT (crashes — treats ConversationItemAddedEvent as ChatMessage):
async def _handle_conversation_item(item):
    content_text = item.text_content or ""   # AttributeError — no .text_content on event
    if item.role == "assistant" and content_text:  # also wrong
```

Every item callback crashes silently in a background task. No transcript, no guardrail, no Langfuse spans for English turns.

### Bug B — `routing.py` `_on_transition_committed` (two voices)

```python
# CURRENT (never triggers — getattr on ConversationItemAddedEvent, not ChatMessage):
def _on_transition_committed(item):
    if getattr(item, "role", None) == "assistant":   # always None — wrong object
        asyncio.create_task(_do_close_pipeline())
```

`item.role` is always `None` (the event wrapper has no `role` attribute — it's in `item.item.role`). So the close never triggers, the 30s fallback fires instead. During those ~37 seconds both agents compete in the same room → two voices.

---

## Files Modified

| File | Change |
|------|--------|
| `agent/agents/english_agent.py` | Unwrap `event.item` in `_handle_conversation_item` |
| `agent/tools/routing.py` | Unwrap `event.item` in `_on_transition_committed` |

---

## Changes Applied

### Step 1 — `agent/agents/english_agent.py`: Unwrap event in handler

```python
# BEFORE:
async def _handle_conversation_item(item):
    content_text = item.text_content or ""
    if item.role == "assistant" and content_text:
        ...
    elif item.role == "user" and content_text:
        ...

@session.on("conversation_item_added")
def on_item_added(item):
    asyncio.create_task(_handle_conversation_item(item))

# AFTER (PLAN15): unwrap ConversationItemAddedEvent wrapper
async def _handle_conversation_item(event):
    item = event.item  # ConversationItemAddedEvent.item is the ChatMessage
    content_text = item.text_content or ""
    if item.role == "assistant" and content_text:
        ...
    elif item.role == "user" and content_text:
        ...

@session.on("conversation_item_added")
def on_item_added(event):
    asyncio.create_task(_handle_conversation_item(event))
```

### Step 2 — `agent/tools/routing.py`: Unwrap event in close handler

```python
# BEFORE:
def _on_transition_committed(item):
    if getattr(item, "role", None) == "assistant":
        asyncio.create_task(_do_close_pipeline())
        pipeline_session.off("conversation_item_added", _on_transition_committed)

# AFTER (PLAN15): unwrap ConversationItemAddedEvent wrapper
def _on_transition_committed(event):
    if getattr(event.item, "role", None) == "assistant":
        asyncio.create_task(_do_close_pipeline())
        pipeline_session.off("conversation_item_added", _on_transition_committed)
```

---

## Expected Outcome

- **Two voices fixed**: `_on_transition_committed` now correctly detects `role == "assistant"` → pipeline closes in ~5-8s instead of ~37s → no overlap
- **Transcript fixed**: `_handle_conversation_item` no longer crashes → English turns published to data channel + Langfuse spans appear
- **Guardrail working**: post-hoc check now runs on English agent responses

---

## Verification

```bash
# 1. Tests — 72 still passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild agents
docker compose up -d --build agent agent-english

# 3. Check logs — no AttributeError:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "5m" | grep -i error

# 4. End-to-end:
#    - Ask "what is an adjective?"
#    - Only ONE voice responds (English tutor)          ← Bug B fix ✓
#    - Transcript shows English tutor turns             ← Bug A fix ✓
#    - Langfuse: conversation.item spans for English    ← Bug A fix ✓
#    - Pipeline closes ~5-8s after handoff (not 37s)   ← Bug B fix ✓
```
