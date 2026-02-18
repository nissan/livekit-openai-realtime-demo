# Plan: Student-Assisted Learning Voice Agent App

## Context
Build a greenfield voice agent web app for student tutoring. Students speak and get routed to a subject-specialist AI — English questions go to an OpenAI Realtime agent, Mathematics to a Claude agent — with an orchestrator (Claude Haiku) making routing decisions. If the orchestrator lacks confidence, it invites a human teacher into the live session. All conversations are logged for audit and future improvement. The app must be globally accessible, so LiveKit handles WebRTC infrastructure and room management. Langfuse provides observability. Everything is Dockerised for developer portability.

The project directory is currently empty (only a `.claude/settings.local.json` with Supabase and shadcn MCP configs). This is a full greenfield implementation.

---

## Tech Stack
| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, `@livekit/components-react`, Tailwind CSS |
| Agent Worker | Python 3.11, `livekit-agents~=1.4` (current: v1.4.2), Anthropic + OpenAI plugins |
| Orchestrator LLM | Claude Haiku (fast routing/classification) |
| English Agent | OpenAI Realtime API (`gpt-realtime` GA model, released Aug 2025) — native speech-to-speech |
| Math Agent | Claude Sonnet 3.5 + OpenAI TTS pipeline |
| History Agent | GPT-5.2 (`gpt-5.2`) + STT transcript input + OpenAI TTS pipeline |
| Guardrail Layer | OpenAI `omni-moderation-latest` + Claude Haiku rewriter (shared `tts_node` base class) |
| Token Service | Next.js API Routes (no separate FastAPI service needed) |
| Transcripts/DB | Supabase (already MCP-configured) |
| Observability | Langfuse v3 (self-hosted in Docker) |
| WebRTC Infra | LiveKit (self-hosted for dev, LiveKit Cloud for prod) |
| Containerisation | Docker + docker-compose |

---

## Project Structure
```
livekit-openai-realtime-demo/      ← existing directory
├── docker-compose.yml
├── docker-compose.override.yml    ← dev hot-reload volume mounts
├── livekit.yaml                   ← self-hosted LiveKit config
├── .env.example
├── .env                           ← gitignored
│
├── frontend/                      ← Next.js app
│   ├── Dockerfile
│   ├── next.config.ts             ← output: "standalone" for Docker
│   ├── app/
│   │   ├── page.tsx               ← role selector (student / teacher)
│   │   ├── student/page.tsx
│   │   ├── teacher/page.tsx       ← escalation monitoring view
│   │   └── api/token/route.ts     ← LiveKit JWT generation
│   ├── components/
│   │   ├── StudentRoom.tsx        ← LiveKitRoom + VoiceAssistantControlBar
│   │   ├── TeacherRoom.tsx
│   │   ├── AgentStateIndicator.tsx
│   │   ├── TranscriptPanel.tsx
│   │   ├── SubjectBadge.tsx       ← shows current routing: Math / English
│   │   └── EscalationBanner.tsx
│   └── hooks/
│       ├── useAgentState.ts       ← wraps useVoiceAssistant
│       └── useTranscript.ts       ← data channel transcript subscriber
│
├── agent/                         ← Python LiveKit Agents worker
│   ├── Dockerfile
│   ├── pyproject.toml             ← uv-managed deps
│   ├── main.py                    ← worker entrypoint + AgentSession config
│   ├── agents/
│   │   ├── base.py                ← GuardedAgent base class (shared tts_node guardrail)
│   │   ├── orchestrator.py        ← OrchestratorAgent (Claude Haiku, @function_tool routing)
│   │   ├── english_agent.py       ← EnglishAgent (OpenAI Realtime RealtimeModel)
│   │   ├── math_agent.py          ← MathAgent (Claude Sonnet llm override + pipeline TTS)
│   │   └── history_agent.py       ← HistoryAgent (GPT-5.2 text LLM + pipeline TTS)
│   ├── services/
│   │   ├── transcript_store.py    ← Supabase async writes
│   │   ├── human_escalation.py    ← generates teacher token + Supabase escalation record
│   │   ├── guardrail.py           ← OpenAI Moderation + Claude Haiku rewriter
│   │   └── langfuse_setup.py      ← OTEL → Langfuse HTTP/protobuf config
│   └── models/
│       └── session_state.py       ← SessionUserdata dataclass (shared across handoffs)
│
└── db/
    └── migrations/
        └── 001_create_transcripts.sql
```

---

## Docker Services (docker-compose.yml)
| Service | Image | Ports | Purpose |
|---|---|---|---|
| `livekit` | `livekit/livekit-server:v1.9.11` (pinned — `:latest` is unstable) | 7880, 7881, 50000-50200/udp | WebRTC infra |
| `redis` | `redis:7-alpine` | internal | LiveKit dependency |
| `langfuse-db` | `postgres:16-alpine` | internal | Langfuse persistence |
| `langfuse` | `langfuse/langfuse:3` | 3001→3000 | Observability UI |
| `agent` | `./agent/Dockerfile` | internal | Python voice agent worker |
| `frontend` | `./frontend/Dockerfile` | 3000 | Next.js web app |

`docker-compose.override.yml` adds volume mounts for hot-reload of both `agent/` and `frontend/` during development.

For production: remove `livekit` + `redis` services, set `LIVEKIT_URL` to LiveKit Cloud endpoint.

---

## Agent Architecture

### Session Lifecycle (`agent/main.py`)
1. Student joins room → Next.js token route dispatches `learning-orchestrator` agent via `RoomConfiguration` + `RoomAgentDispatch` (see Key API Patterns)
2. Worker connects, creates `SessionUserdata` (session_id UUID, student_identity, room_name)
3. Supabase: `create_session_record()` called immediately
4. `AgentSession` configured with: `stt=openai.STT(model="gpt-4o-transcribe")`, `tts=openai.TTS(model="gpt-4o-mini-tts", voice="ash")`, `vad=await silero.VAD.load()` ← **must be awaited**
5. First agent: `OrchestratorAgent()`
6. `session.on("conversation_item_added")` → publish to room data channel (topic: `"transcript"`)
7. On shutdown: save session report to Supabase (verify exact method name against `JobContext` source — `make_session_report()` exists but not fully documented; use `session.history` as fallback)

### Guardrail Layer (`agent/agents/base.py` + `agent/services/guardrail.py`)
All subject agents (English, Math, History) inherit from `GuardedAgent` instead of `Agent` directly. This base class overrides `tts_node` — the LiveKit v1.x hook that intercepts streaming LLM text before TTS synthesis.

**`tts_node` safety pipeline (runs on every agent response):**
1. Accumulate streamed text chunks into a sentence buffer
2. On each complete sentence: call `guardrail.check(text)` (OpenAI `omni-moderation-latest`)
3. If `flagged=False`: yield text directly to TTS
4. If `flagged=True`: call `guardrail.rewrite(text)` — Claude Haiku rewrites to age-appropriate equivalent
5. Yield rewritten text to TTS; log the event (session_id, original, rewritten, categories_flagged)

**Moderation categories checked** (via `omni-moderation-latest`):
`harassment`, `harassment/threatening`, `hate`, `hate/threatening`, `sexual`, `sexual/minors`, `violence`, `violence/graphic`, `self-harm/*`, `illicit`, `illicit/violent`

**Additional age-appropriateness rewrite instruction** (beyond moderation API):
Claude Haiku rewriter is always prompted with: *"Rewrite this for primary/secondary school children aged 8–16. Use simple vocabulary. Do not mention the original issue."*

**Note on English agent (OpenAI Realtime):** Realtime API processes audio-to-audio natively. The `tts_node` hook does not apply to `RealtimeModel` sessions. Guardrail for English agent is applied via a `on_agent_message` session callback that can interrupt playback and trigger a safe regeneration if content is flagged post-hoc. This is an accepted trade-off given the native speech-to-speech latency benefit.

**`agent/services/guardrail.py` key functions:**
```python
async def check(text: str) -> ModerationResult   # OpenAI omni-moderation-latest
async def rewrite(text: str) -> str               # Claude Haiku safe rewrite
async def log_guardrail_event(session_id, original, rewritten, categories)  # Supabase
```

### Orchestrator → Routing (`agent/agents/orchestrator.py`)
- Model: Claude Haiku (fast + cheap classification)
- Three `@function_tool` routing methods: `route_to_english`, `route_to_math`, `route_to_history`
- Each returns `tuple[Agent, str]` — new agent instance + transfer announcement
- Fourth tool: `escalate_to_teacher(reason)` — generates teacher JWT, stores in Supabase, returns spoken message
- Orchestrator itself inherits `GuardedAgent` so its own responses (greetings, transitions) are also checked
- Context preserved via `chat_ctx=context.session.chat_ctx` passed to new agent constructor
- `session.userdata` mutated to track `current_subject` and routing history

### English Agent (`agent/agents/english_agent.py`)
- Inherits from `GuardedAgent`; `tts_node` guardrail does not apply (Realtime API, see above)
- Model: `openai.realtime.RealtimeModel(model="gpt-realtime")` — updated GA model (was `gpt-4o-realtime-preview`, superseded Aug 2025; 20% cheaper)
- Expected latency: ~230–290ms TTFB

**⚠️ Critical architectural constraint**: `RealtimeModel` replaces the entire audio pipeline — it cannot be mixed with traditional STT+LLM+TTS pipeline agents within a single `AgentSession`. The session must commit to one audio paradigm at configuration time.

**Resolution — Two-session architecture for the English agent:**
The English agent runs in its own `AgentSession` configured with `llm=RealtimeModel(...)`, while the Orchestrator/Math/History agents share a separate pipeline `AgentSession`. Both sessions operate in the **same LiveKit room**:
- **Pipeline session** (`learning-orchestrator` worker): Orchestrator, Math, History agents
- **Realtime session** (`learning-english` worker): English agent, dispatched on demand

When the Orchestrator routes to English, it dispatches the `learning-english` worker to the same room (via LiveKit server API) and the pipeline session's agent goes silent. When routing back, the English agent dispatches a return to the orchestrator worker and exits. Context is passed as room metadata or via Supabase.

**Fallback (simpler):** If two-session coordination proves complex during implementation, degrade English agent to use `openai.LLM(model="gpt-4o")` in the pipeline session. Latency increases ~500ms but architecture is unified. Document as a known simplification.

### Math Agent (`agent/agents/math_agent.py`)
- Inherits from `GuardedAgent`; `tts_node` guardrail fully active
- Overrides LLM: `llm=anthropic.LLM(model="claude-3-5-sonnet-20241022", temperature=0.3)`

**Data flow (same pattern as History agent):**
```
Student speaks → STT → Claude Sonnet (text) → [GuardedAgent.tts_node GUARDRAIL] → TTS → audio
```
- Expected latency: ~900–1200ms (Claude Sonnet reasoning) + ~50–200ms guardrail overhead per sentence

### History Agent (`agent/agents/history_agent.py`)
- Inherits from `GuardedAgent`; `tts_node` guardrail fully active
- Overrides LLM: `llm=openai.LLM(model=os.environ.get("OPENAI_HISTORY_MODEL", "gpt-5.2"))`
- **Model ID note**: `gpt-5.2` is the correct OpenAI model ID as of early 2026. Configured via env var so it updates without code change.

**Explicit data flow for History Agent (every turn):**
```
Student speaks
    ↓
[LiveKit VAD] — detects end of turn
    ↓
[STT: openai.STT(model="gpt-4o-transcribe")] — speech → text transcript
    ↓
[GPT-5.2 LLM] — text in, text response streamed out
    ↓
[GuardedAgent.tts_node — GUARDRAIL CHECKPOINT]
    ├─ Buffer streamed text at sentence boundaries
    ├─ Call guardrail.check(sentence) → OpenAI omni-moderation-latest
    │      ├─ NOT flagged → yield sentence directly
    │      └─ FLAGGED → call guardrail.rewrite(sentence) → Claude Haiku
    │                       → yield age-appropriate rewrite
    │                       → log to Supabase guardrail_events
    ↓
[TTS: openai.TTS(model="gpt-4o-mini-tts", voice="ash")] — safe text → audio
    ↓
Student hears response
```

- Guardrail runs **between GPT-5.2 output and TTS input** — no unsafe text ever reaches synthesis
- Specialised instructions for history tutoring: factual, balanced, age-appropriate historical narratives; avoids glorifying violence or presenting disputed history one-sidedly
- Expected latency breakdown: STT ~150ms + GPT-5.2 TTFB ~300ms + guardrail ~50–200ms/sentence + TTS ~100ms = **~600–750ms to first audio**

### Human Escalation (`agent/services/human_escalation.py`)
1. `OrchestratorAgent.escalate_to_teacher()` fires
2. Generates teacher LiveKit JWT (`roomAdmin=True`) for the existing room
3. Stores token + reason in `escalation_events` table (Supabase Realtime broadcasts to teacher portal)
4. Teacher's browser shows notification → clicks "Join Session" → uses pre-signed token
5. Teacher joins as a full audio participant in the existing room
6. `EscalationBanner` on student UI updates via LiveKit participant events

---

## Key API Patterns

### LiveKit Token (Next.js API Route)
```typescript
// frontend/app/api/token/route.ts
// livekit-server-sdk v2.15.0 — toJwt() is NOW ASYNC (breaking change from v1)
import { AccessToken } from "livekit-server-sdk";
import { RoomAgentDispatch, RoomConfiguration } from "@livekit/protocol";

const token = new AccessToken(apiKey, apiSecret, { identity, name, ttl: "2h" });
token.addGrant({ roomJoin: true, room: roomName, canPublish: true, canSubscribe: true, roomAdmin: role === "teacher" });

// Student tokens trigger pipeline agent dispatch via typed classes (v2 pattern):
if (role === "student") {
  token.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: "learning-orchestrator" })]
  });
}

const jwt = await token.toJwt(); // ← MUST be awaited (changed in server-sdk v2)
```

**Frontend packages required:**
```
@livekit/components-react@^2.9.19
@livekit/components-styles          ← required peer dep, must install alongside components-react
@livekit/protocol                   ← for RoomConfiguration + RoomAgentDispatch types
livekit-server-sdk@^2.15.0
livekit-client
```

**`useVoiceAssistant` must be inside `AgentSessionProvider`:**
```tsx
// StudentRoom.tsx — wrap inner components with AgentSessionProvider
<AgentSessionProvider>
  <StudentRoomInner />
</AgentSessionProvider>
```
`AgentState` valid values: `"initializing" | "listening" | "thinking" | "speaking"`

### Agent Handoff Pattern (LiveKit Agents v1.4)
```python
# In orchestrator @function_tool — tuple return still valid in v1.4:
return (MathAgent(chat_ctx=context.session.chat_ctx), "Transferring to Math specialist")
return (HistoryAgent(chat_ctx=context.session.chat_ctx), "Transferring to History specialist")
# Note: chat_ctx parameter preserves history; no "inherit_context" param (removed in v1.0)

# For English agent (separate realtime session): dispatch via LiveKit server API, not tuple return
# Use livekit.api.AgentDispatchClient to dispatch "learning-english" worker to the room
```

### Transcript Event (v1.4 — `agent_speech_committed` removed)
```python
# "agent_speech_committed" was REMOVED in v1.0.
# Use conversation_item_added and filter for assistant role:
@session.on("conversation_item_added")
def on_item(item):
    if item.role == "assistant":
        # agent turn — publish to room data channel
        pass
    elif item.role == "user":
        # student turn
        pass
```

### GuardedAgent Base Class Pattern (LiveKit v1.4 `tts_node`)
```python
# agent/agents/base.py
class GuardedAgent(Agent):
    async def tts_node(
        self, text_stream: AsyncIterable[str], model_settings
    ) -> AsyncIterable[str]:
        buffer = ""
        session_id = self.session.userdata.session_id

        async for chunk in text_stream:
            buffer += chunk
            if any(buffer.rstrip().endswith(p) for p in (".", "!", "?", ":", ";")):
                safe_text = await guardrail.check_and_rewrite(
                    buffer, session_id=session_id
                )
                yield safe_text
                buffer = ""

        if buffer.strip():
            safe_text = await guardrail.check_and_rewrite(
                buffer, session_id=session_id
            )
            yield safe_text
```

---

## Database Schema (Supabase)
Five tables in `db/migrations/001_create_transcripts.sql`:
- `learning_sessions` — one row per session (session_id, room_name, student_identity, ended_at, session_report JSONB)
- `transcript_turns` — each STT/LLM turn (session_id, turn_number, speaker, role, content, subject_area)
- `routing_decisions` — agent handoff log (from_agent, to_agent, question_summary)
- `escalation_events` — teacher invite tokens (teacher_token JWT, reason, timestamps)
- `guardrail_events` — audit log of every flagged response (session_id, original_text, rewritten_text, categories_flagged[], agent_name, timestamp)

All tables have RLS enabled. Agent worker uses `SUPABASE_SERVICE_KEY`. Frontend uses `SUPABASE_ANON_KEY`.

---

## Observability (Langfuse)
**Auto-traced (Anthropic OTEL instrumentation):**
- Orchestrator Claude Haiku calls (routing decisions, tool arguments)
- Math agent Claude Sonnet calls (full token/latency/cost)
- Guardrail rewriter Claude Haiku calls (when content is flagged and rewritten)

**Auto-traced (OpenAI OTEL instrumentation):**
- History agent GPT-5.2 calls (token counts, latency, cost)
- Guardrail moderation API calls (`omni-moderation-latest`)

**Custom OTEL spans needed:**
- `routing.decision` — span per handoff with session_id, from/to agent, turn number
- `openai.realtime.response` — manual span wrapping Realtime audio events
- `guardrail.check` — span per sentence checked, with `flagged` boolean and categories

**Key Langfuse dashboards to build:**
- Average routing latency per agent type
- Escalation rate (% sessions escalated to teacher)
- Subject distribution (Math / English / History)
- Guardrail trigger rate (% responses flagged, per agent)
- Turn counts per session

---

## Latency Strategy
| Decision | Rationale |
|---|---|
| Claude Haiku for orchestrator | 2x faster than Sonnet; routing is classification not reasoning |
| OpenAI Realtime (`gpt-realtime`) for English | Native speech-to-speech; runs in separate session due to pipeline incompatibility; ~230–290ms TTFB |
| Claude Sonnet for Math | Quality over speed; students expect careful step-by-step explanations |
| GPT-5.2 for History | Latest OpenAI model; 400K context; well-suited for factual narrative |
| Sentence-boundary guardrail buffering | Check per sentence not per chunk — balances latency vs safety thoroughness |
| Guardrail adds ~50–200ms per sentence | Moderation API (~5ms) + conditional Haiku rewrite (~100–150ms); acceptable for voice pacing |
| `min_endpointing_delay=0.4s` | Prevent premature cutoff; `max_endpointing_delay=2.0s` caps long pauses |
| Silero VAD | Lightweight, runs in worker process, accurate for classroom environments |
| Download VAD weights at Docker build time | Avoids 200MB download on container startup |
| Streaming TTS | Play audio as first chunk arrives, not after full response |

---

## LangChain / LangGraph Evaluation

### Decision: Exclude LangGraph. Defer LangChain to future phases.

#### LangGraph — Excluded
LangGraph's graph-based state machine model solves problems this architecture doesn't have. LiveKit Agents v1.x `@function_tool` handoffs already provide equivalent functionality. No meaningful feature gain for a four-agent voice router.

#### LangChain — Deferred (two future phases planned)

**Phase 1 (current build): Exclude**
Inline guardrails (`tts_node` override) and OTEL→Langfuse tracing are sufficient.

**Phase 2 (when guardrail rules proliferate): Add `guardrails-ai` + LangChain integration**
If safety checks grow beyond basic moderation, replace inline guard logic with `guardrails-ai` + `GuardrailsOutputParser`.

**Phase 3 (when lesson materials are needed as context): Add LangChain for RAG**
LangChain is the right tool if/when lesson materials need to be loaded, chunked, embedded, and retrieved. Pattern: LangChain retriever runs outside LiveKit orchestration, populates a context string injected into `chat_ctx` before the LLM call.

---

## Critical Gotchas

### SDK Version & API Correctness
1. **LiveKit v1.x only**: All tutorials referencing `VoicePipelineAgent` or `MultimodalAgent` are v0.x (deprecated in v1.0, April 2025). Use `AgentSession` + `Agent` + `@function_tool`.
2. **Pin to `livekit-agents~=1.4`**: v1.4.2 is current (Feb 2026). v1.3 is outdated. v1.4 drops Python 3.9 — use Python 3.10+.
3. **`await silero.VAD.load()`**: The call is async and MUST be awaited. Calling it synchronously will fail silently or error.
4. **`await token.toJwt()`**: `livekit-server-sdk` v2 changed `toJwt()` to async. All token generation code must `await` it.
5. **Agent dispatch uses typed classes**: Use `RoomConfiguration` + `RoomAgentDispatch` from `@livekit/protocol`, NOT plain object literals.
6. **`agent_speech_committed` event removed**: Use `session.on("conversation_item_added")` and filter by `item.role`.
7. **`@llm.ai_callable` removed**: All tool definitions must use `@function_tool`.
8. **`RoomInputOptions` deprecated**: Use `RoomOptions` instead in v1.4 Python SDK.
9. **`useVoiceAssistant` requires `AgentSessionProvider`**: Wrap room components in `<AgentSessionProvider>`.
10. **Install `@livekit/components-styles`**: Required peer dependency of `@livekit/components-react`.

### Architecture Constraints
11. **RealtimeModel cannot be mixed with pipeline in one AgentSession**: English agent runs in a separate `AgentSession`.
12. **Langfuse + OpenAI Realtime**: No native OTEL tracing for Realtime WebSocket sessions. Must add custom spans.
13. **Langfuse OTEL uses HTTP/protobuf, NOT gRPC**: Set `OTLPSpanExporter` endpoint to `/api/public/otel/v1/traces`.
14. **LiveKit UDP ports on macOS Docker Desktop**: Self-hosted LiveKit needs `use_external_ip: false` in `livekit.yaml` for local dev.
15. **Realtime model name updated**: Use `gpt-realtime` (GA, Aug 2025), not `gpt-4o-realtime-preview`.

### Operational
16. **Supabase async client**: Use `supabase>=2.2.0` with `acreate_client`.
17. **Guardrail does not apply to English agent `tts_node`**: Use `conversation_item_added` callback for post-hoc flagging.
18. **GPT-5.2 model ID**: Use env var `OPENAI_HISTORY_MODEL=gpt-5.2`. Easily updated without code change.
19. **Guardrail latency budget**: Sentence-boundary buffering keeps guardrail overhead to ~50–200ms per sentence.
20. **Pinning Docker image**: Use `livekit/livekit-server:v1.9.11` not `:latest`.

---

## Build Sequence
1. **Infra first**: `docker-compose.yml` → verify LiveKit v1.9.11 + Langfuse start cleanly
2. **Single agent POC**: Student speaks, hears Claude respond (no routing yet). Verify `await silero.VAD.load()`, `await token.toJwt()`, `AgentSessionProvider` wrapping all work end-to-end
3. **GuardedAgent base**: Implement `tts_node` guardrail base class and `guardrail.py` service; test against mock unsafe content before any routing
4. **Multi-agent routing (pipeline)**: Add Math + History agents inheriting `GuardedAgent`; test `@function_tool` handoffs with `chat_ctx` context preservation
5. **English Realtime session**: Register `learning-english` worker with separate `AgentSession(llm=RealtimeModel(...))`. Test two-session dispatch to same room and silent handoff back to orchestrator. If coordination is too complex, fall back to `openai.LLM(model="gpt-4o")` in pipeline session
6. **Transcript + observability**: Supabase writes + Langfuse OTEL spans + `guardrail_events` table
7. **Human escalation**: Teacher portal, Supabase Realtime notifications, token join flow
8. **Hardening**: Noise cancellation, VAD tuning, latency profiling, error handling, production Docker builds

---

## Verification
- `docker compose up` → all 6 services healthy
- Open `http://localhost:3000` → select Student role → ask an English question → verify SubjectBadge shows "English" and OpenAI Realtime agent responds
- Ask a maths question in same session → verify SubjectBadge switches to "Math", Claude Sonnet responds
- Ask a history question → verify SubjectBadge switches to "History", GPT-5.2 responds
- Inject a test response with a flagged word → verify guardrail rewrites before TTS plays; check Supabase `guardrail_events` table for the audit record
- Trigger escalation → verify teacher notification appears in `http://localhost:3000/teacher` → teacher joins room
- Check `http://localhost:3001` (Langfuse) → verify traces appear for orchestrator routing decisions, GPT-5.2 history calls, and guardrail moderation spans
- Query Supabase `transcript_turns` table → verify all turns logged with correct speaker/subject
- Check `escalation_events` table → verify teacher token generated on escalation

---

## Environment Variables Required
```
LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET
OPENAI_API_KEY
OPENAI_HISTORY_MODEL=gpt-5.2          ← configurable without code change
ANTHROPIC_API_KEY
SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
LANGFUSE_DB_PASSWORD, LANGFUSE_NEXTAUTH_SECRET
LANGFUSE_ADMIN_EMAIL, LANGFUSE_ADMIN_PASSWORD
NEXT_PUBLIC_LIVEKIT_URL (ws://localhost:7880 for dev)
```
