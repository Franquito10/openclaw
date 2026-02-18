-- OpenClaw Ops Schema — F0: Closed Loop Minimum
-- Run: psql $DATABASE_URL -f ops/schema.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- ops_policy: JSONB key-value config driving caps & gates
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_policy (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ops_agent_config: per-agent settings & model overrides
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_agent_config (
    agent_id      TEXT PRIMARY KEY,
    display_name  TEXT,
    model_override TEXT,
    role          TEXT,
    config        JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- ops_proposals: single entry point for all work
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_proposals (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         TEXT NOT NULL,
    kind             TEXT NOT NULL,
    title            TEXT NOT NULL,
    body             TEXT,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','approved','rejected','completed')),
    policy_snapshot  JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON ops_proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_agent  ON ops_proposals(agent_id);
CREATE INDEX IF NOT EXISTS idx_proposals_created ON ops_proposals(created_at DESC);

-- ============================================================
-- ops_missions: approved proposals become missions
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_missions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id   UUID NOT NULL REFERENCES ops_proposals(id),
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active','completed','failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_missions_status ON ops_missions(status);

-- ============================================================
-- ops_steps: mission work items, claimed by workers
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_steps (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id    UUID NOT NULL REFERENCES ops_missions(id),
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    input         JSONB,
    output        JSONB,
    status        TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','completed','failed')),
    worker_id     TEXT,
    claimed_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_steps_status_kind ON ops_steps(status, kind);
CREATE INDEX IF NOT EXISTS idx_steps_mission     ON ops_steps(mission_id);

-- ============================================================
-- ops_events: append-only event log
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_events (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,
    source      TEXT,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_kind    ON ops_events(kind);
CREATE INDEX IF NOT EXISTS idx_events_created ON ops_events(created_at DESC);

-- ============================================================
-- ops_action_runs: heartbeat action audit log
-- ============================================================
CREATE TABLE IF NOT EXISTS ops_action_runs (
    id          BIGSERIAL PRIMARY KEY,
    action      TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('ok','error')),
    details     JSONB,
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================
-- Future tables (stubs for F1+, created empty now)
-- ============================================================

-- F1: triggers & reactions
CREATE TABLE IF NOT EXISTS ops_triggers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    event_kind  TEXT NOT NULL,
    condition   JSONB NOT NULL DEFAULT '{}',
    action      JSONB NOT NULL DEFAULT '{}',
    enabled     BOOLEAN NOT NULL DEFAULT true,
    cooldown_s  INTEGER NOT NULL DEFAULT 300,
    last_fired  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops_reactions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_id  UUID REFERENCES ops_triggers(id),
    status      TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','processing','completed','failed')),
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

-- F2: memory & roundtable
CREATE TABLE IF NOT EXISTS ops_agent_memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id         TEXT NOT NULL,
    type             TEXT NOT NULL
                     CHECK (type IN ('insight','pattern','strategy','preference','lesson')),
    content          TEXT NOT NULL,
    confidence       REAL NOT NULL DEFAULT 0.5,
    source_trace_id  TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_agent ON ops_agent_memory(agent_id);

CREATE TABLE IF NOT EXISTS ops_roundtables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled','active','completed','failed')),
    config      JSONB NOT NULL DEFAULT '{}',
    summary     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ops_roundtable_turns (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    roundtable_id  UUID NOT NULL REFERENCES ops_roundtables(id),
    agent_id       TEXT NOT NULL,
    content        TEXT NOT NULL,
    turn_number    INTEGER NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- F3: relationships
CREATE TABLE IF NOT EXISTS ops_agent_relationships (
    agent_a     TEXT NOT NULL,
    agent_b     TEXT NOT NULL,
    affinity    REAL NOT NULL DEFAULT 0.5,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_a, agent_b)
);
