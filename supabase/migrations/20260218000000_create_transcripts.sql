-- ============================================================
-- Student-Assisted Learning Voice Agent — Database Schema
-- ============================================================
-- Migration: 20260218000000_create_transcripts
-- Applied automatically via docker-entrypoint-initdb.d on first start.
-- Also compatible with `supabase db reset` when CLI is installed.
-- Agent worker uses SUPABASE_SERVICE_KEY (bypasses RLS).
-- Frontend uses SUPABASE_ANON_KEY (subject to RLS).
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. learning_sessions
--    One row per student session. Created when agent connects;
--    updated on session end with session_report JSONB.
-- ============================================================
CREATE TABLE IF NOT EXISTS learning_sessions (
    session_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    room_name         TEXT NOT NULL,
    student_identity  TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at          TIMESTAMPTZ,
    session_report    JSONB,           -- full conversation summary on close
    CONSTRAINT room_name_not_empty CHECK (room_name <> ''),
    CONSTRAINT student_identity_not_empty CHECK (student_identity <> '')
);

CREATE INDEX IF NOT EXISTS idx_learning_sessions_room ON learning_sessions (room_name);
CREATE INDEX IF NOT EXISTS idx_learning_sessions_student ON learning_sessions (student_identity);
CREATE INDEX IF NOT EXISTS idx_learning_sessions_created ON learning_sessions (created_at DESC);

ALTER TABLE learning_sessions ENABLE ROW LEVEL SECURITY;

-- Teachers (authenticated) can read all sessions
CREATE POLICY "Teachers can read sessions"
    ON learning_sessions FOR SELECT
    TO authenticated
    USING (true);

-- Service role (agent worker) has full access — bypasses RLS
-- No additional policy needed; service_role always bypasses RLS

-- ============================================================
-- 2. transcript_turns
--    Each STT or LLM turn. Published to room data channel
--    (topic: "transcript") and stored here for audit.
-- ============================================================
CREATE TABLE IF NOT EXISTS transcript_turns (
    id            BIGSERIAL PRIMARY KEY,
    session_id    UUID NOT NULL REFERENCES learning_sessions(session_id) ON DELETE CASCADE,
    turn_number   INTEGER NOT NULL,
    speaker       TEXT NOT NULL,          -- "student" | "orchestrator" | "math" | "english" | "history" | "teacher"
    role          TEXT NOT NULL,          -- "user" | "assistant"
    content       TEXT NOT NULL,
    subject_area  TEXT,                   -- "math" | "english" | "history" | NULL (for orchestrator)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transcript_turns_session ON transcript_turns (session_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_transcript_turns_subject ON transcript_turns (subject_area);

ALTER TABLE transcript_turns ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Teachers can read transcripts"
    ON transcript_turns FOR SELECT
    TO authenticated
    USING (true);

-- ============================================================
-- 3. routing_decisions
--    Agent handoff log — one row per routing event.
--    Used for Langfuse dashboard: subject distribution,
--    escalation rate.
-- ============================================================
CREATE TABLE IF NOT EXISTS routing_decisions (
    id                BIGSERIAL PRIMARY KEY,
    session_id        UUID NOT NULL REFERENCES learning_sessions(session_id) ON DELETE CASCADE,
    turn_number       INTEGER,
    from_agent        TEXT NOT NULL,      -- "orchestrator" | "math" | "english" | "history"
    to_agent          TEXT NOT NULL,      -- "math" | "english" | "history" | "teacher_escalation"
    question_summary  TEXT,              -- short summary of what triggered the route
    confidence        FLOAT,             -- 0.0–1.0 if orchestrator returns one
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_decisions_session ON routing_decisions (session_id);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_to_agent ON routing_decisions (to_agent);
CREATE INDEX IF NOT EXISTS idx_routing_decisions_created ON routing_decisions (created_at DESC);

ALTER TABLE routing_decisions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Teachers can read routing decisions"
    ON routing_decisions FOR SELECT
    TO authenticated
    USING (true);

-- ============================================================
-- 4. escalation_events
--    Teacher invite tokens. Supabase Realtime broadcasts
--    inserts to the teacher portal frontend.
-- ============================================================
CREATE TABLE IF NOT EXISTS escalation_events (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES learning_sessions(session_id) ON DELETE CASCADE,
    room_name       TEXT NOT NULL,
    reason          TEXT NOT NULL,        -- orchestrator's escalation reason
    teacher_token   TEXT NOT NULL,        -- pre-signed LiveKit JWT for teacher
    teacher_joined  BOOLEAN NOT NULL DEFAULT FALSE,
    teacher_joined_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '2 hours')
);

CREATE INDEX IF NOT EXISTS idx_escalation_events_session ON escalation_events (session_id);
CREATE INDEX IF NOT EXISTS idx_escalation_events_room ON escalation_events (room_name);
-- Partial index: quickly find pending (un-joined) escalations
CREATE INDEX IF NOT EXISTS idx_escalation_events_pending
    ON escalation_events (created_at DESC)
    WHERE teacher_joined = FALSE;

ALTER TABLE escalation_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Teachers can read escalation events"
    ON escalation_events FOR SELECT
    TO authenticated
    USING (true);

-- Enable Realtime for teacher portal notifications
ALTER PUBLICATION supabase_realtime ADD TABLE escalation_events;

-- ============================================================
-- 5. guardrail_events
--    Audit log of every flagged + rewritten response.
--    Required for compliance, teacher review, model improvement.
-- ============================================================
CREATE TABLE IF NOT EXISTS guardrail_events (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID NOT NULL REFERENCES learning_sessions(session_id) ON DELETE CASCADE,
    agent_name          TEXT NOT NULL,          -- "math" | "english" | "history" | "orchestrator"
    original_text       TEXT NOT NULL,
    rewritten_text      TEXT NOT NULL,
    categories_flagged  TEXT[] NOT NULL DEFAULT '{}',  -- e.g. {"harassment", "violence"}
    moderation_score    FLOAT,                  -- highest score from omni-moderation-latest
    action_taken        TEXT NOT NULL DEFAULT 'rewrite',  -- "rewrite" | "suppress"
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_guardrail_events_session ON guardrail_events (session_id);
CREATE INDEX IF NOT EXISTS idx_guardrail_events_agent ON guardrail_events (agent_name);
CREATE INDEX IF NOT EXISTS idx_guardrail_events_created ON guardrail_events (created_at DESC);
-- GIN index for querying by flagged categories
CREATE INDEX IF NOT EXISTS idx_guardrail_events_categories
    ON guardrail_events USING GIN (categories_flagged);

ALTER TABLE guardrail_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Teachers can read guardrail events"
    ON guardrail_events FOR SELECT
    TO authenticated
    USING (true);

-- ============================================================
-- Helper views for Langfuse dashboard integration
-- ============================================================

-- Subject distribution per day
CREATE OR REPLACE VIEW subject_distribution_daily AS
SELECT
    DATE_TRUNC('day', created_at) AS day,
    to_agent AS subject,
    COUNT(*) AS routing_count
FROM routing_decisions
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;

-- Escalation rate per day
CREATE OR REPLACE VIEW escalation_rate_daily AS
SELECT
    DATE_TRUNC('day', ls.created_at) AS day,
    COUNT(DISTINCT ls.session_id) AS total_sessions,
    COUNT(DISTINCT ee.session_id) AS escalated_sessions,
    ROUND(
        COUNT(DISTINCT ee.session_id)::NUMERIC /
        NULLIF(COUNT(DISTINCT ls.session_id), 0) * 100,
        1
    ) AS escalation_rate_pct
FROM learning_sessions ls
LEFT JOIN escalation_events ee ON ee.session_id = ls.session_id
GROUP BY 1
ORDER BY 1 DESC;

-- Guardrail trigger rate per agent
CREATE OR REPLACE VIEW guardrail_rate_by_agent AS
SELECT
    tt.speaker AS agent_name,
    COUNT(DISTINCT tt.id) AS total_turns,
    COUNT(DISTINCT ge.id) AS flagged_turns,
    ROUND(
        COUNT(DISTINCT ge.id)::NUMERIC /
        NULLIF(COUNT(DISTINCT tt.id), 0) * 100,
        2
    ) AS flag_rate_pct
FROM transcript_turns tt
LEFT JOIN guardrail_events ge ON ge.session_id = tt.session_id
    AND ge.agent_name = tt.speaker
WHERE tt.role = 'assistant'
GROUP BY 1
ORDER BY 4 DESC;
