# F0 Spec: Closed Loop Minimum

## Summary
Establish the Vox-style closed-loop foundation on top of the existing OpenClaw
file-based system. PostgreSQL as source of truth, proposal service as single
entry point, heartbeat for periodic evaluation, one worker with atomic claiming.

## Database Schema

### ops_proposals
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | gen_random_uuid() |
| agent_id | text NOT NULL | proposing agent |
| kind | text NOT NULL | e.g. 'content', 'deploy', 'analysis' |
| title | text NOT NULL | |
| body | text | details |
| status | text NOT NULL | 'pending','approved','rejected','completed' |
| policy_snapshot | jsonb | policy state at creation time |
| created_at | timestamptz | |
| decided_at | timestamptz | |

### ops_missions
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| proposal_id | uuid FK → ops_proposals | |
| title | text NOT NULL | |
| status | text NOT NULL | 'active','completed','failed' |
| created_at | timestamptz | |
| completed_at | timestamptz | |

### ops_steps
| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| mission_id | uuid FK → ops_missions | |
| kind | text NOT NULL | 'analyze','generate','review','publish' |
| title | text NOT NULL | |
| input | jsonb | |
| output | jsonb | |
| status | text NOT NULL | 'queued','running','completed','failed' |
| worker_id | text | which worker claimed it |
| claimed_at | timestamptz | |
| completed_at | timestamptz | |
| created_at | timestamptz | |

### ops_events
| Column | Type | Notes |
|--------|------|-------|
| id | bigserial PK | |
| kind | text NOT NULL | event type |
| source | text | originating component |
| payload | jsonb | |
| created_at | timestamptz | |

### ops_policy
| Column | Type | Notes |
|--------|------|-------|
| key | text PK | e.g. 'auto_approve', 'tweet_quota' |
| value | jsonb NOT NULL | |
| updated_at | timestamptz | |

### ops_action_runs
| Column | Type | Notes |
|--------|------|-------|
| id | bigserial PK | |
| action | text NOT NULL | heartbeat action name |
| status | text NOT NULL | 'ok','error' |
| details | jsonb | |
| duration_ms | integer | |
| created_at | timestamptz | |

### ops_agent_config
| Column | Type | Notes |
|--------|------|-------|
| agent_id | text PK | |
| display_name | text | |
| model_override | text | ollama model name |
| role | text | pm, coder, research, qa, ops, marketing |
| config | jsonb | extra config |
| created_at | timestamptz | |

## Proposal Service
- `create_proposal(agent_id, kind, title, body)` → proposal row
- Check policy gates: daily caps, kind-specific rules
- If `auto_approve` policy allows, auto-approve → create mission + steps
- Log event for every state change

## Heartbeat (every 5 min)
Actions:
1. `recoverStaleSteps` — steps running > 30min → failed, re-queue
2. `logHeartbeat` — record action_run

(F1 adds: evaluateTriggers, processReactionQueue, etc.)

## Worker (analyze)
- Poll loop: attempt atomic claim `UPDATE ops_steps SET status='running', worker_id=? WHERE status='queued' AND kind='analyze' LIMIT 1 RETURNING *`
- Process step: call LLM with step.input, write step.output
- Mark completed or failed
- Emit events

## API Endpoints (prefix /api/ops/)
- `POST /api/ops/proposals` — create proposal
- `GET  /api/ops/proposals` — list proposals
- `GET  /api/ops/missions` — list missions
- `GET  /api/ops/missions/{id}` — mission detail + steps
- `POST /api/ops/heartbeat` — trigger heartbeat manually
- `GET  /api/ops/events` — recent events (last 100)

## Security Hardening
- Bind 127.0.0.1 by default
- API key required for /api/* (except /api/status)
- Body limit 1MB
- CORS restricted to localhost
- Security headers (nosniff, DENY, no-referrer)
- Path traversal validation on /api/out/{name}

## Compat Layer
- On file creation in inbox: also insert ops_event
- On file completion (*.done): also insert ops_event
- Agent_mvp.py emits events to DB when processing tasks
