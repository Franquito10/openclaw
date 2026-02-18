"""
Shared test fixtures.
Uses a mock DB layer so tests run without PostgreSQL.

We patch at every call site (where `from ops.db import X` is used),
not just at the definition site, because Python binds names at import time.
"""
import sys
import os
import json
import pytest
from unittest.mock import patch
from collections import defaultdict
from uuid import uuid4
from datetime import datetime, timezone

# Ensure repo root is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class MockDB:
    """In-memory mock for ops.db functions."""

    def __init__(self):
        self.tables = defaultdict(list)
        self.policy = {
            "auto_approve": {"enabled": True, "kinds": ["analysis", "content", "research"]},
            "daily_proposal_cap": {"max": 50},
            "content_cap": {"max_per_day": 20},
            "stale_step_timeout_min": {"value": 30},
        }
        self.events = []

    def fetchone(self, sql, params=None):
        if "ops_policy" in sql and "WHERE key" in sql:
            key = params[0] if params else None
            val = self.policy.get(key)
            if val is None:
                return None
            return {"key": key, "value": val}
        if "COUNT(*)" in sql and "ops_proposals" in sql:
            return {"cnt": 0}
        if "ops_proposals" in sql and "WHERE id" in sql:
            pid = str(params[0]) if params else None
            for p in self.tables["proposals"]:
                if str(p["id"]) == pid:
                    return p
            return None
        if "ops_missions" in sql and "WHERE id" in sql:
            mid = str(params[0]) if params else None
            for m in self.tables["missions"]:
                if str(m["id"]) == mid:
                    return m
            return None
        if "ops_agent_config" in sql:
            agent_id = params[0] if params else None
            for c in self.tables["agent_config"]:
                if c["agent_id"] == agent_id:
                    return c
            return None
        if "SELECT 1" in sql:
            return {"ok": 1}
        return None

    def fetchall(self, sql, params=None):
        if "ops_policy" in sql:
            return [{"key": k, "value": v} for k, v in self.policy.items()]
        if "ops_proposals" in sql:
            return self.tables.get("proposals", [])[:50]
        if "ops_missions" in sql:
            return self.tables.get("missions", [])[:50]
        if "ops_steps" in sql:
            if "WHERE mission_id" in sql:
                mid = str(params[0]) if params else None
                return [s for s in self.tables.get("steps", []) if str(s["mission_id"]) == mid]
            return self.tables.get("steps", [])[:50]
        if "ops_events" in sql:
            return self.events[:100]
        if "ops_action_runs" in sql:
            return self.tables.get("action_runs", [])[:50]
        if "ops_agent_config" in sql:
            return self.tables.get("agent_config", [])
        return []

    def execute(self, sql, params=None):
        if "INSERT INTO ops_events" in sql:
            self.events.append({
                "id": len(self.events) + 1,
                "kind": params[0] if params else "unknown",
                "source": params[1] if params and len(params) > 1 else None,
                "payload": json.loads(params[2]) if params and len(params) > 2 and params[2] else None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        if "INSERT INTO ops_action_runs" in sql:
            self.tables["action_runs"].append({
                "id": len(self.tables["action_runs"]) + 1,
                "action": params[0] if params else "unknown",
                "status": params[1] if params and len(params) > 1 else "ok",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        if "UPDATE ops_steps" in sql:
            pass  # Accept silently
        if "UPDATE ops_missions" in sql:
            pass
        return 1

    def execute_returning(self, sql, params=None):
        now = datetime.now(timezone.utc)
        if "INSERT INTO ops_proposals" in sql:
            row = {
                "id": str(uuid4()),
                "agent_id": params[0],
                "kind": params[1],
                "title": params[2],
                "body": params[3] if len(params) > 3 else None,
                "status": "pending",
                "policy_snapshot": json.loads(params[4]) if len(params) > 4 and params[4] else None,
                "created_at": now.isoformat(),
                "decided_at": None,
            }
            self.tables["proposals"].append(row)
            return row
        if "UPDATE ops_proposals" in sql and "approved" in sql:
            pid = str(params[0]) if params else None
            for p in self.tables["proposals"]:
                if str(p["id"]) == pid:
                    p["status"] = "approved"
                    p["decided_at"] = now.isoformat()
                    return {"id": pid}
            return None
        if "UPDATE ops_proposals" in sql and "rejected" in sql:
            pid = str(params[0]) if params else None
            for p in self.tables["proposals"]:
                if str(p["id"]) == pid and p["status"] == "pending":
                    p["status"] = "rejected"
                    return {"id": pid}
            return None
        if "INSERT INTO ops_missions" in sql:
            row = {
                "id": str(uuid4()),
                "proposal_id": str(params[0]),
                "title": params[1],
                "status": "active",
                "created_at": now.isoformat(),
                "completed_at": None,
            }
            self.tables["missions"].append(row)
            return row
        if "INSERT INTO ops_steps" in sql:
            row = {
                "id": str(uuid4()),
                "mission_id": str(params[0]),
                "kind": params[1],
                "title": params[2],
                "input": json.loads(params[3]) if params[3] else None,
                "output": None,
                "status": "queued",
                "worker_id": None,
                "claimed_at": None,
                "completed_at": None,
                "created_at": now.isoformat(),
            }
            self.tables["steps"].append(row)
            return row
        return None

    def emit_event(self, kind, source=None, payload=None):
        self.events.append({
            "id": len(self.events) + 1,
            "kind": kind,
            "source": source,
            "payload": payload,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def get_policy(self, key, default=None):
        return self.policy.get(key, default)

    def ping(self):
        return True


# All modules that do `from ops.db import X` need patching at their own namespace
_PATCH_TARGETS = [
    # (module_path, function_name)
    ("ops.db", "fetchone"),
    ("ops.db", "fetchall"),
    ("ops.db", "execute"),
    ("ops.db", "execute_returning"),
    ("ops.db", "emit_event"),
    ("ops.db", "get_policy"),
    ("ops.db", "ping"),
    # proposal_service imports
    ("ops.proposal_service", "fetchone"),
    ("ops.proposal_service", "fetchall"),
    ("ops.proposal_service", "execute_returning"),
    ("ops.proposal_service", "emit_event"),
    ("ops.proposal_service", "get_policy"),
    # heartbeat imports
    ("ops.heartbeat", "fetchall"),
    ("ops.heartbeat", "execute"),
    ("ops.heartbeat", "execute_returning"),
    ("ops.heartbeat", "emit_event"),
    ("ops.heartbeat", "get_policy"),
    # api imports
    ("ops.api", "fetchall"),
    ("ops.api", "fetchone"),
    ("ops.api", "ping"),
]


@pytest.fixture
def mock_db():
    """Provide a MockDB and patch ops.db functions at all call sites."""
    db = MockDB()

    method_map = {
        "fetchone": db.fetchone,
        "fetchall": db.fetchall,
        "execute": db.execute,
        "execute_returning": db.execute_returning,
        "emit_event": db.emit_event,
        "get_policy": db.get_policy,
        "ping": db.ping,
    }

    patches = []
    for module, func in _PATCH_TARGETS:
        try:
            p = patch(f"{module}.{func}", side_effect=method_map[func])
            p.start()
            patches.append(p)
        except AttributeError:
            pass  # Module not yet imported or function not present

    yield db

    for p in patches:
        p.stop()
