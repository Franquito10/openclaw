# OpenClaw Agent System — Architecture Document

> Generated 2026-02-18. Source of truth for current state + migration target.

## 1. Current State (Pre-Migration)

### Stack
- **Language:** Python 3.12, stdlib + requests
- **Runtime:** WSL2 Ubuntu on Windows 11
- **LLM:** Ollama (default llama3.1:8b) with optional Claude CLI fallback
- **Persistence:** File-based (txt/md/json)
- **Service:** systemd user service `agent-mvp.service`

### Directory Layout
```
~/workspace/
├── repo/                  # This repository
│   ├── agent_mvp.py       # Core executor (inbox watcher, 3s poll)
│   ├── conductor.py       # Orchestrator (GOAL_*.txt → subtasks)
│   ├── dashboard_api.py   # HTTP API on port 8787
│   ├── graph_build.py     # Task dependency graph builder
│   ├── index.html         # "Nova" web dashboard
│   └── tools/openclaw/    # CLI tool
├── inbox/                 # Task files (.txt → .txt.done)
├── outputs/               # Result files (.md)
├── logs/                  # Log files
├── approvals/             # EXEC approval tokens (.ok)
└── state/                 # Conductor memory (memory.json)
```

### Data Flow
```
User (Web/CLI) → inbox/*.txt → agent_mvp.py → outputs/*.md
                                     ↑
               conductor.py (GOAL_*.txt → subtasks)
```

### Agent Roles
Detected by `@prefix:` in task text: `pm`, `research`, `coder`, `qa`, `ops`.

### Modes
- **NORMAL:** task → LLM prompt → .md output
- **STRICT:** `STRICT:` prefix, minimal LLM response
- **EXEC:** `EXEC:` prefix, shell command with human approval

### API (port 8787)
| Method | Route              | Purpose                |
|--------|--------------------|------------------------|
| GET    | /api/status        | systemd service status |
| GET    | /api/inbox         | List inbox files       |
| GET    | /api/outputs       | List output files      |
| GET    | /api/out/{name}    | Read output content    |
| GET    | /graph.json        | Task graph             |
| POST   | /api/submit        | Create task            |
| POST   | /api/inbox         | Create task (alias)    |

---

## 2. Migration Target (Vox Architecture)

### Core Concepts
1. **Closed Loop:** Proposal → Mission → Steps → Events → Triggers/Reactions → back
2. **Proposal Service:** Single entry point for all work creation
3. **Policy Table:** JSONB config driving caps, gates, auto-approve rules
4. **Heartbeat:** 5-min timer running evaluations
5. **Workers:** One per step kind, atomic claiming (CAS: queued→running)
6. **Roundtable:** Scheduled multi-agent discussions with turn caps
7. **Memory:** Agent-level insights with confidence + dedup
8. **Relationships:** Agent-to-agent affinity with drift clamping
9. **Initiative:** Agents proposing work autonomously
10. **Voice Evolution:** Rule-driven prompt personality

### Database (PostgreSQL)
Tables: `ops_proposals`, `ops_missions`, `ops_steps`, `ops_events`,
`ops_policy`, `ops_action_runs`, `ops_agent_config`,
`ops_agent_memory`, `ops_agent_relationships`, `ops_triggers`,
`ops_reactions`, `ops_roundtables`, `ops_roundtable_turns`

### Compatibility Layer
During migration, file-based inbox/outputs continue working.
A bridge (`ops/compat.py`) replicates file events into `ops_events`.

---

## 3. Post-Migration Layout
```
~/workspace/
├── repo/
│   ├── agent_mvp.py           # Legacy executor (kept working)
│   ├── conductor.py           # Legacy orchestrator (kept working)
│   ├── dashboard_api.py       # Hardened API (legacy + /api/ops/*)
│   ├── graph_build.py         # Legacy graph
│   ├── index.html             # Dashboard
│   ├── tools/openclaw/        # CLI
│   ├── ops/                   # NEW: Vox-style ops engine
│   │   ├── __init__.py
│   │   ├── db.py              # DB connection + helpers
│   │   ├── schema.sql         # DDL
│   │   ├── seed.sql           # Seed data
│   │   ├── proposal_service.py
│   │   ├── heartbeat.py
│   │   ├── worker_analyze.py
│   │   ├── compat.py          # File↔DB bridge
│   │   ├── models.py          # Model routing
│   │   └── api.py             # /api/ops/* handler
│   ├── scripts/
│   │   ├── setup_db.sh
│   │   ├── migrate.sh
│   │   ├── seed.sh
│   │   └── ab_test_heretic.py
│   ├── tests/
│   ├── systemd/
│   ├── specs/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── .gitignore
└── models-lab/                # NEW: Isolated model lab
    ├── heretic/               # heretic-llm in dedicated venv
    ├── hf/, out/, gguf/
    ├── llama.cpp/
    └── ollama-modelfiles/
```
