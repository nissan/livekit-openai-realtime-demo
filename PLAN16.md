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

### Bug B — Missing Transcript: `text_content` Was Empty (Initial Assumption)

Initial assumption: `forwarded_text = ""` in the Realtime SDK path → `conversation_item_added`
never fires with content → English turns never published.

**Corrected by live logs**: Diagnostic logging added in this plan revealed `text_content`
IS populated for the English agent. The `conversation_item_added` path was working all along
once PLAN15's unwrapping fix was in place.

### Bug C — Routing Context Shown as "You" in Transcript

When routing between agents, `generate_reply(user_input=question_summary)` is called
from `GuardedAgent.on_enter()`. This injects the routing question summary as a
`role="user"` conversation item, which `main.py`'s `on_conversation_item` published as
`speaker="student"` — appearing as "You" in the transcript panel even though the
student's original question was already shown.

---

## All Fixes Implemented (Iterative — 6 commits)

### Fix A1 — `agent/tools/routing.py`: Initial approach — interrupt() + 2s timer

Replaced the PLAN15 event-driven close with:
1. `pipeline_session.interrupt()` — stops TTS immediately after dispatch
2. `asyncio.create_task(_do_close_pipeline())` with `asyncio.sleep(2.0)` — closes 2s later
3. 30s fallback retained as safety net
4. Removed `conversation_item_added` event listener

**Problem discovered**: `interrupt()` was called while the orchestrator TTS was playing
its transition message ("Let me connect you with our English tutor!") — silencing it
completely. Students heard nothing before the English agent started.

---

### Fix A2 — `agent/tools/routing.py`: Remove interrupt(), extend to 3.5s ✓ FINAL

Removed `interrupt()` entirely. Changed sleep from `2.0s` to `3.5s`:
- Orchestrator gets ~3.5s to speak its transition sentence
- Pipeline closes at T+3.5s
- English agent starts speaking at T+4s (3s delay + ~1s WebRTC pipeline setup)
- **0.5s gap — no overlap, orchestrator speech heard**

---

### Fix B1 — `agent/agents/english_agent.py`: Diagnostic logging ✓ KEPT

Added unconditional `logger.info` at top of `_handle_conversation_item`:
```python
logger.info(
    "English conversation_item_added: role=%s text_content=%r",
    getattr(item, "role", None), getattr(item, "text_content", None)
)
```
Live logs confirmed `text_content` IS populated — `conversation_item_added` path works.
The `publish_data(topic="transcript")` path in `english_agent.py` was already functional.

---

### Fix B2 — `frontend/hooks/useTranscript.ts`: Three iterations

**Iteration 1** — `registerTextStreamHandler("lk.transcription", ...)`:
Added a second `useEffect` registering a text stream handler.

**Problem**: `@livekit/components-react` internally registers its own handler for
`"lk.transcription"`. The SDK only allows ONE handler per topic → `DataStreamError`
on mount, crashing the page.

**Iteration 2** — `room.on("transcriptionReceived", ...)`:
Switched to the Room EventEmitter event (supports multiple listeners). Filters
`final: true` segments from remote participants only.

**Problem**: `transcriptionReceived` fires for ALL remote participants (English AND
pipeline agents — orchestrator, math, history). Combined with the existing
`dataReceived(topic="transcript")` path, every turn appeared twice.

**Iteration 3 — FINAL**: Removed the `transcriptionReceived` useEffect entirely.
Diagnostic logs confirmed `text_content` is populated → `publish_data(topic="transcript")`
already works correctly for all agents including English. The single `dataReceived`
handler is sufficient.

---

### Fix C1 — Phantom "You" context messages: string-match approach

Added `pending_context: Optional[str]` to `SessionUserdata`.
Routing functions set `userdata.pending_context = question_summary`.
`on_conversation_item` compared `msg.text_content.strip() == pending_context.strip()` and
skipped publishing on match.

**Problem**: LLM varies the wording and casing of `question_summary` between
tool-call argument and actual injected text. Example:
- Tool arg: `"Learn about George Washington"`
- Injected text: `"learn about George Washington, which is a history topic."`
→ strings don't match → suppression silently fails.

---

### Fix C2 — `agent/models/session_state.py` + `agent/tools/routing.py` + `agent/main.py`: skip counter ✓ FINAL

Replaced `pending_context: Optional[str]` with `skip_next_user_turns: int = 0`.

**Routing functions** (`_route_to_math_impl`, `_route_to_history_impl`,
`_route_to_orchestrator_impl`) set `userdata.skip_next_user_turns = 1`.

**`main.py` pipeline entrypoint** also sets `skip_next_user_turns = 1` when
`pending_question` is recovered from re-dispatch metadata (orchestrator returning
from English Realtime session).

**`on_conversation_item`** in `main.py`: when `role == "user"` and
`skip_next_user_turns > 0`, decrements counter and returns early — no content
matching, always correct regardless of LLM phrasing.

---

## Final State of Modified Files

| File | Change |
|------|--------|
| `agent/tools/routing.py` | No `interrupt()`, close at 3.5s, `skip_next_user_turns = 1` per routing fn |
| `agent/agents/english_agent.py` | Diagnostic `logger.info` in `_handle_conversation_item` |
| `agent/models/session_state.py` | `skip_next_user_turns: int = 0` field |
| `agent/main.py` | Skip counter check in `on_conversation_item`; set counter on re-dispatch |
| `frontend/hooks/useTranscript.ts` | Single `dataReceived` handler only (all extra useEffects removed) |

---

## Commits (in order)

1. `fix(agent): interrupt pipeline TTS + lk.transcription frontend handler` — initial Fix A + B
2. `fix(frontend): switch English transcript from registerTextStreamHandler to transcriptionReceived` — DataStreamError fix
3. `fix(frontend): remove transcriptionReceived — conversation_item_added path works` — deduplication fix
4. `fix(agent): restore orchestrator transition speech + fix phantom user transcript` — Fix A2 + Fix C1
5. `fix(agent): replace string-match pending_context with skip_next_user_turns counter` — Fix C2 (final)

---

## Lessons Learned

1. **`interrupt()` stops in-progress TTS** — calling it after dispatch also silences the transition message the orchestrator was mid-sentence on. Never call `interrupt()` unless you explicitly want to silence all current speech.

2. **`registerTextStreamHandler` is single-subscriber** — `@livekit/components-react` owns `"lk.transcription"`. Use `room.on("transcriptionReceived", ...)` for multiple listeners, but be aware it fires for ALL agent participants.

3. **Diagnostic logging before fixing** — checking live logs would have revealed `text_content` was populated in PLAN15, avoiding the incorrect `forwarded_text = ""` assumption and saving two frontend iterations.

4. **LLM output is not deterministic** — never compare `question_summary` from a tool call against content generated at runtime. Use flags/counters, not string matching.

5. **`transcriptionReceived` fires for pipeline agents too** — it's not English-only. The `publish_data(topic="transcript")` + `dataReceived` path is the reliable single source of truth for all agent transcript turns.

---

## Verification

```bash
# 1. Tests still passing (72)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. English agent diagnostic logs confirm text_content populated:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "5m" | grep "English conversation_item_added"
# Expected: role=assistant text_content='Sure! Let's dive into...' (NOT None)

# 3. Pipeline closes ~3.5s after English dispatch (not 18s):
docker logs livekit-openai-realtime-demo-agent-1 --since "5m" | grep "Pipeline session closed"

# 4. End-to-end test:
#    - Ask "what is an adjective?" → routed to English
#    - Orchestrator says transition sentence before going silent    ← Fix A2 ✓
#    - ONE voice responds after ~4s (no overlap)                   ← Fix A2 ✓
#    - English transcript appears in panel                         ← Fix B ✓
#    - No "You" bubble for question summary context               ← Fix C2 ✓
#    - Ask "who was George Washington?" → routed to History
#    - No "You" bubble for routing context                        ← Fix C2 ✓
```

---

## Key Files

- `agent/tools/routing.py` — `_route_to_english_impl` + `_route_to_*_impl` routing functions
- `agent/agents/english_agent.py` — `create_english_realtime_session`, `_handle_conversation_item`
- `agent/models/session_state.py` — `SessionUserdata` with `skip_next_user_turns`
- `agent/main.py` — `on_conversation_item` handler, pipeline entrypoint
- `frontend/hooks/useTranscript.ts` — single `dataReceived` transcript hook
