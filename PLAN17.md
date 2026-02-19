# Plan: Automated Testing Strategy + OTEL Latency Instrumentation (PLAN17)

## Context

PLAN16 is complete. We now have 72 pytest unit tests and 66 Playwright E2E tests — all
passing. However, all existing tests are **structural/unit-level**: routing logic, OTEL
span shapes, session state dataclass, UI navigation. There are **zero integration or
session-level tests** that simulate actual student conversations, multi-agent handoffs, or
voice pipeline timing. Bugs like the "two voices" overlap and "phantom You" transcript
entries went undetected because they require a full agent session to reproduce.

Two objectives for PLAN17:
1. **Automated testing**: Test agent behaviour (routing, transcript, guardrail, handoffs) without a real microphone
2. **OTEL latency instrumentation**: Add spans so we can see *where time is spent* in the voice response pipeline (latency in voice is critical UX)

---

## Current Test Coverage Map

| Layer | What's Tested | What's Missing |
|---|---|---|
| Unit (pytest) | SessionUserdata, routing spans, guardrail API calls, transcript text_content, speaker attribution, OTEL span shapes | English Realtime session, skip_next_user_turns in live flow, pipeline close timing |
| E2E (Playwright) | UI pages, token API, error boundary | Agent sessions, handoffs, transcript rendering, audio |
| Integration | **Nothing** | STT→LLM→TTS pipeline, multi-agent handoffs, two-session coordination |
| Evaluation | **Nothing** | Routing correctness, subject detection accuracy, guardrail trigger rate |
| Latency | **Nothing** | STT latency, LLM first token, TTS first frame, guardrail check duration |

---

## Three Proposals

---

### Proposal A — LiveKit Native Session Testing (`session.run()`)

**Mechanism**: LiveKit agents v1.4+ provides `session.run(user_input="text")` which injects a
text message directly into the conversation, completely bypassing STT. The `AgentSession`
runs the full LLM → routing → TTS pipeline in-process. No microphone, no WebRTC, no Docker needed.

**What it can test**:
- Orchestrator routes "What is 25% of 80?" → MathAgent (assert `is_agent_handoff`)
- MathAgent routes "Who was Napoleon?" → back to Orchestrator → HistoryAgent
- `skip_next_user_turns` counter suppresses phantom user turn after handoff
- Guardrail triggers on inappropriate content → rewrite fires
- English dispatch fires the correct `CreateAgentDispatchRequest` (existing mock pattern)
- `conversation_item_added` emits with populated `text_content` for all agents
- Multi-turn conversation: history accumulates across 3+ `session.run()` calls
- Speaker attribution: assistant turns labelled with correct `speaking_agent`

**New test file**: `agent/tests/test_session_integration.py`

```python
@pytest.mark.asyncio
async def test_orchestrator_routes_math_question():
    async with AgentSession(llm=mock_llm, stt=None, tts=None, vad=None) as session:
        await session.start(OrchestratorAgent(), room=mock_room)
        result = await session.run(user_input="What is the quadratic formula?")
        result.expect.next_event().is_agent_handoff(new_agent_type=MathAgent)

@pytest.mark.asyncio
async def test_skip_next_user_turns_suppresses_phantom_entry():
    # After routing, generate_reply(user_input=pending_q) fires;
    # skip_next_user_turns=1 must suppress it from the transcript
    ...

@pytest.mark.asyncio
async def test_multiturn_context_preserved_through_handoff():
    ...
```

**Where mocks come from**: Uses existing patterns from `test_agent_handoffs.py` — mock
`RunContext`, mock `AgentSession`, mock LLM. The `conftest.py` already patches all API keys.

**Pros**: Fast (seconds), zero infrastructure, runs in CI, catches regression bugs before
they reach live testing. Most bugs from PLAN1–16 would have been caught here.

**Cons**: Does NOT test: actual STT accuracy, TTS audio quality, WebRTC timing, real network
latency, two-session coordination in a live room, OpenAI Realtime model behaviour.

**Effort**: Medium — 2–3 days. ~15–20 new test cases.

---

### Proposal B — Langfuse Trace Evaluation (LLM-as-Judge)

**Mechanism**: A Python script (`scripts/evaluate_traces.py`) queries the Langfuse REST API
for recent traces, then uses an LLM judge (GPT-4o or Claude Sonnet) to score each trace
against defined rubrics. Scores are written back to Langfuse via the Scores API, visible
in the dashboard.

**Evaluation targets** (using existing OTEL span attributes):

| Rubric | Source Span | Score Type |
|---|---|---|
| Routing correctness: did the agent pick the right specialist? | `routing.decision` → `to_agent` vs `question_summary` | Boolean |
| Transcript completeness: did all turns get published? | `conversation.item` count vs `turn_number` | Numeric |
| Guardrail trigger rate: are inappropriate inputs being caught? | `teacher.escalation` + `conversation.item` content | Numeric |
| Subject detection accuracy: correct subject for question? | `routing.decision.question_summary` + `to_agent` | Categorical |
| English handoff timing: did pipeline close before English started? | `routing.decision` + session.end timing | Boolean |
| Session coherence: did conversation make sense end-to-end? | all `conversation.item` turns in sequence | Boolean |

**Script structure** (`scripts/evaluate_traces.py`):
```python
from langfuse import Langfuse
from openai import AsyncOpenAI

lf = Langfuse(public_key="pk-lf-dev", secret_key="sk-lf-dev", host="http://localhost:3000")
llm = AsyncOpenAI()

# Get last 50 sessions
sessions = lf.get_sessions(limit=50)
for session in sessions:
    traces = lf.get_traces(session_id=session.id)
    routing_spans = [t for t in traces if t.name == "routing.decision"]
    for span in routing_spans:
        score = judge_routing_correctness(span.input["question_summary"], span.output["to_agent"])
        lf.score(trace_id=span.trace_id, name="routing_correctness", value=score)
```

**Integration with CI**: Can run as a nightly job after real sessions have been collected.
Not a blocking CI gate (requires live sessions to exist first).

**Pros**: Evaluates real production behaviour, no code changes to agents, can score
historical sessions retroactively, builds a quality baseline over time.

**Cons**: Requires live sessions to exist first (not a green-field gate), adds LLM
API cost per evaluation run, scores are probabilistic (judge varies), latency — not
real-time.

**Effort**: Medium — 1–2 days for evaluation script + Langfuse dashboard setup. Ongoing
cost per run (~$0.01–$0.05 per session).

---

### Proposal C — Audio Injection Integration Tests (Full Pipeline)

**Mechanism**: Pre-recorded WAV files of common student phrases are injected directly into
a LiveKit room via `rtc.AudioSource` + `LocalAudioTrack`. A test harness starts a real
`AgentSession` connected to a local LiveKit server (via `livekit.yaml`), pushes the audio
frames, and asserts on the resulting `conversation_item_added` events and transcript data
channel messages.

```python
# Pseudocode — requires live LiveKit server
audio_source = rtc.AudioSource(sample_rate=16000, num_channels=1)
track = rtc.LocalAudioTrack.create_audio_track("test-student", audio_source)
# ... publish to room ...
with open("fixtures/what_is_adjective.wav", "rb") as f:
    frame = rtc.AudioFrame(data=f.read(), sample_rate=16000, ...)
    await audio_source.capture_frame(frame)
# Assert transcript data received
```

**Audio fixtures needed**: 5–10 pre-recorded WAV files covering key routing scenarios:
- "What is the quadratic formula?" → math
- "Who was George Washington?" → history
- "What is an adjective?" → english
- "I want to hurt myself" → escalation
- "Tell me about the weather" → off-topic guardrail

**Pros**: Tests real STT accuracy and audio pipeline end-to-end. Catches timing bugs that
`session.run()` cannot (e.g., VAD endpointing too short, TTS latency too high). Closest
to real user experience.

**Cons**: Requires running LiveKit server (Docker), significant setup overhead, slow
(each test takes 5–30s depending on LLM latency), flaky due to network/API variance,
needs real OpenAI API keys (cost per run ~$0.05–0.20 per test). Not suitable as a
blocking CI gate. Overkill for regression testing.

**Effort**: High — 3–5 days + ongoing maintenance. Recommended only for critical path
scenarios (escalation, English handoff timing).

---

## Recommended Approach: A + B (Layered)

**Phase 1 (Week 1)**: Implement Proposal A — `session.run()` tests
- Covers all bugs from PLAN1–16 as regression tests
- Runs in CI on every push, ~30 seconds
- No infrastructure required

**Phase 2 (Week 2)**: Implement Proposal B — Langfuse trace evaluation script
- Runs nightly against real session data
- Scores routing correctness, transcript completeness, safety events
- Builds quality baseline in Langfuse dashboard

**Defer Proposal C**: Reserve audio injection for targeted testing of the English handoff
timing scenario (hardcoded 3.5s/3.0s constants) if timing regressions appear in production.

---

## OTEL Latency Instrumentation (New Requirement)

Currently **zero latency spans** exist. These hardcoded constants reveal the gap:
- `routing.py:196` — `asyncio.sleep(3.5)` (orchestrator transition window) — not measured
- `english_agent.py:279` — `asyncio.sleep(3.0)` (WebRTC setup wait) — not measured
- `main.py:157` — `min_endpointing_delay=0.4`, `max_endpointing_delay=2.0` — config only

### New Spans to Add

#### 1. Guardrail latency — `agent/services/guardrail.py`

Wrap `check()` and `rewrite()` in OTEL spans:
```python
# check() — line 76
with tracer.start_as_current_span("guardrail.check") as span:
    span.set_attribute("text_length", len(text))
    result = await openai_client.moderations.create(...)
    span.set_attribute("flagged", result.flagged)
    span.set_attribute("highest_score", result.highest_score)

# rewrite() — line 129
with tracer.start_as_current_span("guardrail.rewrite") as span:
    span.set_attribute("original_length", len(text))
    rewritten = await anthropic_client.messages.create(...)
    span.set_attribute("rewritten_length", len(rewritten))
```

This makes guardrail latency visible in Langfuse: ~5ms (clean) vs ~150ms (rewrite).

#### 2. TTS sentence pipeline latency — `agent/agents/base.py` (GuardedAgent.tts_node)

Record sentence-level timing:
```python
# In tts_node, per sentence:
t_sentence_start = time.perf_counter()
safe_text = await guardrail_service.check_and_rewrite(sentence, ...)
t_guardrail_done = time.perf_counter()

with tracer.start_as_current_span("tts.sentence") as span:
    span.set_attribute("guardrail_ms", round((t_guardrail_done - t_sentence_start) * 1000))
    span.set_attribute("sentence_length", len(sentence))
    span.set_attribute("was_rewritten", safe_text != sentence)
    async for frame in Agent.default.tts_node(self, iter([safe_text]), model_settings):
        yield frame
    span.set_attribute("tts_ms", round((time.perf_counter() - t_guardrail_done) * 1000))
```

#### 3. Routing decision latency — `agent/tools/routing.py`

Add `decision_ms` to existing `routing.decision` span:
```python
t0 = time.perf_counter()
# ... existing routing logic ...
span.set_attribute("decision_ms", round((time.perf_counter() - t0) * 1000))
```

#### 4. English dispatch-to-audio latency — `agent/tools/routing.py` + `agent/agents/english_agent.py`

- In `_route_to_english_impl`: record `dispatch_at = time.time()` in dispatch metadata or OTEL
- In `english_agent.py`: on first `conversation_item_added` (assistant role), compute `time.time() - dispatch_at`
- Emit `english.startup_ms` attribute on the first `conversation.item` span

#### 5. Conversation turn end-to-end latency — `agent/main.py`

Track time from user speech committed to first assistant audio frame:
```python
@session.on("user_input_transcribed")
def on_user_transcribed(event):
    userdata.last_user_input_at = time.perf_counter()

# In on_conversation_item, for role=="assistant":
if userdata.last_user_input_at:
    e2e_ms = round((time.perf_counter() - userdata.last_user_input_at) * 1000)
    span.set_attribute("e2e_response_ms", e2e_ms)
    userdata.last_user_input_at = None
```

Add `last_user_input_at: Optional[float] = None` to `SessionUserdata`.

#### 6. Pipeline close timing verification — `agent/tools/routing.py`

Replace the hardcoded 3.5s constant with a measured span:
```python
t_dispatch = time.perf_counter()
# ... dispatch request ...
await asyncio.sleep(3.5)
span.set_attribute("actual_close_delay_ms", round((time.perf_counter() - t_dispatch) * 1000))
```

---

## Files to Modify

### Testing (Proposal A)
| File | Change |
|---|---|
| `agent/tests/test_session_integration.py` | **New file** — 15–20 session.run() tests |
| `agent/tests/conftest.py` | Add `mock_room`, `mock_llm` fixtures |

### Evaluation (Proposal B)
| File | Change |
|---|---|
| `scripts/evaluate_traces.py` | **New file** — Langfuse REST API query + LLM judge scoring |
| `scripts/README.md` | **New file** — how to run evaluations |

### OTEL Latency Instrumentation
| File | Change |
|---|---|
| `agent/services/guardrail.py` | Add `guardrail.check` + `guardrail.rewrite` spans (lines 76, 129) |
| `agent/agents/base.py` | Add `tts.sentence` span with guardrail_ms + tts_ms (lines 49–98) |
| `agent/tools/routing.py` | Add `decision_ms` to `routing.decision` span (lines 69, 109, 146, 254) |
| `agent/agents/english_agent.py` | Add `english.startup_ms` on first assistant item (line 203) |
| `agent/main.py` | Add `e2e_response_ms` via `user_input_transcribed` event (lines 163–212) |
| `agent/models/session_state.py` | Add `last_user_input_at: Optional[float] = None` |

---

## New Test Cases for Known PLAN Issues (Proposal A Regression Suite)

| Test | Covers Bug From |
|---|---|
| Routing phantom "You" suppressed by skip_next_user_turns | PLAN16 Fix C |
| Pipeline closes before English speaks (3.5s timer) | PLAN16 Fix A |
| on_enter() calls generate_reply() | PLAN6 |
| Specialists have routing tools | PLAN6 |
| conversation_item_added fires with populated text_content | PLAN15 |
| speaking_agent set by on_enter not by routing function | PLAN9/10 |
| CreateAgentDispatchRequest proto object (not kwargs) | PLAN6 |
| Guardrail rewrite fires on flagged content | PLAN1 |
| History accumulates across handoffs | PLAN7 |
| English session uses separate AgentSession | PLAN8 |

---

## Verification

```bash
# 1. Run new session integration tests (Proposal A)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_session_integration.py -v

# 2. Run full pytest suite — all 72 + new tests must pass
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# 3. Run evaluation script against local Langfuse (Proposal B)
PYTHONPATH=$(pwd) uv run --directory agent python scripts/evaluate_traces.py

# 4. Verify new OTEL spans appear in Langfuse:
#    - Open http://localhost:3000 → Traces
#    - Filter by service.name = "learning-voice-agent"
#    - Expand any conversation trace — should see:
#      guardrail.check (with flagged + highest_score attrs)
#      tts.sentence (with guardrail_ms + tts_ms attrs)
#      routing.decision (with decision_ms attr)
#      conversation.item for assistant (with e2e_response_ms attr)

# 5. Langfuse latency dashboard:
#    - Create dashboard with metric: p50/p95 of e2e_response_ms
#    - Target: p50 < 1500ms, p95 < 3500ms
#    - Alert if guardrail.rewrite fires (indicates flagged content in session)
```

---

## Key Files (Reference)

- `agent/tests/test_agent_handoffs.py` — existing mock patterns to reuse
- `agent/tests/conftest.py` — API key mocks (extend for session fixtures)
- `agent/services/langfuse_setup.py` — OTEL exporter config
- `agent/services/guardrail.py` — check() line 76, rewrite() line 129
- `agent/agents/base.py` — tts_node() lines 49–98, on_enter() lines 100–151
- `agent/tools/routing.py` — routing.decision spans lines 69, 109, 146, 254
- `agent/main.py` — on_conversation_item lines 163–212
- `agent/models/session_state.py` — SessionUserdata (add last_user_input_at)
