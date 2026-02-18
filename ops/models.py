"""
ops.models — Model routing configuration.

Global default:   qwen2.5:14b  (fallback: llama3.2:3b)
Per-agent overrides are stored in ops_agent_config.model_override
and can also be set via environment variables.

This module provides get_model(agent_id) used by workers and agent_mvp.py.
"""
import os
import logging

log = logging.getLogger("ops.models")

# Global defaults from env
DEFAULT_MODEL = os.environ.get("AGENT_OLLAMA_MODEL", "qwen2.5:14b")
FALLBACK_MODEL = os.environ.get("AGENT_OLLAMA_FALLBACK", "llama3.2:3b")

# Static overrides (used when DB is not available)
STATIC_OVERRIDES = {
    "coder": os.environ.get("OPS_MODEL_CODER", "qwen2.5-coder:14b"),
    "marketing": os.environ.get("OPS_MODEL_MARKETING", "qwen2.5-7b-heretic"),
}

# Env-based per-agent override pattern: OPS_MODEL_{AGENT_ID}
# e.g. OPS_MODEL_CODER=qwen2.5-coder:14b


def get_model(agent_id: str = None) -> str:
    """
    Resolve model for a given agent.
    Priority: env override > DB override > static override > global default.
    """
    if agent_id:
        # 1. Check env var override: OPS_MODEL_{AGENT_ID}
        env_key = f"OPS_MODEL_{agent_id.upper()}"
        env_val = os.environ.get(env_key)
        if env_val:
            return env_val

        # 2. Check DB override (graceful if DB not available)
        try:
            from ops.db import fetchone
            row = fetchone(
                "SELECT model_override FROM ops_agent_config WHERE agent_id = %s",
                (agent_id,),
            )
            if row and row.get("model_override"):
                return row["model_override"]
        except Exception:
            pass

        # 3. Static overrides
        if agent_id in STATIC_OVERRIDES and STATIC_OVERRIDES[agent_id]:
            return STATIC_OVERRIDES[agent_id]

    return DEFAULT_MODEL


def get_fallback() -> str:
    """Get the fallback model."""
    return FALLBACK_MODEL


def list_routing_table() -> dict:
    """Return current routing table for diagnostics."""
    table = {
        "default": DEFAULT_MODEL,
        "fallback": FALLBACK_MODEL,
        "overrides": {},
    }

    # Static overrides
    for agent_id, model in STATIC_OVERRIDES.items():
        if model:
            table["overrides"][agent_id] = {"source": "static", "model": model}

    # DB overrides
    try:
        from ops.db import fetchall
        rows = fetchall(
            "SELECT agent_id, model_override FROM ops_agent_config "
            "WHERE model_override IS NOT NULL"
        )
        for row in rows:
            table["overrides"][row["agent_id"]] = {
                "source": "db",
                "model": row["model_override"],
            }
    except Exception:
        pass

    return table
