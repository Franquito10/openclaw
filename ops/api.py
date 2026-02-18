"""
ops.api — Handler for /api/ops/* routes.

This module provides a dispatch function called from dashboard_api.py.
It does NOT run its own server.
"""
import json
import logging
from ops.db import fetchall, fetchone, ping
from ops.proposal_service import (
    create_proposal_and_maybe_auto_approve,
    approve_proposal,
    reject_proposal,
)
from ops.heartbeat import run_heartbeat_once

log = logging.getLogger("ops.api")


def handle_ops_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """
    Dispatch /api/ops/* requests.
    Returns (status_code, response_dict).
    """
    try:
        return _dispatch(method, path, body)
    except ImportError as e:
        return 503, {"error": f"Database not available: {e}"}
    except Exception as e:
        log.error("ops.api error: %s", e)
        return 500, {"error": str(e)}


def _dispatch(method: str, path: str, body: dict | None) -> tuple[int, dict]:
    # --- Health ---
    if path == "/api/ops/health":
        ok = ping()
        return 200, {"db": ok}

    # --- Proposals ---
    if path == "/api/ops/proposals" and method == "POST":
        if not body:
            return 400, {"error": "Missing request body"}
        agent_id = body.get("agent_id")
        kind = body.get("kind")
        title = body.get("title")
        if not all([agent_id, kind, title]):
            return 400, {"error": "Required: agent_id, kind, title"}
        result = create_proposal_and_maybe_auto_approve(
            agent_id=agent_id,
            kind=kind,
            title=title,
            body=body.get("body"),
        )
        if result.get("error"):
            return 429, result
        return 201, _serialize(result)

    if path == "/api/ops/proposals" and method == "GET":
        rows = fetchall(
            "SELECT * FROM ops_proposals ORDER BY created_at DESC LIMIT 50"
        )
        return 200, {"proposals": _serialize_list(rows)}

    if path.startswith("/api/ops/proposals/") and "/approve" in path and method == "POST":
        pid = path.split("/api/ops/proposals/")[1].split("/")[0]
        result = approve_proposal(pid)
        if result.get("error"):
            return 400, result
        return 200, _serialize(result)

    if path.startswith("/api/ops/proposals/") and "/reject" in path and method == "POST":
        pid = path.split("/api/ops/proposals/")[1].split("/")[0]
        reason = (body or {}).get("reason")
        result = reject_proposal(pid, reason)
        if result.get("error"):
            return 400, result
        return 200, result

    # --- Missions ---
    if path == "/api/ops/missions" and method == "GET":
        rows = fetchall(
            "SELECT * FROM ops_missions ORDER BY created_at DESC LIMIT 50"
        )
        return 200, {"missions": _serialize_list(rows)}

    if path.startswith("/api/ops/missions/") and method == "GET":
        mid = path.split("/api/ops/missions/")[1].split("/")[0]
        mission = fetchone("SELECT * FROM ops_missions WHERE id = %s", (mid,))
        if not mission:
            return 404, {"error": "Mission not found"}
        steps = fetchall(
            "SELECT * FROM ops_steps WHERE mission_id = %s ORDER BY created_at",
            (mid,),
        )
        return 200, {
            "mission": _serialize_one(mission),
            "steps": _serialize_list(steps),
        }

    # --- Events ---
    if path == "/api/ops/events" and method == "GET":
        rows = fetchall(
            "SELECT * FROM ops_events ORDER BY created_at DESC LIMIT 100"
        )
        return 200, {"events": _serialize_list(rows)}

    # --- Heartbeat (manual trigger) ---
    if path == "/api/ops/heartbeat" and method == "POST":
        results = run_heartbeat_once()
        return 200, {"actions": results}

    # --- Policy ---
    if path == "/api/ops/policy" and method == "GET":
        rows = fetchall("SELECT * FROM ops_policy ORDER BY key")
        return 200, {"policy": _serialize_list(rows)}

    # --- Action runs ---
    if path == "/api/ops/action-runs" and method == "GET":
        rows = fetchall(
            "SELECT * FROM ops_action_runs ORDER BY created_at DESC LIMIT 50"
        )
        return 200, {"action_runs": _serialize_list(rows)}

    return 404, {"error": f"Unknown ops route: {method} {path}"}


# ---- Serialization helpers ----

def _serialize(obj):
    """Recursively convert non-JSON-serializable types."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    # UUID
    if hasattr(obj, "hex") and hasattr(obj, "int"):
        return str(obj)
    return obj


def _serialize_one(row: dict) -> dict:
    return _serialize(row)


def _serialize_list(rows: list) -> list:
    return [_serialize(r) for r in rows]
