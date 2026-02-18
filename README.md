# Student-Assisted Learning Voice Agent

AI-powered voice tutoring with multi-agent routing: students speak naturally and get connected to specialist AI tutors for **Maths** (Claude Sonnet 3.5), **English** (OpenAI Realtime), and **History** (GPT-5.2). An orchestrator (Claude Haiku) routes questions and can escalate to a human teacher.

## Architecture

```
Student speaks
    ↓
[LiveKit WebRTC] — global WebRTC infrastructure
    ↓
[OrchestratorAgent: Claude Haiku] — fast routing/classification
    ├── English → [EnglishAgent: OpenAI Realtime gpt-realtime] (separate session)
    ├── Maths   → [MathAgent: Claude Sonnet 3.5 + TTS pipeline]
    ├── History → [HistoryAgent: GPT-5.2 + TTS pipeline]
    └── Escalate → Teacher joins live room (Supabase Realtime notification)

All pipeline agents (Math, History, Orchestrator):
  LLM text → [GuardedAgent.tts_node] → omni-moderation-latest → [Claude Haiku rewrite if flagged] → TTS → student

Observability: Langfuse v3 (OTEL HTTP/protobuf traces)
Storage: Supabase (transcripts, routing decisions, guardrail events, escalations)
```

## Quick Start

### 1. Prerequisites

- Docker Desktop
- API keys: OpenAI, Anthropic, Supabase project
- (Optional) Langfuse keys for observability

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

Minimum required variables:
```
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...
```

### 3. Set up Supabase database

Run the migration in your Supabase project SQL editor:
```bash
# Copy contents of db/migrations/001_create_transcripts.sql
# Paste into Supabase → SQL Editor → Run
```

### 4. Start services

```bash
docker compose up
```

Services started:
| Service | URL | Purpose |
|---|---|---|
| Frontend | http://localhost:3000 | Student & Teacher UI |
| Langfuse | http://localhost:3001 | Observability dashboard |
| LiveKit | ws://localhost:7880 | WebRTC server |

### 5. Use the app

1. Open http://localhost:3000
2. Select **Student**, enter your name, click **Start Learning**
3. Speak naturally — ask a maths question, an English question, or a history question
4. Watch the **SubjectBadge** update as you're routed to the right specialist
5. For teacher monitoring: select **Teacher** on the home page

## Project Structure

```
├── agent/              Python LiveKit Agents v1.4 worker
│   ├── agents/         GuardedAgent base, Orchestrator, Math, English, History
│   ├── services/       Guardrail, Transcript storage, Human escalation, Langfuse
│   └── models/         SessionUserdata dataclass
├── frontend/           Next.js 14 App Router
│   ├── app/            Pages + LiveKit token API route
│   ├── components/     StudentRoom, TeacherRoom, TranscriptPanel, etc.
│   └── hooks/          useAgentState, useTranscript
├── db/migrations/      Supabase schema (5 tables + views)
├── docker-compose.yml  6-service stack
├── livekit.yaml        Self-hosted LiveKit config
└── PLAN.md             Full architectural plan (for architects)
```

## Key Architecture Decisions

### Two-session architecture for English (OpenAI Realtime)
`RealtimeModel` cannot be mixed with STT+LLM+TTS pipeline in one `AgentSession`. The English agent runs in a **separate** `AgentSession` (`learning-english` worker) in the **same LiveKit room**, dispatched on demand by the orchestrator.

### Guardrail pipeline (all pipeline agents)
Every agent response goes through `GuardedAgent.tts_node`:
```
LLM text stream → sentence buffer → omni-moderation-latest (~5ms)
  → clean: yield directly to TTS
  → flagged: Claude Haiku rewrite (~150ms) → log to Supabase → yield to TTS
```

### Observability
All LLM calls auto-traced via OTEL → Langfuse. Custom spans for routing decisions, guardrail checks, and Realtime audio events.

## Development

### Local agent development (without Docker)

```bash
cd agent
uv sync
LIVEKIT_URL=ws://localhost:7880 \
LIVEKIT_API_KEY=devkey \
LIVEKIT_API_SECRET=devsecret \
OPENAI_API_KEY=sk-... \
ANTHROPIC_API_KEY=sk-ant-... \
python main.py dev
```

### Local frontend development

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:3000
```

### Verify guardrail

With the agent running, inject test content via the OpenAI Realtime console or unit test:
```python
# agent/services/guardrail.py has check_and_rewrite() for direct testing
import asyncio
from agent.services.guardrail import check_and_rewrite

result = asyncio.run(check_and_rewrite("test harmful content", session_id="test"))
```

## Production Deployment

1. Remove `livekit` and `redis` from docker-compose.yml services
2. Set `LIVEKIT_URL` to your LiveKit Cloud endpoint
3. Set `NEXT_PUBLIC_LIVEKIT_URL` to the same (for browser clients)
4. Configure a production Langfuse instance or Langfuse Cloud
5. Set all secrets in your deployment environment (never commit `.env`)

## Verification Checklist

- [ ] `docker compose up` — all 6 services healthy
- [ ] Student asks English question → SubjectBadge shows "English", Realtime agent responds
- [ ] Student asks Maths question → SubjectBadge shows "Mathematics", Claude Sonnet responds
- [ ] Student asks History question → SubjectBadge shows "History", GPT-5.2 responds
- [ ] Guardrail test → check Supabase `guardrail_events` table for audit record
- [ ] Escalation trigger → teacher notification at /teacher → teacher joins room
- [ ] Langfuse http://localhost:3001 → traces for routing decisions + LLM calls
- [ ] Supabase `transcript_turns` → all turns logged with correct speaker/subject

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, TypeScript, @livekit/components-react, Tailwind CSS |
| Agent Worker | Python 3.11, livekit-agents~=1.4 |
| Orchestrator | Claude Haiku (fast routing) |
| English Agent | OpenAI Realtime `gpt-realtime` (native speech-to-speech) |
| Math Agent | Claude Sonnet 3.5 + pipeline TTS |
| History Agent | GPT-5.2 + pipeline TTS |
| Guardrails | OpenAI `omni-moderation-latest` + Claude Haiku rewriter |
| Database | Supabase (PostgreSQL + Realtime) |
| Observability | Langfuse v3 (self-hosted) |
| WebRTC | LiveKit v1.9.11 (self-hosted dev, Cloud for prod) |
