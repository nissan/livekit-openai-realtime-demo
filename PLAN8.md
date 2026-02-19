# Plan: Comprehensive Langfuse OTEL Coverage (PLAN8)

## Context

After PLAN7 fixed the transcript data channel and Langfuse worker dependency, the OTEL
spans that DO fire will now reach Langfuse correctly. However, the current coverage has
critical blind spots that make it impossible to diagnose failures during manual testing:

- **Entire English Realtime session is invisible** — no OTEL spans at all (conversation items,
  session start/end, nothing). This is the most-used alternative session type.
- **No session root span** — Langfuse has no way to group all spans from one session.
  The first span it sees is a `conversation.item` or `routing.decision` floating without context.
  `create_session_trace()` helper already exists in `langfuse_setup.py` but is never called.
- **Agent activation not traced** — cannot see WHEN each agent becomes active or which
  agent is currently serving. Critical for debugging routing delays and "silent" handoffs.
- **Teacher escalation not traced** — the highest-priority safety event has no OTEL span.
- **Diagnostic `on_enter()` log has same PLAN7 content bug** — `hasattr(part, "text")` always
  produces empty `last_user_text` in the log, degrading log quality.

---

## Gaps Fixed in This Plan

| Gap | Impact | Where |
|-----|--------|--------|
| No session.start / session.end spans | Cannot link spans to a session in Langfuse | `agent/main.py` |
| English session has 0 OTEL spans | Entire Realtime session invisible to Langfuse | `agent/agents/english_agent.py` |
| Agent activation not traced | Cannot debug routing timing or silent agents | `agent/agents/base.py` |
| Teacher escalation not traced | Safety event invisible to Langfuse | `agent/tools/routing.py` |
| `on_enter()` diagnostic uses broken hasattr | Always logs empty last_user_text | `agent/agents/base.py` |

---

## Files to Modify

| File | Change |
|------|--------|
| `agent/main.py` | Add `session.start` + `session.end` spans in both entrypoints |
| `agent/agents/english_agent.py` | Add `conversation.item` OTEL spans in `on_item_added` |
| `agent/agents/base.py` | Add `agent.activated` span in `on_enter()`; fix broken hasattr loop |
| `agent/tools/routing.py` | Add `teacher.escalation` span in `_escalate_impl()` |
| `agent/tests/test_langfuse_otel_coverage.py` | 5 new tests for new spans |

---

## Step-by-Step Changes

### Step 1 — Session start/end spans in `main.py`

**1a — Pipeline session (`pipeline_session_entrypoint`)**

After userdata is initialized (after `await transcript_store.create_session_record(...)`):

```python
tracer = get_tracer("pipeline-session")

# Session start marker — creates root trace context in Langfuse
with tracer.start_as_current_span("session.start") as span:
    span.set_attributes(create_session_trace(
        userdata.session_id, student_identity, room_name
    ))
    span.set_attribute("session_type", "pipeline")
    span.set_attribute("recovered", bool(recovered_session_id))
```

After `await transcript_store.close_session_record(...)`:

```python
with tracer.start_as_current_span("session.end") as span:
    span.set_attribute("langfuse.session_id", userdata.session_id)
    span.set_attribute("langfuse.user_id", student_identity)
    span.set_attribute("session.id", userdata.session_id)
    span.set_attribute("session_type", "pipeline")
    span.set_attribute("total_turns", userdata.turn_number)
    span.set_attribute("escalated", userdata.escalated)
    span.set_attribute("subjects_covered", ",".join(set(
        userdata.previous_subjects + ([userdata.current_subject] if userdata.current_subject else [])
    )))
```

**1b — English session (`english_session_entrypoint`)**

After `session = await create_english_realtime_session(...)`:

```python
tracer_eng = get_tracer("english-session")
with tracer_eng.start_as_current_span("session.start") as span:
    span.set_attributes(create_session_trace(
        userdata.session_id, student_identity, room_name
    ))
    span.set_attribute("session_type", "realtime_english")
```

After `await session_closed.wait()`:

```python
with tracer_eng.start_as_current_span("session.end") as span:
    span.set_attribute("langfuse.session_id", userdata.session_id)
    span.set_attribute("langfuse.user_id", student_identity)
    span.set_attribute("session.id", userdata.session_id)
    span.set_attribute("session_type", "realtime_english")
```

**Import change**: Add `create_session_trace` to the import from `langfuse_setup`:
```python
from agent.services.langfuse_setup import setup_langfuse_tracing, get_tracer, create_session_trace
```

### Step 2 — English session `conversation.item` spans in `english_agent.py`

Inside `create_english_realtime_session()`, after the existing imports, get a tracer:

```python
from agent.services.langfuse_setup import get_tracer as _get_tracer
_tracer = _get_tracer("english-realtime-session")
```

Inside `on_item_added`, wrap the content block in an OTEL span:

```python
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
    # existing guardrail check + publish_data code continues below

elif item.role == "user" and content_text:
    with _tracer.start_as_current_span("conversation.item") as span:
        span.set_attribute("langfuse.session_id", session_userdata.session_id)
        span.set_attribute("langfuse.user_id", session_userdata.student_identity)
        span.set_attribute("session.id", session_userdata.session_id)
        span.set_attribute("subject_area", "english")
        span.set_attribute("role", "user")
        span.set_attribute("session_type", "realtime")
    # existing publish_data code continues below
```

### Step 3 — Agent activation span in `base.py`

Add import at top of `base.py`:
```python
from agent.services.langfuse_setup import get_tracer as _get_tracer
_tracer = _get_tracer("agent-lifecycle")
```

In `on_enter()`, add OTEL span (immediately closes — just a marker):
```python
async def on_enter(self) -> None:
    try:
        session_id = self.session.userdata.session_id
        student_identity = self.session.userdata.student_identity
    except AttributeError:
        session_id = "unknown"
        student_identity = "unknown"

    with _tracer.start_as_current_span("agent.activated") as span:
        span.set_attribute("agent_name", self.agent_name)
        span.set_attribute("langfuse.session_id", session_id)
        span.set_attribute("langfuse.user_id", student_identity)
        span.set_attribute("session.id", session_id)

    # Existing diagnostic logging (also fix broken hasattr → text_content):
    try:
        msgs = list(self.session.history.messages())
        last_user_text = ""
        for msg in reversed(msgs):
            if msg.role == "user":
                last_user_text = msg.text_content or ""  # FIXED: was hasattr(part, "text")
                break
        logger.info(
            "%s.on_enter history_length=%d last_user=%.150r",
            self.agent_name, len(msgs), last_user_text,
        )
    except Exception:
        logger.debug("%s.on_enter: could not inspect history", self.agent_name)

    pending_q = getattr(self, "_pending_question", None)
    ...
```

### Step 4 — Teacher escalation span in `routing.py`

In `_escalate_impl()`, wrap the escalation logic in a span:

```python
async def _escalate_impl(agent, context: RunContext, reason: str) -> str:
    userdata = context.session.userdata
    session_id = userdata.session_id
    room_name = userdata.room_name
    from_agent = getattr(agent, "agent_name", "unknown")
    userdata.escalated = True
    userdata.escalation_reason = reason

    with tracer.start_as_current_span("teacher.escalation") as span:
        span.set_attribute("langfuse.session_id", session_id)
        span.set_attribute("langfuse.user_id", userdata.student_identity)
        span.set_attribute("session.id", session_id)
        span.set_attribute("from_agent", from_agent)
        span.set_attribute("reason", reason[:500])
        span.set_attribute("room_name", room_name)
        span.set_attribute("turn_number", userdata.turn_number)

    # existing asyncio.create_task + logger.warning + human_escalation call unchanged
```

`tracer` is already imported at the top of `routing.py` from `get_tracer("routing")`.

### Step 5 — New `agent/tests/test_langfuse_otel_coverage.py` (5 tests)

```python
class TestSessionSpans:
    def test_session_start_attributes_from_helper():
        # create_session_trace() returns dict with correct Langfuse keys
        # assert "langfuse.session_id", "langfuse.user_id", "room.name" present

    def test_session_end_attributes_contain_stats():
        # Verify escalated/total_turns/subjects_covered fields

class TestAgentActivationSpan:
    async def test_on_enter_emits_agent_activated_span():
        # Mock tracer, fire on_enter, verify span created with agent_name attribute

class TestEscalationSpan:
    async def test_escalate_impl_emits_teacher_escalation_span():
        # Mock tracer + human_escalation, call _escalate_impl
        # verify span created with from_agent, reason, session attributes

class TestEnglishSessionSpans:
    def test_conversation_item_attributes_for_english_assistant():
        # Verify subject_area="english", session_type="realtime", role="assistant"
```

---

## Net Test Count

| File | Before | Added | After |
|------|--------|-------|-------|
| `test_langfuse_otel_coverage.py` | 0 | 5 | 5 |
| All other test files | 58 | 0 | 58 |
| **Total** | **58** | **+5** | **63** |

---

## Critical Files

- `agent/main.py` — both entrypoints; import `create_session_trace`
- `agent/agents/english_agent.py` — `on_item_added` handler (lines 184–245)
- `agent/agents/base.py` — `on_enter()` (lines 98–127)
- `agent/tools/routing.py` — `_escalate_impl()` (lines 258–285)
- `agent/services/langfuse_setup.py` — read-only reference; `create_session_trace()` at line 87
- `agent/tests/test_langfuse_otel_coverage.py` (new)

---

## Verification

```bash
# Run all tests — target 63 passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Rebuild and verify Langfuse traces during manual test:
docker compose down && docker compose up -d --build

# In Langfuse UI (http://localhost:3000):
# 1. Traces → filter by langfuse.session_id → should see session.start as first span
# 2. Per session: session.start → agent.activated (orchestrator) → conversation.item (turns)
# 3. Routing to Math → routing.decision span appears
# 4. Route to English → session.start (realtime_english) + conversation.item spans
# 5. Teacher escalation → teacher.escalation span in timeline
# 6. Session end → session.end span with total_turns + subjects_covered
```
