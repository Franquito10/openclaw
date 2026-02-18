# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Fuente de verdad para trabajar este repo con Claude Code y mantener compatibilidad durante la migración progresiva.

## 0) Principio rector (no negociable)
**NO greenfield.** Este repo ya funciona (file-based). Toda mejora es **migración progresiva** con **compat layer**.
- El runtime actual (inbox/outputs/approvals + /api/* existentes) debe seguir funcionando durante toda la migración.
- Los cambios se implementan por **fases verificables** (F0…F5).
- Se evita meter dependencias pesadas en el runtime principal.
- Lo "pesado" (Heretic, llama.cpp, transformers/torch, etc.) vive aislado en `~/workspace/models-lab/` con su propio venv.

---

## 1) Entorno real (PC oficina)
**Sistema:** WSL2 Ubuntu + Windows 11
**Python:** 3.12
**Repo:** `~/workspace/repo`

### Componentes actuales (existentes)
- `agent_mvp.py` — executor: consume tareas desde `~/workspace/inbox` y produce `~/workspace/outputs`
- `conductor.py` — planner/orquestador: procesa `GOAL_*.txt`
- `dashboard_api.py` — API local en `:8787`
- `graph_build.py`, `index.html` — dashboard actual
- `tools/openclaw/openclaw` — CLI local (si existe en repo, se respeta; no inventar)

### Persistencia file-based (existente)
- `~/workspace/state/memory.json` — estado conductor
- `~/workspace/inbox/*.txt` y `*.done`
- `~/workspace/outputs/*.md`
- `~/workspace/approvals/*.ok`

### Routing/roles por prefijo (existente)
En prompts/salidas se usan prefijos:
- `@pm:`, `@research:`, `@coder:`, `@qa:`, `@ops:`

**Nota:** esto es "routing lógico del runtime". NO es lo mismo que "agentes de Claude Code".

---

## 2) Agentes de Claude Code (Project agents)
Estos agentes viven en: `.claude/agents/*.md`
Se usan desde Claude Code con `@nombre`.

### Roles y responsabilidades (definitivas)
**Regla de oro:** *Solo un agente debe "conducir" cambios de código por tarea.*
Los demás revisan, auditan, o proponen.

#### Director/Integrador
- `@cto-executor`
  Dueño del diseño técnico y plan de implementación. Integra cambios y define secuencia.

#### Especialistas (reviewers / sign-off)
- `@backend-guardian` — calidad backend, legibilidad, refactor incremental
- `@frontend-architect` — UX + vanilla JS/DOM, sin frameworks
- `@performance-engineer` — cuellos de botella, escalabilidad, I/O, polling, caching
- `@security-auditor` — vulnerabilidades de código (path traversal, subprocess, auth, CORS)
- `@ciso-guardian` — threat modeling sistémico (prompt injection, exfil, ejecución arbitraria)

#### Arquitectura multi-agente
- `@ai-orchestrator` — coordinación, diseño de closed loop, triggers, roundtable, memory, relationships

### Uso recomendado (pipeline)
Para cualquier cambio serio:
1) `@cto-executor` — arquitectura + plan
2) `@backend-guardian` / `@frontend-architect` — review de diseño si aplica
3) Implementación (normalmente la conduce `@cto-executor`)
4) `@ciso-guardian` — *sign-off obligatorio* si toca: subprocess / endpoints / auth / filesystem write / network
5) `@performance-engineer` — *sign-off* si afecta polling, workers, colas, I/O
6) `@security-auditor` — audit de código final (si hay superficie web/FS)

---

## 3) Compatibilidad (endpoints y flujos que NO se rompen)
Durante TODA la migración, deben seguir existiendo:
- `/api/status`
- `/api/inbox`
- `/api/outputs`
- `/api/out/{name}`
- `/api/submit`
- `/graph.json`

**Nuevas rutas**: siempre bajo prefijo:
- `/api/ops/*`

---

## 4) Estrategia de migración por fases (F0…F5)
La migración replica el tutorial de Vox ("6 AI agents that run a company") **1:1 en capítulos**, sin reescritura desde cero.

### F0 — Closed loop mínimo (entregable obligatorio)
**Objetivo:** introducir DB ops_* + proposal-service + heartbeat + 1 worker con atomic claiming, manteniendo compat file-based.

Incluye:
- Schema mínimo: `ops_proposals, ops_missions, ops_steps, ops_events, ops_policy, ops_action_runs`
- `proposal-service` central: `createProposalAndMaybeAutoApprove()`
- Cap gates + policy JSONB (`ops_policy`)
- Heartbeat: endpoint + timer local
- 1 worker (ej: `analyze`) con atomic claiming (UPDATE queued→running con compare-and-swap)
- Endpoints básicos: crear proposal, listar missions
- Smoke tests + seed scripts
- Hardening mínimo del dashboard API (ver sección 8)
- `models-lab/heretic` aislado + override del agente de marketing

**Checkpoint verificable F0**
- `curl /api/ops/proposals` funciona con auth
- Worker reclama steps en forma atómica
- Heartbeat corre cada 5 min y registra `ops_action_runs`
- File-based `/api/submit` sigue funcionando igual

### F1 — Triggers + Reaction Matrix + Queue + stale recovery
Incluye:
- `evaluateTriggers()`
- `processReactionQueue()`
- cooldowns por trigger
- recovery de steps stale
- registro completo en `ops_events`

### F2 — Roundtable + memory distillation + action items
Incluye:
- voices config "tipo voices.ts" pero Python
- speaker selection (affinity + recency + jitter)
- caps: 120 chars por turno
- distillation a memory + action items a proposal-service

### F3 — Relationships + drift
Incluye:
- `ops_agent_relationships` con drift clamp ±0.03
- floor/ceiling
- uso real en speaker selection y format selection

### F4 — Initiative queue + voice evolution
Incluye:
- initiative worker que genera proposals (modelo barato)
- voice evolution rule-driven según stats de memory
- injection controlado al prompt

### F5 — Stage frontend observable
Incluye:
- `/stage` con signal feed virtualizado
- missions list con expand/collapse
- mission playback timeline
- skeletons + error boundaries
- (opcional) pixel office fase posterior

---

## 5) DB: Postgres local (default) / Supabase (opcional)
Por defecto se asume **Postgres local** (Docker o nativo). Supabase cloud es opcional.

### Convención
- Tablas: `ops_*`
- `ops_policy` es **policy-driven config** (JSONB) para gates/caps.
- `ops_events` es event log (source of truth).
- Workers operan sobre `ops_steps` con atomic claiming.

---

## 6) Closed loop (modelo mental operativo)
Ciclo:
**Proposal → Mission → Steps → Events → Triggers/Reactions → back**

Heartbeat (cada 5 min) ejecuta:
- `evaluateTriggers`
- `processReactionQueue`
- `promoteInsights`
- `learnFromOutcomes`
- `recoverStaleSteps`
- `recoverStaleRoundtables`
y registra `ops_action_runs`.

---

## 7) MODELOS / Routing (Heretic solo para 1 agente)
### Defaults
- Global default: `qwen2.5:14b` (preferred) con fallback `llama3.2:3b`
- Dev override: `qwen2.5-coder:14b`
- Marketing override: `qwen2.5-7b-heretic` (solo para "prueba de fuego")

**Regla:** NO cambiar el modelo global por el experimento.

Model routing priority: `OPS_MODEL_{AGENT_ID}` env var → DB `ops_agent_config.model_override` → static overrides (`ops/models.py`) → `AGENT_OLLAMA_MODEL`.

### A/B test controlado
Agregar util de A/B:
- mismo prompt
- parámetros fijos
- mismo `num_predict`
- timeout configurable (default 600s)
- retries configurables
- comparación entre `qwen2.5:7b` vs `qwen2.5-7b-heretic`

---

## 8) HARDENING mínimo del dashboard API (obligatorio)
Objetivo: seguro para uso local.

### Bind
- Default: `127.0.0.1`
- Permitir `0.0.0.0` solo si `MC_BIND_ALL=1`

### Auth por API key
- Todas las rutas `/api/*` requieren:
  `Authorization: Bearer <key>`
- EXCEPTO: `/api/status`
- Env var: `MC_API_KEY`
- Si falta o es incorrecta: `401`

### Request body limit
- Default: `1MB`
- Env: `MC_MAX_BODY=1048576`
- Si excede: `413`

### CORS
- NO usar `*`
- Default permitir solo localhost
- Env: `MC_CORS_ORIGIN="http://localhost:8787"`

### Security headers
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`

### Path traversal fix
- `/api/logs`: validar `agent` y resolver path *dentro* de `LOGS_DIR`
- Si existe `design_director` en este repo: validar `artifact_paths` dentro de `ARTIFACTS_DIR`
- No inventar archivos/clases inexistentes

---

## 9) models-lab (aislado, sin romper runtime)
Crear en `~/workspace/models-lab/` (fuera del runtime principal).

Estructura:
- `heretic/` (repo clonado o instalación heretic-llm) **en venv dedicado**
- `llama.cpp/` (convert/quantizar a GGUF si hace falta)
- `hf/`, `out/`, `gguf/`, `ollama-modelfiles/`

**Regla de aislamiento:**
El runtime principal (OpenClaw) NO depende de torch/transformers/etc.
Todo lo pesado vive en `models-lab` con su propio venv.

---

## 10) Calidad de producción (mínimos)
### Tests
- Smoke tests por fase
- Tests deben correr local en WSL2 sin PostgreSQL real (usa MockDB en `tests/conftest.py`)
- Cada fase incluye: spec → implement → tests → run tests y mostrar output

### Documentación obligatoria por fase
- `ARCHITECTURE.md` (primero: explorar repo y documentar lo que existe)
- `specs/Fx_*.md` por fase
- `README` actualizado con comandos

### .gitignore obligatorio
Ignorar:
- `state/`, `logs/`, `events/`, `artifacts/`, `models-lab/`, `*.env`

---

## 11) Reglas de ejecución (workflow de cambios)
Antes de cambiar código:
1) Explorar repo y escribir/actualizar `ARCHITECTURE.md` con lo encontrado.
2) Escribir spec de fase en `specs/`.
3) Implementar incremental con compat layer.
4) Agregar tests.
5) Correr tests y registrar output.

**Nunca inventar archivos que no existan.**
Si se crean archivos nuevos:
- listarlos
- explicar dónde van
- justificar por qué no rompemos compat

---

## 12) Comandos
**Environment:** Copiar `.env.example` a `.env` y configurar `MC_API_KEY` y `DATABASE_URL`. El venv está en `repo/.venv/`.

### Tests (no requieren PostgreSQL — usan MockDB)
```bash
python -m pytest tests/
python -m pytest tests/test_api.py
python -m pytest tests/test_proposal_service.py::test_auto_approve
```

### Run local
```bash
python dashboard_api.py                  # dashboard API en :8787
python -m ops.heartbeat                  # heartbeat loop
python -m ops.worker_analyze             # analyze step worker
python -m ops.compat                     # file↔DB bridge
```

### DB setup (elegir una)
```bash
bash scripts/setup_db.sh docker    # PostgreSQL via Docker Compose
bash scripts/setup_db.sh native    # instalar PostgreSQL via apt en WSL2
bash scripts/setup_db.sh migrate   # solo correr schema.sql + seed.sql contra DATABASE_URL
```

### A/B test
```bash
python scripts/ab_test_heretic.py --timeout 600 --retries 2 --num_predict 256
```

### Systemd (user services)
```bash
systemctl --user start dashboard-api
systemctl --user start ops-worker-analyze
systemctl --user start ops-compat
systemctl --user start ops-heartbeat
```

---

## 13) "Cómo pedirle cosas a Claude Code" (prompts efectivos)

- Diseño:
  `@cto-executor Diseñá F0 sin romper compat. Entregá spec + pasos + checkpoints.`

- Seguridad:
  `@ciso-guardian Revisá esta propuesta como atacante. Listá riesgos CRITICAL→LOW y mitigaciones.`

- Performance:
  `@performance-engineer Encontrá cuellos de botella y proponé optimizaciones incrementales.`

- Frontend:
  `@frontend-architect Mejorá /stage sin frameworks, con virtualization y playback.`

---

## 14) "Definition of Done" por fase
Una fase está "DONE" solo si:
- compat endpoints siguen funcionando
- spec está escrita
- tests pasan
- comandos de ejecución local están documentados
- hardening no se rompió
- policy/gates existen y se aplican donde corresponde

---

## 15) Seguridad operativa (secrets)
- Guardar secrets en `.env` con `chmod 600`
- Nunca commitear `.env`
- Preferir variables de entorno para llaves y tokens

---

## 16) Nota final
Este repo es un sistema de automatización con ejecución de pasos.
El objetivo es aumentar robustez sin inflar complejidad.
Minimalismo + disciplina > frameworks + magia.
