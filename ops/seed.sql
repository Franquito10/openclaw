-- OpenClaw Ops Seed Data — F0
-- Run: psql $DATABASE_URL -f ops/seed.sql

-- Default policy
INSERT INTO ops_policy (key, value) VALUES
    ('auto_approve', '{"enabled": true, "kinds": ["analysis", "content", "research"]}'),
    ('daily_proposal_cap', '{"max": 50}'),
    ('content_cap', '{"max_per_day": 20}'),
    ('deploy_policy', '{"requires_review": true}'),
    ('tweet_quota', '{"max_per_day": 10}'),
    ('stale_step_timeout_min', '{"value": 30}')
ON CONFLICT (key) DO NOTHING;

-- Default agent configs
INSERT INTO ops_agent_config (agent_id, display_name, model_override, role) VALUES
    ('pm',        'Project Manager', NULL,                    'pm'),
    ('research',  'Researcher',      NULL,                    'research'),
    ('coder',     'Developer',       'qwen2.5-coder:14b',    'coder'),
    ('qa',        'QA Engineer',     NULL,                    'qa'),
    ('ops',       'Operations',      NULL,                    'ops'),
    ('marketing', 'Marketing',       'qwen2.5-7b-heretic',   'marketing')
ON CONFLICT (agent_id) DO NOTHING;
