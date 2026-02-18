"""
ops.heartbeat — Periodic evaluation loop (5-min cycle).

F0 actions:
  - recoverStaleSteps: running > 30min → failed, re-queue
  - logHeartbeat: record that heartbeat ran

F1+ will add: evaluateTriggers, processReactionQueue, promoteInsights,
learnFromOutcomes, recoverStaleRoundtables.
"""
import time
import json
import logging
from datetime import datetime, timezone, timedelta
from ops.db import fetchall, execute, execute_returning, emit_event, get_policy

log = logging.getLogger("ops.heartbeat")

HEARTBEAT_INTERVAL = int(
    __import__("os").environ.get("OPS_HEARTBEAT_INTERVAL", "300")
)  # seconds, default 5 min


def _run_action(name: str, fn) -> dict:
    """Run a heartbeat action, measure time, return result."""
    t0 = time.monotonic()
    try:
        details = fn()
        duration = int((time.monotonic() - t0) * 1000)
        execute(
            "INSERT INTO ops_action_runs (action, status, details, duration_ms) "
            "VALUES (%s, 'ok', %s, %s)",
            (name, json.dumps(details or {}), duration),
        )
        return {"action": name, "status": "ok", "duration_ms": duration}
    except Exception as e:
        duration = int((time.monotonic() - t0) * 1000)
        log.error("Heartbeat action '%s' failed: %s", name, e)
        execute(
            "INSERT INTO ops_action_runs (action, status, details, duration_ms) "
            "VALUES (%s, 'error', %s, %s)",
            (name, json.dumps({"error": str(e)}), duration),
        )
        return {"action": name, "status": "error", "error": str(e)}


# ---- Actions ----

def recover_stale_steps() -> dict:
    """
    Steps that have been 'running' for longer than the configured timeout
    are marked 'failed' and a new 'queued' copy is created (re-queue).
    """
    timeout_policy = get_policy("stale_step_timeout_min", {"value": 30})
    timeout_min = timeout_policy.get("value", 30)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_min)

    stale = fetchall(
        "SELECT id, mission_id, kind, title, input FROM ops_steps "
        "WHERE status = 'running' AND claimed_at < %s",
        (cutoff,),
    )

    recovered = 0
    for step in stale:
        # Mark old step as failed
        execute(
            "UPDATE ops_steps SET status = 'failed', completed_at = now() "
            "WHERE id = %s",
            (step["id"],),
        )

        # Re-queue a fresh copy
        execute(
            "INSERT INTO ops_steps (mission_id, kind, title, input) "
            "VALUES (%s, %s, %s, %s)",
            (step["mission_id"], step["kind"], step["title"],
             json.dumps(step["input"]) if step["input"] else None),
        )

        emit_event(
            "step.recovered",
            source="heartbeat",
            payload={
                "old_step_id": str(step["id"]),
                "kind": step["kind"],
                "timeout_min": timeout_min,
            },
        )
        recovered += 1

    if recovered:
        log.info("Recovered %d stale steps (timeout=%dmin)", recovered, timeout_min)

    return {"recovered": recovered, "timeout_min": timeout_min}


def log_heartbeat() -> dict:
    """Record that heartbeat ran."""
    emit_event("heartbeat.tick", source="heartbeat")
    return {"tick": True}


# ---- Main loop ----

ACTIONS = [
    ("recoverStaleSteps", recover_stale_steps),
    ("logHeartbeat", log_heartbeat),
    # F1+: ("evaluateTriggers", evaluate_triggers),
    # F1+: ("processReactionQueue", process_reaction_queue),
    # F2+: ("promoteInsights", promote_insights),
    # F2+: ("learnFromOutcomes", learn_from_outcomes),
    # F1+: ("recoverStaleRoundtables", recover_stale_roundtables),
]


def run_heartbeat_once() -> list[dict]:
    """Execute all heartbeat actions, return results."""
    log.info("Heartbeat tick starting (%d actions)", len(ACTIONS))
    results = []
    for name, fn in ACTIONS:
        r = _run_action(name, fn)
        results.append(r)
        log.info("  %s → %s (%dms)", name, r["status"], r.get("duration_ms", 0))
    return results


def run_heartbeat_loop():
    """Run heartbeat forever with configured interval."""
    log.info("Heartbeat loop starting (interval=%ds)", HEARTBEAT_INTERVAL)
    while True:
        try:
            run_heartbeat_once()
        except Exception as e:
            log.error("Heartbeat loop error: %s", e)
        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    run_heartbeat_loop()
