# Plan: Fix Silent Handoffs + Broken Dispatch API

## Context

Live testing revealed two symptoms after the session-lifecycle fixes:

1. **English agent silently waits after activation** — after routing History→English, the
   English session activates but says nothing until the student re-prompts.
2. **Specialist agent silently waits after activation** — after routing back to Orchestrator
   then History (or Math), the specialist activates but says nothing until re-prompted.

Investigation (docker logs + source) found **three distinct root causes**:

### Root Cause A — `create_dispatch()` uses wrong API (CRITICAL)
Both `agent/tools/routing.py` and `agent/agents/english_agent.py` call:
```python
await api.agent_dispatch.create_dispatch(room_name=room_name, ...)  # WRONG
```
But the installed LiveKit API (`agent_dispatch_service.py`) requires a proto object:
```python
await api.agent_dispatch.create_dispatch(CreateAgentDispatchRequest(room=room_name, ...))
```
**Effect**: English dispatch _always_ fails → FallbackEnglishAgent runs in the pipeline
session without routing tools. The English→back dispatch also always fails →
OrchestratorAgent is never re-dispatched from English.

### Root Cause B — `generate_reply()` called without `user_input` → silence
`GuardedAgent.on_enter()` calls `await self.session.generate_reply()` with no arguments.
LiveKit's `_generate_reply` passes `user_message=None` to the LLM node. The LLM has no
explicit trigger to respond → produces nothing, waiting for the student to speak.

Confirmed by logs: every agent activation shows `last_user=''` even when a question
exists in history.

### Root Cause C — English Realtime session starts with empty context
`create_english_realtime_session()` creates a new `AgentSession` with no `chat_ctx`.
The student's English question is in the _pipeline_ session's history, not the English
session's history. Even with `generate_reply()` fixed, the English session has nothing
to respond to without the question being passed in.

---

## Files to Modify (5 files)

| File | Change |
|---|---|
| `agent/tools/routing.py` | Fix dispatch proto; set `_pending_question` on Math/History agents; add question to English dispatch metadata |
| `agent/agents/english_agent.py` | Fix dispatch proto; add `initial_question` param to session factory; override `on_enter` to no-op |
| `agent/main.py` | Parse `question` from dispatch metadata; pass to English session factory; set `_pending_question` on OrchestratorAgent on return |
| `agent/agents/base.py` | Use `user_input=_pending_question` in `generate_reply()` when set |
| `agent/tests/test_agent_handoffs.py` | Fix dispatch mock to assert proto object; add dispatch correctness tests |

New test file:

| File | Change |
|---|---|
| `agent/tests/test_handoff_question_context.py` | 6 new tests covering proto dispatch + `_pending_question` mechanism |

---

## Step-by-Step Changes

### Step 1 — Fix dispatch proto in `routing.py`

Add import at top:
```python
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest
```

In `_route_to_english_impl`, change dispatch call:
```python
# Before:
await api.agent_dispatch.create_dispatch(
    room_name=room_name,
    agent_name="learning-english",
    metadata=f"session:{session_id}",
)

# After:
await api.agent_dispatch.create_dispatch(
    CreateAgentDispatchRequest(
        agent_name="learning-english",
        room=room_name,
        metadata=f"session:{session_id}|question:{question_summary}",
    )
)
```

In `_route_to_math_impl`, after creating the specialist:
```python
specialist = MathAgent(chat_ctx=context.session.history)
specialist._pending_question = question_summary
return (specialist, "Let me connect you with our Mathematics tutor!")
```

In `_route_to_history_impl`, same pattern:
```python
specialist = HistoryAgent(chat_ctx=context.session.history)
specialist._pending_question = question_summary
return (specialist, "Let me connect you with our History tutor!")
```

In `_route_to_orchestrator_impl`, same pattern (for return from specialist):
```python
orchestrator = OrchestratorAgent(chat_ctx=context.session.history)
orchestrator._pending_question = reason
return (orchestrator, "Let me pass you back to your main tutor!")
```

### Step 2 — Fix dispatch proto + English session factory in `english_agent.py`

Add import:
```python
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest
```

In `route_back_to_orchestrator`, fix dispatch:
```python
await api.agent_dispatch.create_dispatch(
    CreateAgentDispatchRequest(
        agent_name="learning-orchestrator",
        room=room_name,
        metadata=f"return_from_english:{session_id}|question:{reason}",
    )
)
```

Override `on_enter()` in `EnglishAgent` to be a no-op (the session factory calls
`generate_reply()` directly with context so we avoid the no-context silent call):
```python
async def on_enter(self) -> None:
    # English Realtime session calls generate_reply() with initial_question
    # from dispatch metadata — we skip the default no-context on_enter.
    pass
```

Update `create_english_realtime_session()` signature and add explicit reply:
```python
async def create_english_realtime_session(
    room,
    participant,
    session_userdata,
    initial_question: str = "",
) -> AgentSession:
    ...
    await session.start(agent, room=room)

    if initial_question:
        # Immediately answer the question that caused routing to English
        session.generate_reply(user_input=initial_question)

    return session
```

### Step 3 — Parse metadata + pass question in `main.py`

Add a helper function at the top of the session entrypoints:
```python
def _parse_dispatch_metadata(metadata: str) -> dict:
    """Parse 'key:value|key:value' dispatch metadata into a dict."""
    result = {}
    for part in metadata.split("|"):
        if ":" in part:
            key, _, value = part.partition(":")
            result[key] = value
    return result
```

In `english_session_entrypoint()`:
```python
meta = _parse_dispatch_metadata(ctx.room.metadata or "")
existing_session_id = meta.get("session")
initial_question = meta.get("question", "")

session = await create_english_realtime_session(
    room=ctx.room,
    participant=participant,
    session_userdata=userdata,
    initial_question=initial_question,
)
```

In `pipeline_session_entrypoint()`, update the metadata parsing:
```python
meta = _parse_dispatch_metadata(ctx.room.metadata or "")
recovered_session_id = meta.get("return_from_english")
if not recovered_session_id:
    recovered_session_id = meta.get("session")  # plain session recovery

pending_question = meta.get("question", "")

userdata = SessionUserdata(student_identity=student_identity, room_name=room_name)
if recovered_session_id:
    userdata.session_id = recovered_session_id

orchestrator = OrchestratorAgent()
if pending_question:
    orchestrator._pending_question = pending_question

await session.start(orchestrator, room=ctx.room)
```

### Step 4 — Use `_pending_question` in `base.py`

```python
async def on_enter(self) -> None:
    # ... existing diagnostic logging ...

    pending_q = getattr(self, "_pending_question", None)
    if pending_q:
        await self.session.generate_reply(user_input=pending_q)
    else:
        await self.session.generate_reply()
```

### Step 5 — Update tests in `test_agent_handoffs.py`

Fix existing English routing test to assert proto object:
```python
from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest

def test_orchestrator_can_route_to_english(...):
    ...
    call_arg = mock_api.agent_dispatch.create_dispatch.call_args[0][0]
    assert isinstance(call_arg, CreateAgentDispatchRequest)
    assert call_arg.room == room_name
    assert call_arg.agent_name == "learning-english"
```

### Step 6 — New `agent/tests/test_handoff_question_context.py`

```python
"""Tests that question context is preserved through agent handoffs."""

class TestDispatchProto:
    def test_route_to_english_uses_create_agent_dispatch_request(...):
        # verify CreateAgentDispatchRequest is used, not keyword args
        # assert call_arg.room == room_name, call_arg.agent_name == "learning-english"

    def test_english_back_uses_create_agent_dispatch_request(...):
        # verify english_agent.route_back_to_orchestrator uses proto

class TestPendingQuestion:
    def test_route_to_math_sets_pending_question(...):
        # _route_to_math_impl sets specialist._pending_question = question_summary

    def test_route_to_history_sets_pending_question(...):
        # _route_to_history_impl sets specialist._pending_question = question_summary

    def test_on_enter_uses_pending_question_as_user_input(...):
        # mock session; set agent._pending_question; call on_enter()
        # assert generate_reply called with user_input=pending_q

    def test_on_enter_without_pending_question_uses_no_user_input(...):
        # mock session; no _pending_question; call on_enter()
        # assert generate_reply called with no args
```

---

## Net Test Count

| File | Before | Added/Changed | After |
|---|---|---|---|
| `test_agent_handoffs.py` | 16 | 2 updated + 2 new | 18 |
| `test_handoff_question_context.py` | 0 | 6 | 6 |
| All other test files | 28 | 0 | 28 |
| **Total** | **44** | **+8** | **52** |

---

## Critical Files

- `agent/tools/routing.py` — dispatch proto fix + `_pending_question` on specialists
- `agent/agents/english_agent.py` — dispatch proto fix + `on_enter` no-op + session factory
- `agent/main.py` — metadata parsing + question pass-through
- `agent/agents/base.py` — `_pending_question` → `user_input` in `generate_reply()`
- `agent/tests/test_agent_handoffs.py` — fix existing mock assertions
- `agent/tests/test_handoff_question_context.py` (new)

## Installed API Reference

- `create_dispatch` signature: `async def create_dispatch(self, req: CreateAgentDispatchRequest) -> AgentDispatch`
- `CreateAgentDispatchRequest` fields: `agent_name: str`, `room: str`, `metadata: str`
- Import: `from livekit.protocol.agent_dispatch import CreateAgentDispatchRequest`
- `generate_reply` signature: `def generate_reply(self, *, user_input=NOT_GIVEN, ...) -> SpeechHandle` (NOT async)
- `AgentSession.aclose()` exists at line 912 (already used in existing code)

---

## Architect Audit Copy

Save this plan to the project root as `PLAN6.md` during implementation (same pattern as
PLAN4.md and PLAN5.md):
```bash
cp /Users/nissan/.claude/plans/transient-wandering-lovelace.md \
   /Users/nissan/code/livekit-openai-realtime-demo/PLAN6.md
```

---

## Verification

```bash
# Run all tests — target 52 passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Targeted: just new handoff tests
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_handoff_question_context.py -v

# Rebuild and restart only agent
docker compose up -d --build agent
```

Manual test after restart:
1. Connect → let Orchestrator greet
2. Ask history question → interrupt → ask English question
   **Expected**: English agent immediately answers (not silent)
3. In English, ask history question
   **Expected**: Orchestrator takes over, routes to History, History immediately answers (not silent)
4. In English, say "goodbye"
   **Expected**: English routes back, Orchestrator gives farewell
