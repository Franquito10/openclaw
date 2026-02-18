# OpenClaw Migration Plan — F0 through F5

> Migración progresiva del sistema file-based al modelo Vox (closed loop).
> Cada fase tiene objetivos verificables y checkpoints.

---

## F0: Foundation — Closed Loop Minimum ✦ CURRENT

### Objectives
1. PostgreSQL schema (`ops_*` tables) running locally
2. Proposal service with cap gates and auto-approve
3. Heartbeat (5-min) running core evaluations
4. 1 worker (`analyze`) with atomic claiming (CAS: queued→running)
5. API endpoints `/api/ops/*` for proposals and missions
6. Security hardening of `dashboard_api.py`
7. Compat layer: file events replicated to `ops_events`
8. Model routing (per-agent override) + models-lab setup
9. A/B test script for heretic vs base model
10. Smoke tests, seed data, systemd units

### Checkpoints
- [ ] `POST /api/ops/proposals` creates a proposal, returns ID
- [ ] Auto-approved proposal creates a mission + steps
- [ ] Worker picks up `analyze` step via atomic claim
- [ ] Heartbeat runs and logs action_runs
- [ ] Legacy `/api/submit` still works
- [ ] `dashboard_api.py` rejects requests without API key
- [ ] `python -m pytest tests/` passes

---

## F1: Triggers + Reaction Queue + Stale Recovery

### Objectives
1. `ops_triggers` table: condition-based event matching
2. `ops_reactions` table: queued reactions with cooldown
3. Heartbeat additions: `evaluateTriggers`, `processReactionQueue`
4. Stale step recovery: running > 30min → mark failed, re-queue
5. Stale roundtable recovery (prep for F2)

### Checkpoints
- [ ] Trigger fires on specific event type → creates reaction
- [ ] Reaction with cooldown skips if fired recently
- [ ] Stale step automatically re-queued
- [ ] New heartbeat actions logged in `ops_action_runs`

---

## F2: Roundtable + Memory Distillation + Action Items

### Objectives
1. `ops_roundtables`, `ops_roundtable_turns` tables
2. Roundtable config: voices, schedule, max_turns, char_cap (120)
3. Speaker selection: affinity + recency + jitter
4. Turn-by-turn LLM calls with character limit
5. `ops_agent_memory` table: types (insight/pattern/strategy/preference/lesson)
6. Memory: confidence scores, dedup via `source_trace_id`, cap per agent
7. Distillation: roundtable summary → memory entries
8. Action items from roundtable → proposal service

### Checkpoints
- [ ] Roundtable runs with 3+ agents, respects turn caps
- [ ] Memory entries created with correct types and confidence
- [ ] Duplicate memory deduplicated by trace ID
- [ ] Action items become proposals via proposal service
- [ ] Memory influence probability ~0.3 in prompts

---

## F3: Relationships + Drift

### Objectives
1. `ops_agent_relationships` table: agent pairs, affinity score
2. Drift: clamp ±0.03 per interaction, floor 0.0, ceiling 1.0
3. Drift log in `ops_events`
4. Integration: speaker selection weighted by relationship affinity
5. Integration: format/tone selection influenced by relationship

### Checkpoints
- [ ] Relationship scores update after agent interactions
- [ ] Drift clamped correctly (never jumps > 0.03)
- [ ] Speaker selection prefers higher-affinity agents
- [ ] Relationship changes logged as events

---

## F4: Initiative + Voice Evolution

### Objectives
1. Initiative queue: heartbeat enqueues initiative checks
2. Initiative worker: uses cheap model to generate proposals
3. Initiative proposals go through proposal-service gates
4. Voice config per agent: base personality traits
5. Voice evolution: rule-driven from memory stats
6. Voice injection into all agent prompts

### Checkpoints
- [ ] Agents generate initiative proposals autonomously
- [ ] Initiative proposals respect policy caps
- [ ] Voice evolves based on accumulated memory patterns
- [ ] Voice differences visible in agent outputs

---

## F5: Stage Frontend + Pixel Office (Optional)

### Objectives
1. New `/stage` page: observable mission control
2. Signal feed: virtualized list of events (real-time via SSE or polling)
3. Missions list: expand/collapse with step timeline
4. Mission playback: replay step-by-step execution
5. Error boundaries + skeleton loaders
6. (Optional) Pixel office: visual agent representation

### Checkpoints
- [ ] `/stage` page loads with live signal feed
- [ ] Mission details expand to show steps + events
- [ ] Playback mode replays mission timeline
- [ ] Page handles 1000+ events without lag (virtualization)
- [ ] Graceful error states with skeleton fallbacks

---

## Cross-Cutting Rules

1. **No breaking changes:** Legacy routes (`/api/status`, `/api/inbox`, etc.) always work
2. **New routes use `/api/ops/*` prefix**
3. **Each phase writes a spec** (`specs/Fx_*.md`) before implementation
4. **Each phase adds tests** that pass before moving on
5. **Compat layer stays active** until all consumers migrated
6. **models-lab/ is fully isolated** — no torch/transformers in main runtime
