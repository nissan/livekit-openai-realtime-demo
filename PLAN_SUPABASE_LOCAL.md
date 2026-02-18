# Plan: Add Local Docker Supabase Support

## Context

The project was implemented with **cloud Supabase** as an external dependency — developers must create a project at supabase.co before `docker compose up` will work. This contradicts the stated goal of being "fully Dockerised for developer portability."

The user is asking whether local Docker Supabase is configured. **The answer is no — it is not currently configured.** This plan adds it.

### Current State
- `SUPABASE_URL=https://your-project.supabase.co` in `.env.example`
- No Supabase services in `docker-compose.yml` (only livekit, redis, langfuse-db, langfuse, agent, frontend)
- No `supabase/` directory or `config.toml`
- SQL migration is in `db/migrations/001_create_transcripts.sql` (requires manual paste into Supabase SQL Editor)
- Teacher portal uses Supabase Realtime — requires the Realtime service to be running locally

### Why this matters
- Developer onboarding requires creating a cloud Supabase account before anything works
- The Teacher escalation feature (`EscalationBanner`, `TeacherRoom`) uses Supabase Realtime WebSocket subscriptions — these need the Realtime service locally
- Langfuse already self-hosts its own Postgres; Supabase is the only "cloud only" service

---

## Approach: Supabase CLI + docker-compose integration

Use the official Supabase CLI local development stack. The Supabase CLI runs a full local Supabase stack via Docker (Postgres, GoTrue auth, PostgREST, Realtime, Studio dashboard). We wire it into the project so `docker compose up` works end-to-end without any cloud accounts.

Two concrete changes:

### 1. Add Supabase to docker-compose.yml

Use the official Supabase self-hosted Docker images (same images the CLI uses internally). Add these services to `docker-compose.yml`:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `supabase-db` | `supabase/postgres:15.6.1.152` | 5432 (internal) | PostgreSQL with supabase extensions |
| `supabase-auth` | `supabase/gotrue:v2.164.0` | internal | Auth / JWT validation |
| `supabase-rest` | `postgrest/postgrest:v12.2.3` | internal | Auto-REST API from schema |
| `supabase-realtime` | `supabase/realtime:v2.30.23` | internal | WebSocket subscriptions (critical for teacher escalation) |
| `supabase-meta` | `supabase/postgres-meta:v0.84.2` | internal | DB introspection (used by Studio) |
| `supabase-studio` | `supabase/studio:20241028-d34f26e` | 54323 | Local Supabase UI dashboard |
| `supabase-kong` | `kong:2.8.1` | 54321→8000 | API gateway (routes to auth/rest/realtime) |

Local URLs:
- **API**: `http://localhost:54321` (via Kong)
- **Studio**: `http://localhost:54323`
- **DB**: `postgresql://postgres:postgres@localhost:5432/postgres`

### 2. Initialize supabase/ project structure

Create `supabase/config.toml` and move the migration:
- `supabase/config.toml` — Supabase CLI project config (project_id, auth settings, etc.)
- `supabase/migrations/20260218000000_create_transcripts.sql` — migration in Supabase CLI timestamp format (moved from `db/migrations/001_create_transcripts.sql`)
- `supabase/seed.sql` — optional seed data (empty for now)
- `supabase/kong.yml` — Kong declarative config routing auth/rest/realtime

When Supabase CLI is available, developers can also run `supabase db push` or `supabase db reset` to apply migrations. When using pure Docker Compose, we apply migrations via an init SQL mount.

### 3. Update environment variables

`.env.example` switches to local URLs for dev:
```
# Local Supabase (docker compose up)
SUPABASE_URL=http://localhost:54321
SUPABASE_ANON_KEY=<fixed local anon key — same for all local instances>
SUPABASE_SERVICE_KEY=<fixed local service key — same for all local instances>

# Frontend env vars (browser must use localhost)
NEXT_PUBLIC_SUPABASE_URL=http://localhost:54321
NEXT_PUBLIC_SUPABASE_ANON_KEY=<same fixed anon key>
```

The local anon and service keys are well-known fixed values for local Supabase development (they're not secrets — they're JWT signed with the local JWT secret which is also fixed). These are documented in the official Supabase self-hosting guide.

### 4. Auto-apply migrations in docker-compose

Mount the migration SQL into `supabase-db` initdb volume so it runs automatically on first start:
```yaml
supabase-db:
  volumes:
    - ./supabase/migrations:/docker-entrypoint-initdb.d/migrations:ro
```

### 5. Update docker-compose.override.yml

Add `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` to frontend dev environment (currently only `SUPABASE_URL`/`SUPABASE_ANON_KEY` server-side vars are set).

---

## Files Created/Modified

### New files
- `supabase/config.toml` — Supabase CLI project config
- `supabase/kong.yml` — Kong API gateway declarative config
- `supabase/migrations/20260218000000_create_transcripts.sql` — migration (timestamp-renamed copy)
- `supabase/seed.sql` — empty seed file

### Modified files
- `docker-compose.yml` — added 7 Supabase services + depends_on wiring for agent/frontend
- `docker-compose.override.yml` — added `NEXT_PUBLIC_SUPABASE_*` env vars to frontend
- `.env.example` — switched Supabase URLs to localhost defaults + added `NEXT_PUBLIC_*` vars

### No changes needed
- `agent/services/transcript_store.py` — already reads `SUPABASE_URL`/`SUPABASE_SERVICE_KEY` from env
- `agent/services/human_escalation.py` — already reads from env
- `agent/services/guardrail.py` — already reads from env
- `db/migrations/001_create_transcripts.sql` — kept in place (supabase/ version is a copy)
- `frontend/components/TeacherRoom.tsx` — already used `process.env.NEXT_PUBLIC_SUPABASE_URL` and `process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY`

---

## Local Supabase Fixed Keys (well-known defaults)

These are the same default values used by `supabase start` locally — not secrets:
```
JWT_SECRET=super-secret-jwt-token-with-at-least-32-characters-long
ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlhdCI6MTYzNDAxMzA3OSwiZXhwIjoxOTQ5NTczMDc5fQ.ix3Xvz1KYi-nF_GmVRJZ9F7Yam8CU_u2NzFKTQO9flo
SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNjM0MDEzMDc5LCJleHAiOjE5NDk1NzMwNzl9.D4gyAqkKFFsgPIz-MmYQHlx1xERp1gHQMEbPuvX5ogs
```

---

## Verification

After changes:
1. `docker compose up` — all ~13 services healthy (6 existing + 7 Supabase)
2. `http://localhost:54323` — Supabase Studio opens, shows tables
3. Tables exist: `learning_sessions`, `transcript_turns`, `routing_decisions`, `escalation_events`, `guardrail_events`
4. `http://localhost:3000` → Student session → check Supabase Studio `transcript_turns` table populates
5. Trigger escalation → check `escalation_events` table → verify teacher portal receives Realtime notification
6. No cloud Supabase credentials needed — `.env` only needs API keys (OpenAI, Anthropic, LiveKit)

### Optional (if Supabase CLI installed)
```bash
supabase start          # starts local stack
supabase db reset       # resets DB and re-applies migrations
supabase studio         # opens Studio in browser
```

---

## Implementation Date
2026-02-18
