# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

Student-Assisted Learning Voice Agent: students speak naturally and get routed to specialist AI tutors for Maths (Claude Sonnet 3.5), English (OpenAI Realtime), and History (GPT). An orchestrator (Claude Haiku) routes questions and can escalate to a human teacher.

## Commands

### Agent (Python)

```bash
# Install dependencies
cd agent && uv sync

# Run all unit tests
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v

# Run a single test file
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_guardrail.py -v

# Run a single test by name
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/test_guardrail.py::TestCheck::test_clean_passes -v

# Run integration tests (requires real API keys)
PYTHONPATH=$(pwd) uv run --directory agent pytest tests/integration/ -v -s

# Lint
uv run --directory agent ruff check agent/

# Run agent locally (outside Docker)
cd /path/to/repo
PYTHONPATH=$(pwd) LIVEKIT_URL=ws://localhost:7880 LIVEKIT_API_KEY=devkey LIVEKIT_API_SECRET=devsecret OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... uv run --directory agent python main.py dev
```

### Frontend (Next.js)

```bash
cd frontend
npm install
npm run dev          # dev server on :3000
npm run build        # production build
npm run lint         # ESLint
npm run type-check   # TypeScript check (no emit)
npm run test:e2e     # Playwright E2E (66 tests: 33 × chromium + firefox)
npm run test:e2e:ui  # Playwright with interactive UI
```

### Docker (full stack)

```bash
docker compose up           # start all 18 services
docker compose up agent     # start specific service
docker compose logs -f agent  # follow logs
```

## Architecture

### Two-Worker Model

The agent worker (`agent/main.py`) registers two distinct worker types, selected via `AGENT_TYPE` env var:

- **`learning-orchestrator`** (`AGENT_TYPE=orchestrator`, default): Pipeline session using STT+LLM+TTS chain. Runs `OrchestratorAgent → MathAgent / HistoryAgent` within one `AgentSession`. Dispatched when a student joins via the token API.
- **`learning-english`** (`AGENT_TYPE=english`): Separate worker using `RealtimeModel` (OpenAI gpt-realtime, native speech-to-speech). Dispatched on-demand by the orchestrator to the same LiveKit room. Cannot share a session with the pipeline worker.

### Agent Hierarchy

```
GuardedAgent (base.py)          — tts_node guardrail + on_enter() generate_reply
├── OrchestratorAgent            — Claude Haiku; classifies + routes
├── MathAgent                    — Claude Sonnet 3.5
└── HistoryAgent                 — GPT (pipeline TTS)

EnglishAgent (english_agent.py) — OpenAI Realtime; separate AgentSession; no GuardedAgent
```

### Routing Architecture

All routing goes through `agent/tools/routing.py`. The key constraint: **specialists never route directly to other specialists** — they always `route_back_to_orchestrator`, which then re-routes. Cross-subject flows: Orchestrator → Math/History/English.

Routing functions return `(new_agent_instance, "transition sentence")` tuples for in-session handoffs (math/history/orchestrator), or just a string for English (which triggers a LiveKit API dispatch to a separate worker).

### GuardedAgent.tts_node

Every pipeline agent overrides `tts_node` to run safety checks per sentence:
1. Buffer LLM text stream at sentence boundaries (`.!?:;`)
2. `omni-moderation-latest` check (~5ms)
3. If flagged → Claude Haiku rewrite (~150ms) + log to Supabase `guardrail_events`
4. Delegate to `Agent.default.tts_node` to yield `rtc.AudioFrame`

**Critical**: Must return `AsyncIterable[rtc.AudioFrame]`, not text. English agent handles this differently (audio-native, no tts_node guardrail).

### Session State

`SessionUserdata` (`agent/models/session_state.py`) is the shared mutable state across all agent handoffs within one student session. Carried as `AgentSession.userdata`. Key fields: `session_id`, `current_subject`, `speaking_agent`, `skip_next_user_turns`, `turn_number`.

### Frontend Component Tree

```
app/student/page.tsx → StudentRoom.tsx
  LiveKitRoom                      — provides RoomContext
    ConnectionGuard                — waits for Connected + agent participant
      StudentRoomInner             — uses hooks that depend on RoomContext
        useTranscript()            — listens to room "transcript" data channel
        useVoiceAssistant()        — reads from RoomContext (no SessionProvider)
        SubjectBadge, TranscriptPanel, AgentStateIndicator, EscalationBanner
```

**Critical**: `SessionProvider` is intentionally absent. In `@livekit/components-react` v2.9.19, `SessionProvider` crashes on `session.room` access before the voice pipeline is ready. `useVoiceAssistant()` reads from `RoomContext` directly.

### Token API

`frontend/app/api/token/route.ts` issues LiveKit JWTs. Student tokens embed `RoomConfiguration` + `RoomAgentDispatch` using typed classes from `@livekit/protocol` (not plain objects) to auto-dispatch `learning-orchestrator` on room join.

### Observability

All LLM calls auto-traced via OpenTelemetry → Langfuse v3. Endpoint: `http://langfuse:3000/api/public/otel/v1/traces` (HTTP/protobuf, not gRPC). Custom spans for routing decisions (`routing.decision`), guardrail checks (`tts.sentence`), and session lifecycle (`session.start`, `session.end`).

### Transcript Flow

Agent → `ctx.room.local_participant.publish_data(payload, topic="transcript")` → frontend `room.on("dataReceived", ...)` in `useTranscript` hook → React state → `TranscriptPanel`. Also saved to Supabase `transcript_turns` via `transcript_store.save_transcript_turn()`.

## Key File Locations

| Path | Purpose |
|---|---|
| `agent/main.py` | Worker entrypoint; registers both worker types |
| `agent/agents/base.py` | `GuardedAgent` base class with tts_node guardrail |
| `agent/agents/orchestrator.py` | Routing/classification agent |
| `agent/agents/english_agent.py` | OpenAI Realtime session factory |
| `agent/tools/routing.py` | All cross-agent handoff implementations |
| `agent/models/session_state.py` | `SessionUserdata` dataclass |
| `agent/services/guardrail.py` | `check_and_rewrite()` pipeline |
| `agent/services/transcript_store.py` | Supabase persistence |
| `agent/services/langfuse_setup.py` | OTEL/Langfuse configuration |
| `agent/tests/conftest.py` | Mocks all external APIs (no network needed for unit tests) |
| `agent/tests/fixtures/synthetic_questions.py` | 63-item parametrised test dataset |
| `frontend/app/api/token/route.ts` | LiveKit JWT generation |
| `frontend/components/StudentRoom.tsx` | Main voice UI |
| `frontend/hooks/useTranscript.ts` | Real-time transcript from data channel |
| `db/migrations/001_create_transcripts.sql` | Supabase schema |

## Critical Gotchas

### Python Imports

The `agent/` directory is the project root. Import as `from agent.agents.xxx import ...`. Run tests from the repo root with `PYTHONPATH=$(pwd)`. The `hatchling` build config lists `packages = ["agents", "models", "services", "tools"]` (the subdirs, not "agent").

### LiveKit Agents v1.4 API

- `session.wait()` does not exist — use `asyncio.Event` on `session.on("close", ...)`
- `tts_node` must return `AsyncIterable[rtc.AudioFrame]`, not text strings
- Use `@function_tool` decorator (not `@llm.ai_callable`, which was removed)
- Use `conversation_item_added` event (not `agent_speech_committed`, which was removed)
- `await token.toJwt()` is async in livekit-server-sdk v2

### macOS Docker Dev

`livekit.yaml` must set `rtc.node_ip: 127.0.0.1`. Without it, LiveKit advertises the container-internal IP as ICE candidates → browser gets `ConnectionError` even though UDP ports are forwarded.

### Transcript Speaker Attribution

`speaking_agent` is set in `GuardedAgent.on_enter()`, which fires **after** the transition message. This is intentional: the transition sentence ("Let me connect you with...") is attributed to the current speaker, not the incoming agent.

Phantom "user" transcript entries from `generate_reply(user_input=pending_q)` are suppressed via `userdata.skip_next_user_turns` counter (not string comparison — LLM varies phrasing).

### English Routing Timing

When routing to English: dispatch LiveKit API call → pipeline session closes after 3.5s (via `asyncio.sleep`) → English Realtime worker starts at ~4s. Never call `session.interrupt()` during this handoff (it silences the transition sentence mid-word).

### Langfuse v3

Requires ClickHouse + MinIO + `langfuse-worker` service. Without `langfuse-worker`, OTEL spans queue in Redis BullMQ but are never processed (0 traces in UI). The `LANGFUSE_S3_EVENT_UPLOAD_BUCKET` env var is mandatory.
