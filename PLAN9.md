# Plan: Fix English Handoff + Transcript Speaker Bug (PLAN9)

## Context

Two bugs found during manual testing of the PLAN8 build:

**Bug 1 — English Realtime session never starts (critical)**
The `learning-english` worker is dispatched correctly via the LiveKit agent dispatch API
(`route_to_english` succeeds and logs "Dispatched learning-english worker to room"), but
**no worker process ever picks up the job** because `learning-english` is never registered.

Root cause: `AgentServer` supports exactly ONE `rtc_session` (confirmed in SDK source:
`"The AgentServer currently only supports registering only one rtc_session"`).
`main.py` registers only `learning-orchestrator`. The `english_session_entrypoint` function
exists but is never wired to a worker. The agent Dockerfile even has the comment
"Override CMD in docker-compose to run english worker separately if needed" — the
architecture was always meant to have a second service.

**Bug 2 — Transcript speaker shows DESTINATION agent, not SOURCE agent**
The `on_conversation_item` handler in `main.py` uses:
```python
speaker = "student" if role == "user" else userdata.current_subject or "orchestrator"
```
But routing functions call `userdata.route_to("math")` (which sets `current_subject = "math"`)
BEFORE the `conversation_item_added` event fires for the transition message. Result:
- "Let me connect you with the Math tutor!" → speaker shows "math" (should be "orchestrator")
- "Let me pass you back to the main tutor!" → speaker shows "orchestrator" (should be "math")

---

## Gaps Fixed in This Plan

| Bug | Symptom | Root Cause | Where |
|-----|---------|------------|-------|
| English session never starts | No English OTEL spans, no English audio | `learning-english` worker never registered | `docker-compose.yml` + `agent/main.py` |
| Transcript speaker wrong | "math" appears as speaker of orchestrator's routing message | `current_subject` is updated before `conversation_item_added` fires | `agent/models/session_state.py` + `agent/agents/base.py` + `agent/main.py` |

---

## Files Modified

| File | Change |
|------|--------|
| `agent/main.py` | Add `AGENT_TYPE` env-var branch to register either orchestrator or english worker; use `speaking_agent` for transcript speaker |
| `agent/models/session_state.py` | Add `speaking_agent: Optional[str] = None` field |
| `agent/agents/base.py` | Set `userdata.speaking_agent = self.agent_name` at top of `on_enter()` |
| `docker-compose.yml` | Add `agent-english` service with `AGENT_TYPE=english` (same image, no prewarm) |
| `agent/tests/test_transcript_speaker.py` | 2 new tests verifying speaker correctness |

---

## Step-by-Step Changes

### Step 1 — `agent/main.py`: AGENT_TYPE branch + speaking_agent for transcript

**1a — Import/registration block at `__main__`** (replaces the existing `if __name__ == "__main__":` block):
```python
if __name__ == "__main__":
    setup_langfuse_tracing()

    agent_type = os.environ.get("AGENT_TYPE", "orchestrator")

    if agent_type == "english":
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=english_session_entrypoint,
                agent_name="learning-english",
                # No prewarm — RealtimeModel handles audio natively, no VAD needed
            ),
        )
    else:
        cli.run_app(
            WorkerOptions(
                entrypoint_fnc=pipeline_session_entrypoint,
                prewarm_fnc=prewarm,
                agent_name="learning-orchestrator",
            ),
        )
```

**1b — Fix transcript speaker** (in `on_conversation_item` handler, line 162):
```python
# BEFORE:
speaker = "student" if role == "user" else userdata.current_subject or "orchestrator"

# AFTER:
if role == "user":
    speaker = "student"
else:
    # speaking_agent is set by GuardedAgent.on_enter() AFTER the transition message fires,
    # so it correctly identifies who SAID the message (not who we routed TO).
    speaker = userdata.speaking_agent or userdata.current_subject or "orchestrator"
```

### Step 2 — `agent/models/session_state.py`: Add `speaking_agent` field

```python
@dataclass
class SessionUserdata:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    student_identity: str = ""
    room_name: str = ""
    current_subject: Optional[str] = None
    speaking_agent: Optional[str] = None    # NEW — tracks who is currently speaking
    previous_subjects: list[str] = field(default_factory=list)
    turn_number: int = 0
    escalated: bool = False
    escalation_reason: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
```

### Step 3 — `agent/agents/base.py`: Set `speaking_agent` in `on_enter()`

At the very top of `on_enter()`, before the OTEL span and logging:
```python
# Update speaking_agent so transcript handler knows who is actively speaking.
# This fires AFTER the transition message ("Let me connect you with...") fires,
# so the transition message correctly shows the PREVIOUS speaker.
try:
    self.session.userdata.speaking_agent = self.agent_name
except AttributeError:
    pass
```

### Step 4 — `docker-compose.yml`: Add `agent-english` service

Add after the `agent:` service block:

```yaml
  agent-english:
    build:
      context: ./agent
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      AGENT_TYPE: english
      LIVEKIT_URL: ${LIVEKIT_URL:-ws://livekit:7880}
      LIVEKIT_API_KEY: ${LIVEKIT_API_KEY}
      LIVEKIT_API_SECRET: ${LIVEKIT_API_SECRET}
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      SUPABASE_URL: ${SUPABASE_URL:-http://supabase-kong:8000}
      SUPABASE_SERVICE_KEY: ${SUPABASE_SERVICE_KEY:-eyJ...}
      LANGFUSE_HOST: http://langfuse:3000
      LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY:-pk-lf-dev}
      LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY:-sk-lf-dev}
      OTEL_EXPORTER_OTLP_ENDPOINT: http://langfuse:3000/api/public/otel/v1/traces
    depends_on:
      livekit:
        condition: service_started
      langfuse:
        condition: service_healthy
      langfuse-worker:
        condition: service_started
      supabase-kong:
        condition: service_healthy
    networks:
      - internal
```

### Step 5 — `agent/tests/test_transcript_speaker.py` (2 new tests)

```python
class TestTranscriptSpeaker:
    def test_speaking_agent_set_by_on_enter():
        # Mock userdata with speaking_agent=None, call on_enter with agent_name="math"
        # verify userdata.speaking_agent == "math" after on_enter

    def test_speaker_uses_speaking_agent_not_current_subject():
        # userdata.speaking_agent = "orchestrator", userdata.current_subject = "math"
        # verify speaker = "orchestrator" (not "math")
        # This simulates the transition message scenario
```

---

## Timing Proof for Bug 2 Fix

```
Orchestrator routing to Math:
  1. _route_to_math_impl() called → userdata.route_to("math") → current_subject = "math"
  2. Returns (MathAgent, "Let me connect you with Math tutor!")
  3. conversation_item_added fires for transition message
     → speaking_agent = "orchestrator" (set by orchestrator's on_enter, not yet overwritten)
     → speaker = "orchestrator" ✅
  4. MathAgent.on_enter() fires → speaking_agent = "math"
  5. MathAgent generates reply → speaking_agent = "math" → speaker = "math" ✅

Math routing back to Orchestrator:
  1. _route_to_orchestrator_impl() called → route_to("orchestrator") → current_subject = "orchestrator"
  2. Returns (OrchestratorAgent, "Let me pass you back!")
  3. conversation_item_added fires for transition message
     → speaking_agent = "math" (set by math's on_enter, not yet overwritten)
     → speaker = "math" ✅
  4. OrchestratorAgent.on_enter() fires → speaking_agent = "orchestrator"
  5. Orchestrator greets student → speaking_agent = "orchestrator" → speaker = "orchestrator" ✅
```

---

## Net Test Count

| File | Before | Added | After |
|------|--------|-------|-------|
| `test_transcript_speaker.py` | 0 | 2 | 2 |
| All other test files | 63 | 0 | 63 |
| **Total** | **63** | **+2** | **65** |

---

## Critical Files

- `agent/main.py` — AGENT_TYPE branch (lines 346–356) + `on_conversation_item` speaker (line 162)
- `agent/models/session_state.py` — add `speaking_agent` field (after `current_subject` line 22)
- `agent/agents/base.py` — set `speaking_agent` at top of `on_enter()` (line 98)
- `docker-compose.yml` — add `agent-english` service after `agent:` block (~line 405)
- `agent/tests/test_transcript_speaker.py` (new file)

---

## Verification

```bash
# 1. Run all tests — target 65 passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild and bring up the full stack
docker compose down && docker compose up -d --build

# 3. Check both workers registered:
docker compose logs agent | grep "registered worker"
docker compose logs agent-english | grep "registered worker"
# Expected:
#   agent:         {"agent_name": "learning-orchestrator", ...}
#   agent-english: {"agent_name": "learning-english", ...}

# 4. Run a test session:
#    - Open http://localhost:3000
#    - Ask a maths question → speaker should be "math", not "orchestrator"
#    - Ask about English grammar → English session dispatches AND connects
#    - Check transcript sidebar: transition messages show correct speakers
#    - Check Langfuse http://localhost:3001: English session.start span appears

# 5. Speaker correctness check in Langfuse:
#    conversation.item spans with role="assistant" should have:
#    - subject_area="orchestrator" for greeting messages
#    - subject_area="math" for math answers
#    - subject_area="history" for history answers
```
