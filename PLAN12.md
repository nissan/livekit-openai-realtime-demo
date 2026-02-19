# Plan: Fix English Crash + Speech Cutoff (PLAN12)

## Context

After deploying PLAN11 (added `await` + increased pipeline close delay from 4s → 8s),
the same symptoms persist: silence after routing to English, and speech still cut off.

**Docker logs from agent-english at 12:04:25.663Z reveal the true root cause:**

```
TypeError: RealtimeModel.__init__() got an unexpected keyword argument 'instructions'
```

The English worker crashes **immediately** on every dispatch — before connecting to the
room, before generating a reply, before any Langfuse span is created. This is why:
- Zero English agent.activated events in Langfuse
- Student always hears silence after English routing
- No English Langfuse trace exists (crash happens before instrumentation)

The `instructions` bug predates PLAN11 — PLAN11's `await` fix was correct but irrelevant
because the crash occurred 4 lines before `generate_reply()` is ever reached.

**Secondary: speech cutoff persists**
Routing decision fires at T=0. TTS speech begins at T+1.464s and runs 7.545s (ending
at T+9.009s). Pipeline close timer fires at T+8s, cutting off approximately 1 second of
trailing audio that is still in-flight to the browser. This explains why the transcript
shows the full sentence but the student hears it truncated.

---

## Root Cause Analysis

### Bug 1 — `instructions` passed to wrong object

**In `agent/agents/english_agent.py` lines ~172–183:**

```python
session = AgentSession(
    userdata=session_userdata,
    llm=realtime.RealtimeModel(
        model=_REALTIME_MODEL,
        voice="shimmer",
        instructions=ENGLISH_SYSTEM_PROMPT,   # ← CRASH: RealtimeModel never accepted this
        modalities=["audio", "text"],
        input_audio_transcription=InputAudioTranscription(
            model="gpt-4o-mini-transcribe",
        ),
    ),
)
```

`RealtimeModel.__init__()` accepts: `model`, `voice`, `modalities`, `tool_choice`,
`input_audio_transcription`, `turn_detection`, `temperature`, etc. — **no `instructions`**.

Instructions are correctly set at the `Agent` level. `EnglishAgent.__init__()` already
passes `instructions=ENGLISH_SYSTEM_PROMPT` to `super().__init__()` (Agent base class).
The Agent's `instructions` property is then forwarded to `RealtimeSession` via
`update_instructions()` when the session starts. **The fix is to simply remove the
`instructions` kwarg from `RealtimeModel()`.**

### Bug 2 — Pipeline close timer too short

**In `agent/tools/routing.py` line 187:**

```python
await asyncio.sleep(8.0)
```

Confirmed timing from trace `fd92b85b` (session `34890971`):
- Routing decision: 12:04:25.379Z
- TTS speech starts: 12:04:26.843Z (T+1.464s)
- TTS speech ends: 12:04:33.388Z (T+9.009s)
- Pipeline closes: 12:04:25.379Z + 8s = 12:04:33.379Z (T+8.000s)
- **Audio in-flight cut off: ~1 second**

Increasing to 12s gives the transition message a safe 12s window from the routing
decision, covering the ~1.5s before TTS starts and the ~7.5s of audio.

---

## Files Modified

| File | Change |
|------|--------|
| `agent/agents/english_agent.py` | Removed `instructions=ENGLISH_SYSTEM_PROMPT` from `RealtimeModel()` |
| `agent/tools/routing.py` | `asyncio.sleep(8.0)` → `asyncio.sleep(12.0)` |

---

## Changes Applied

### Fix 1 — `agent/agents/english_agent.py`: Remove `instructions` from RealtimeModel

```python
# BEFORE (crashes every time):
llm=realtime.RealtimeModel(
    model=_REALTIME_MODEL,
    voice="shimmer",
    instructions=ENGLISH_SYSTEM_PROMPT,      # ← removed this line
    modalities=["audio", "text"],
    input_audio_transcription=InputAudioTranscription(
        model="gpt-4o-mini-transcribe",
    ),
),

# AFTER (instructions flow via EnglishAgent.__init__ → Agent.__init__):
llm=realtime.RealtimeModel(
    model=_REALTIME_MODEL,
    voice="shimmer",
    modalities=["audio", "text"],
    input_audio_transcription=InputAudioTranscription(
        model="gpt-4o-mini-transcribe",
    ),
),
```

Note: `EnglishAgent.__init__()` already calls `super().__init__(instructions=ENGLISH_SYSTEM_PROMPT)`.
The Agent base class stores `self._instructions` and forwards it to `RealtimeSession`
via `update_instructions()` when the session starts. No other changes needed.

### Fix 2 — `agent/tools/routing.py`: Increase pipeline close delay

```python
# BEFORE:
await asyncio.sleep(8.0)
# AFTER:
await asyncio.sleep(12.0)
```

---

## Verification

```bash
# 1. Run tests — 72 still passing
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 2. Rebuild and restart
docker compose up -d --build agent agent-english

# 3. Test session:
#    - Ask a maths question → math answers ✓
#    - Ask "what is a pronoun?" → orchestrator routes to English ✓
#    - English tutor SPEAKS (crash is fixed) ← key fix
#    - Transition message plays fully (12s window) ← no more cutoff

# 4. Check agent-english logs — no TypeError crash:
docker logs livekit-openai-realtime-demo-agent-english-1 --since "10m"
```

---

## Why Previous PLAN11 Didn't Fix This

PLAN11 added `await` to `session.generate_reply()` (line 274) and increased the
English greet delay from 1.5s to 3.0s. Both changes are correct and still needed.
But the crash at line 174 (`RealtimeModel(instructions=...)`) occurs **before** the
code ever reaches line 274. The `await` fix never executes because the session is
never created successfully.

---

## Outcome

- `agent-english` starts cleanly — registered with LiveKit with no `TypeError`
- 72/72 tests pass
- Git commit: `fix(agent): fix English crash + speech cutoff (PLAN12)`
