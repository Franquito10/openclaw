"""
ops.worker_analyze — Worker for 'analyze' step kind.

Atomic claiming via compare-and-swap:
  UPDATE ops_steps SET status='running', worker_id=?, claimed_at=now()
  WHERE id = (SELECT id FROM ops_steps WHERE status='queued' AND kind='analyze'
              ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
  RETURNING *

This ensures only one worker picks up each step.
"""
import os
import json
import time
import logging
import requests
from ops.db import db_cursor, emit_event, fetchone

log = logging.getLogger("ops.worker_analyze")

WORKER_ID = os.environ.get("OPS_WORKER_ID", f"analyze-{os.getpid()}")
POLL_INTERVAL = int(os.environ.get("OPS_WORKER_POLL", "5"))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")

# Model routing: load from DB or env
DEFAULT_MODEL = os.environ.get("AGENT_OLLAMA_MODEL", "qwen2.5:14b")
FALLBACK_MODEL = os.environ.get("AGENT_OLLAMA_FALLBACK", "llama3.2:3b")


def _get_model_for_agent(agent_id: str = None) -> str:
    """Get model for agent, checking DB config first."""
    if agent_id:
        try:
            row = fetchone(
                "SELECT model_override FROM ops_agent_config WHERE agent_id = %s",
                (agent_id,),
            )
            if row and row.get("model_override"):
                return row["model_override"]
        except Exception:
            pass
    return DEFAULT_MODEL


def _call_ollama(prompt: str, model: str = None) -> str:
    """Call Ollama API. Falls back to FALLBACK_MODEL on failure."""
    model = model or DEFAULT_MODEL
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=600,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()
    except Exception as e:
        if model != FALLBACK_MODEL:
            log.warning("Model %s failed (%s), trying fallback %s", model, e, FALLBACK_MODEL)
            return _call_ollama(prompt, FALLBACK_MODEL)
        raise


def claim_step() -> dict | None:
    """
    Atomically claim one queued 'analyze' step.
    Returns step dict or None if nothing available.
    """
    with db_cursor() as (conn, cur):
        cur.execute(
            """
            UPDATE ops_steps
            SET status = 'running', worker_id = %s, claimed_at = now()
            WHERE id = (
                SELECT id FROM ops_steps
                WHERE status = 'queued' AND kind = 'analyze'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (WORKER_ID,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def process_step(step: dict):
    """Process a claimed step: call LLM, write output, mark complete."""
    step_id = step["id"]
    mission_id = step["mission_id"]
    step_input = step.get("input") or {}
    if isinstance(step_input, str):
        step_input = json.loads(step_input)

    title = step.get("title", "Analysis")
    kind = step_input.get("kind", "analysis")

    # Build prompt
    prompt = (
        f"You are an analysis agent. Perform the following task:\n\n"
        f"Task: {title}\n"
        f"Kind: {kind}\n"
        f"Context: {json.dumps(step_input)}\n\n"
        f"Provide a thorough analysis. Be concise but complete."
    )

    # Determine agent for model routing
    agent_id = step_input.get("agent_id")
    model = _get_model_for_agent(agent_id)

    emit_event(
        "step.started",
        source=WORKER_ID,
        payload={"step_id": str(step_id), "model": model},
    )

    try:
        result = _call_ollama(prompt, model)

        # Mark step completed
        with db_cursor() as (conn, cur):
            cur.execute(
                "UPDATE ops_steps SET status = 'completed', "
                "output = %s, completed_at = now() WHERE id = %s",
                (json.dumps({"result": result, "model": model}), step_id),
            )

        emit_event(
            "step.completed",
            source=WORKER_ID,
            payload={
                "step_id": str(step_id),
                "mission_id": str(mission_id),
                "model": model,
            },
        )
        log.info("Step %s completed (model=%s)", step_id, model)

        # Check if all steps in mission are done
        _check_mission_completion(mission_id)

    except Exception as e:
        log.error("Step %s failed: %s", step_id, e)
        with db_cursor() as (conn, cur):
            cur.execute(
                "UPDATE ops_steps SET status = 'failed', "
                "output = %s, completed_at = now() WHERE id = %s",
                (json.dumps({"error": str(e)}), step_id),
            )
        emit_event(
            "step.failed",
            source=WORKER_ID,
            payload={"step_id": str(step_id), "error": str(e)},
        )


def _check_mission_completion(mission_id):
    """If all steps are completed, mark mission as completed."""
    with db_cursor() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) AS total, "
            "COUNT(*) FILTER (WHERE status = 'completed') AS done, "
            "COUNT(*) FILTER (WHERE status = 'failed') AS failed "
            "FROM ops_steps WHERE mission_id = %s",
            (mission_id,),
        )
        row = cur.fetchone()
        total, done, failed = row[0], row[1], row[2]

        if done + failed == total:
            new_status = "completed" if failed == 0 else "failed"
            cur.execute(
                "UPDATE ops_missions SET status = %s, completed_at = now() "
                "WHERE id = %s AND status = 'active'",
                (new_status, mission_id),
            )
            if cur.rowcount:
                emit_event(
                    "mission.completed",
                    source=WORKER_ID,
                    payload={
                        "mission_id": str(mission_id),
                        "status": new_status,
                        "steps_done": done,
                        "steps_failed": failed,
                    },
                )
                log.info(
                    "Mission %s → %s (done=%d, failed=%d)",
                    mission_id, new_status, done, failed,
                )


def run_worker_loop():
    """Main worker loop: claim → process → repeat."""
    log.info("Worker %s starting (kind=analyze, poll=%ds)", WORKER_ID, POLL_INTERVAL)
    while True:
        try:
            step = claim_step()
            if step:
                log.info("Claimed step %s: %s", step["id"], step["title"])
                process_step(step)
            else:
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info("Worker %s stopped.", WORKER_ID)
            break
        except Exception as e:
            log.error("Worker loop error: %s", e)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    run_worker_loop()
