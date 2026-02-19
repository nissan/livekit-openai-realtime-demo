# Plan: Session Lifecycle Fixes + Observability

## Context

Two bugs were reported during live testing:

1. **Wrong history question after English detour** — After routing
   History→English→History, the History agent answered the *old* History
   question (Q1) instead of the new one (Q2) asked after returning from
   the English session.

2. **"Goodbye" did not end the English session** — Saying "goodbye" to the
   English agent caused it to respond "bye!" and continue running instead
   of routing back to the orchestrator to end the session.

---

## Root Cause Analysis

### Bug 1 — Competing pipeline session (History Q1 vs Q2)

`_route_to_english_impl` dispatched the English Realtime worker but returned
a **plain string** (not an `(Agent, str)` tuple). This meant the original
pipeline session's OrchestratorAgent **stayed alive** in the room.

Both the English session and the original OrchestratorAgent received the
student's audio via STT. When the student asked History Q2 to the English
agent, the old OrchestratorAgent also heard it, routed to HistoryAgent using
the **stale full chat history** (which still had History Q1 as the most
recent pending question). Two HistoryAgent instances competed in the room and
the one with stale context answered History Q1.

**Confirmed API**: `AgentSession.aclose()` exists (line 912 of
`voice/agent_session.py` in livekit-agents v1.4) and calls
`_aclose_impl(reason=CloseReason.USER_INITIATED)`.

### Bug 2 — English agent ignored "goodbye"

`route_back_to_orchestrator`'s tool description said *"when the student asks
about a different subject"*. "Goodbye" does not match that pattern, so
`gpt-realtime` just said farewell and kept the session running. There was no
instruction in the system prompt to route back on session-ending intent.

---

## Files Modified (4 files)

| File | Change |
|---|---|
| `agent/tools/routing.py` | Add `_get_last_user_message` + `_get_history_length` helpers; add `last_user_message` + `history_length` to all `routing.decision` OTEL spans; schedule `AgentSession.aclose()` 4s after English dispatch |
| `agent/agents/english_agent.py` | Add `asyncio` import; expand `route_back_to_orchestrator` description to include goodbye/end-session; add goodbye instruction to `ENGLISH_SYSTEM_PROMPT`; schedule `AgentSession.aclose()` 3s after routing back |
| `agent/main.py` | Read `ctx.room.metadata` for `return_from_english:{session_id}` in `pipeline_session_entrypoint` and recover session_id for Langfuse/Supabase continuity |
| `agent/agents/base.py` | Add diagnostic logging in `on_enter()`: logs `history_length` and `last_user_message` every time an agent activates |

---

## Fix Details

### Fix 1: Close pipeline session after English dispatch (`routing.py`)

After a successful English worker dispatch, schedule `aclose()` on the
pipeline session with a 4-second delay (allows the TTS routing message to
finish playing):

```python
pipeline_session = context.session

async def _close_pipeline_after_english_dispatch():
    await asyncio.sleep(4.0)
    try:
        await pipeline_session.aclose()
        logger.info("Pipeline session closed after English dispatch [session=%s]", session_id)
    except Exception:
        logger.exception("Failed to close pipeline session after English routing")

asyncio.create_task(_close_pipeline_after_english_dispatch())
```

Only fires on the **success path** (inside the try block, after dispatch).
The fallback path (dispatch failure → FallbackEnglishAgent) is unaffected.

### Fix 2: Close English session after routing back (`english_agent.py`)

Mirrors Fix 1. After dispatching the new "learning-orchestrator" worker,
schedule `aclose()` on the English session:

```python
async def _close_english_after_dispatch():
    await asyncio.sleep(3.0)
    try:
        await english_session.aclose()
    except Exception:
        logger.exception("Failed to close English session after routing back")

asyncio.create_task(_close_english_after_dispatch())
```

### Fix 3: Handle goodbye in English agent (`english_agent.py`)

Tool description update:
```python
@function_tool(
    description=(
        "Route back to the orchestrator when: the student asks about a different "
        "subject (maths, history, etc.); OR the student says goodbye, thanks, or "
        "wants to end or pause the tutoring session."
    )
)
```

System prompt addition:
```
When the student says goodbye, thank them for the session, and ALWAYS call
route_back_to_orchestrator so the main tutor can give a proper farewell.
```

### Fix 4: Session ID recovery (`main.py`)

When `pipeline_session_entrypoint` is invoked after the English agent
dispatches "learning-orchestrator" back, it now reads `ctx.room.metadata`
for the `return_from_english:{id}` pattern and restores the session_id:

```python
ctx_metadata = ctx.room.metadata or ""
recovered_session_id = None
if ctx_metadata.startswith("return_from_english:"):
    recovered_session_id = ctx_metadata.split(":", 1)[1]

userdata = SessionUserdata(student_identity=student_identity, room_name=room_name)
if recovered_session_id:
    userdata.session_id = recovered_session_id
    userdata.current_subject = "orchestrator"
```

This keeps the full History→English→History journey under **one session ID**
in Langfuse and Supabase.

### Fix 5: Observability (`routing.py` + `base.py`)

All `routing.decision` OTEL spans now carry:
- `last_user_message` — the most recent user utterance at routing time (≤500 chars)
- `history_length` — number of messages in chat history at routing time

`GuardedAgent.on_enter()` now logs:
```
{agent_name}.on_enter history_length={n} last_user='...'
```

Both are visible in Langfuse traces and container logs, enabling post-hoc
diagnosis of "which question did the agent actually see when it activated?".

---

## Test Results

```
44 passed in 1.38s
```

No new tests were added (session `aclose()` timing and job context recovery
require live infrastructure; existing mock-based suite covers routing logic).

---

## Timing Notes

| Delay | Purpose |
|---|---|
| 4s (pipeline close after English dispatch) | Allows ~8-word TTS routing message to play |
| 3s (English close after routing back) | Allows ~8-word TTS farewell message to play |

If TTS latency changes significantly, these values may need adjustment.

---

## Verification

Reproduce the original bugs and confirm they are fixed:

1. Ask a history question → interrupt → ask English question → interrupt → ask a NEW history question.
   **Expected**: History agent answers the NEW question, not the old one.

2. While in the English session, say "goodbye".
   **Expected**: English agent says goodbye and routes back to the orchestrator.

3. Check Langfuse traces:
   - All `routing.decision` spans should have `last_user_message` and `history_length` attributes.
   - After returning from English, History→English→History should appear under the **same session_id**.

## Status: IMPLEMENTED ✓
Date: 2026-02-19
Commit: a8fad49
