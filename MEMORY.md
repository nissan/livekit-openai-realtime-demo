# Project Memory — Learning Voice Agent

## Project: livekit-openai-realtime-demo
GitHub: https://github.com/nissan/livekit-openai-realtime-demo

## Architecture
- 13-service Docker stack: livekit, redis, langfuse-db, langfuse-clickhouse, langfuse-minio(+init), langfuse, **langfuse-worker**, supabase-db, supabase-auth, supabase-kong, supabase-rest, supabase-realtime, supabase-meta, supabase-studio, agent, frontend
- Pipeline session (learning-orchestrator): Orchestrator→Math→History agents (all can cross-route)
- Realtime session (learning-english): separate AgentSession for OpenAI Realtime
- GuardedAgent base class: tts_node guardrail + on_enter() generate_reply on all pipeline agents
- Shared routing: agent/tools/routing.py — specialists can route to each other (not just orchestrator)

## Critical SDK Gotchas (LiveKit v1.4)
- `await silero.VAD.load()` — must be async
- `await token.toJwt()` — async in server-sdk v2
- Use `@function_tool` not `@llm.ai_callable` (removed)
- Use `conversation_item_added` not `agent_speech_committed` (removed)
- `SessionProvider` (NOT `AgentSessionProvider`) required to wrap components using `useVoiceAssistant` — `AgentSessionProvider` does not exist in v2.9.19
- `SessionProvider` crashes if rendered before room connects (`session.room` undefined) → wrap with `ConnectionGuard` using `useConnectionState()` inside `LiveKitRoom`
- Install `@livekit/components-styles` as peer dep alongside `@livekit/components-react`
- `RoomConfiguration` + `RoomAgentDispatch` must use typed classes from `@livekit/protocol`
- Langfuse OTEL: HTTP/protobuf endpoint `/api/public/otel/v1/traces`, NOT gRPC

## LiveKit Docker / macOS Gotchas
- `livekit.yaml` must set `rtc.node_ip: 127.0.0.1` for macOS Docker Desktop local dev.
  Without it, LiveKit advertises container-internal IP (172.17.x.x) as ICE candidates →
  browser gets `ConnectionError: could not establish pc connection` even though UDP ports are forwarded.
- Agent running outside Docker: set `LIVEKIT_URL=ws://localhost:7880` (not `ws://livekit:7880` from .env which only resolves inside Docker)

## Testing Infrastructure
- Pytest 72 unit tests: `PYTHONPATH=$(pwd) uv run --directory agent pytest tests/ -v`
- Playwright 25 E2E tests: `cd frontend && npm run test:e2e` (chromium, reuseExistingServer)
- Token shape test skips gracefully when LIVEKIT_API_KEY/SECRET absent

## Python Package Import Gotcha (hatchling + Docker)
- `agent/` dir IS the project root — no nested `agent/` package exists
- Fix: `agent/__init__.py` at project root + `agent/conftest.py` adds `..` to sys.path
- hatchling `packages = ["agents", "models", "services", "tools"]` (the actual subdirs, not "agent")
- OTEL `previous_subject` must be captured BEFORE calling `userdata.route_to()` or it reflects the new subject
- **CRITICAL Docker fix**: Dockerfile uses `WORKDIR /workspace/agent` + `ENV PYTHONPATH=/workspace`
  so `from agent.agents.xxx` resolves to `/workspace/agent/agents/xxx.py`. Without this, the
  hatchling editable install `.pth` file is empty (packages not present at `RUN uv pip install` time)
  and ALL `from agent.*` imports fail at startup.
- **CRITICAL outside Docker**: Must set `PYTHONPATH=/path/to/repo/root`:
  ```
  cd /path/to/livekit-openai-realtime-demo
  PYTHONPATH=$(pwd) uv run --directory agent python3 main.py start
  ```

## Critical Agent v1.4 API Gotchas
- `session.wait()` does NOT exist → use `asyncio.Event` on session `"close"` event:
  ```python
  closed = asyncio.Event()
  session.on("close", lambda _: closed.set())
  await session.start(agent, room=ctx.room)
  await closed.wait()
  ```
- `tts_node` must return `AsyncIterable[rtc.AudioFrame]` NOT `AsyncIterable[str]`:
  ```python
  def tts_node(self, text, model_settings):
      async def _audio():
          async for frame in Agent.default.tts_node(self, safe_text_gen(), model_settings):
              yield frame
      return _audio()
  ```
  Returning text strings silently produces no audio — agent goes Thinking but never speaks.

## SessionProvider — Final Resolution (v2.9.19)
- `SessionProvider` (`Ta` in minified bundle) crashes on `session.room` before voice pipeline ready
- Fix: Remove `SessionProvider` entirely from `StudentRoom.tsx`. `useVoiceAssistant()` reads from
  RoomContext (via `useRemoteParticipants`/`useTracks`/`useConnectionState`) — no SessionProvider needed.
- Replace `VoiceAssistantControlBar` with `TrackToggle source={Track.Source.Microphone}`
- `useAudioPlayback()` for Chrome autoplay policy — show "enable audio" banner when `!canPlayAudio`

## Docker / Infra Gotchas (Langfuse v3 + Supabase ECR)
- Langfuse v3 requires ClickHouse + MinIO — `LANGFUSE_S3_EVENT_UPLOAD_BUCKET` is mandatory (no default)
- **Langfuse v3 needs langfuse-worker service** (`langfuse/langfuse-worker:3`) — without it, OTEL spans
  queue in Redis BullMQ (`bull:otel-ingestion-queue:wait`) but are NEVER processed → 0 traces in UI
- Langfuse healthcheck: `wget -qO- http://$(hostname):3000/api/public/health` — use `hostname` not
  `127.0.0.1` or `hostname -i`; the Next.js server binds to the Docker network IP, not loopback
- Agent `depends_on: langfuse: condition: service_healthy` prevents "Invalid credentials" OTEL failures
  caused by agent starting before Langfuse init creates the `pk-lf-dev`/`sk-lf-dev` API keys
- ClickHouse needs `{shard}` + `{replica}` macros in listen.xml for `ReplicatedMergeTree ON CLUSTER`
- ClickHouse healthcheck: use `http://127.0.0.1:8123/ping` NOT `localhost` (macOS Docker routes localhost → IPv6)
- Kong healthcheck: use admin API `http://127.0.0.1:8001/` NOT proxy port `localhost:8000` (IPv6 issue + Kong proxy binds 0.0.0.0 only)
- Supabase ECR images: postgres 17 superuser is `supabase_admin`; init script must be named `zz-*` to run AFTER image's `migrate.sh` creates service roles
- Langfuse INIT keys: `pk-lf-*` / `sk-lf-*` (NOT `lf-pk-*`); email must have valid TLD (e.g. `admin@example.local`, not `admin@localhost`)
- Frontend node_modules: do NOT use named Docker volume — it shadows host node_modules (which has correct @swc/helpers). Mount `./frontend:/app` and use host node_modules directly. Named volume for `.next` cache is fine.

## Next.js / Frontend Gotchas
- Next.js 14 does NOT support `next.config.ts` — use `next.config.mjs`
- CSS `@import "@livekit/components-styles"` fails in postcss (can't resolve package exports)
  → Fix: import in `layout.tsx` as JS: `import "@livekit/components-styles"`
- Playwright strict mode: use `getByRole('heading')` not `getByText(/regex/)` when multiple elements match

## LiveKit Transcript + Routing Gotchas (PLAN16)
- `session.interrupt()` stops ALL in-progress TTS immediately — calling it after dispatch
  silences the orchestrator's transition sentence mid-word. Never use `interrupt()` unless
  you explicitly want total silence. Use a timer + `aclose()` instead.
- `registerTextStreamHandler("lk.transcription")` throws `DataStreamError` — `@livekit/components-react`
  already owns this topic (single-subscriber). Use `room.on("transcriptionReceived", ...)` for
  multi-listener access, but note it fires for ALL remote participants (every agent), not English only.
- `transcriptionReceived` + `dataReceived(topic="transcript")` = duplicates — both fire for every
  agent turn. `publish_data(topic="transcript")` via `conversation_item_added` is the single source
  of truth for all agents; do not add a second transcript path.
- English agent `conversation_item_added` DOES fire with populated `text_content` (PLAN15 unwrap
  fix was sufficient). The initial PLAN16 assumption of `forwarded_text=""` was wrong.
- Pipeline close timing for English handoff: no `interrupt()` + `aclose()` at T+3.5s. English starts
  at T+4s (3s sleep + ~1s WebRTC). Orchestrator gets ~3.5s to speak its transition sentence.
- `generate_reply(user_input=pending_q)` in `on_enter()` injects a phantom `role="user"` conversation
  item → appears as "You" in transcript. Fix: set `userdata.skip_next_user_turns = 1` before routing;
  consume in `on_conversation_item` with a counter (NOT string comparison — LLM varies phrasing).
- Never compare LLM-generated `question_summary` strings for equality — use flags/counters instead.

## User Preferences
- Git commits frequently with intelligent messages for audit trail
- Public GitHub repo for all projects
- **Every plan must be saved as PLAN{N}.md in project root** for architect audit trail — do this as part of every plan implementation (PLAN.md, PLAN2–PLAN16 all present)
- **Blanket approval for**: `docker`, `docker compose`, `docker inspect`, `grep`, `sed` — no need to ask for confirmation, always proceed

## Key File Locations
- Plans: PLAN.md–PLAN16.md (root)
- Session state: agent/models/session_state.py (SessionUserdata — skip_next_user_turns etc.)
- Agent entrypoint: agent/main.py
- Guardrail: agent/services/guardrail.py
- Shared routing: agent/tools/routing.py (all cross-agent handoffs)
- Token API: frontend/app/api/token/route.ts
- DB schema: db/migrations/001_create_transcripts.sql
- Sample questions: frontend/lib/sample-questions.ts
- Demo walkthrough: frontend/app/demo/page.tsx
- Pytest root conftest: agent/conftest.py (sys.path fix)
