"""
ops.proposal_service — Central entry point for all work creation.

Every proposal (from API, triggers, reactions, initiative, roundtable)
goes through createProposalAndMaybeAutoApprove().
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from ops.db import fetchone, fetchall, execute_returning, emit_event, get_policy

log = logging.getLogger("ops.proposal_service")

# ---- Step templates per proposal kind ----
STEP_TEMPLATES = {
    "analysis": [
        {"kind": "analyze", "title": "Run analysis"},
    ],
    "content": [
        {"kind": "analyze", "title": "Research topic"},
        {"kind": "generate", "title": "Generate content"},
        {"kind": "review", "title": "Review content"},
    ],
    "research": [
        {"kind": "analyze", "title": "Deep research"},
    ],
    "deploy": [
        {"kind": "analyze", "title": "Pre-deploy checks"},
        {"kind": "review", "title": "Deploy review"},
        {"kind": "publish", "title": "Execute deploy"},
    ],
}


def _check_daily_cap(agent_id: str) -> tuple[bool, str]:
    """Check if agent has exceeded daily proposal cap."""
    policy = get_policy("daily_proposal_cap", {"max": 50})
    max_daily = policy.get("max", 50)

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = fetchone(
        "SELECT COUNT(*) AS cnt FROM ops_proposals "
        "WHERE agent_id = %s AND created_at >= %s",
        (agent_id, today_start),
    )
    count = row["cnt"] if row else 0
    if count >= max_daily:
        return False, f"Daily cap reached: {count}/{max_daily}"
    return True, ""


def _check_kind_cap(kind: str) -> tuple[bool, str]:
    """Check kind-specific caps (e.g. content_cap, tweet_quota)."""
    cap_key = f"{kind}_cap"
    policy = get_policy(cap_key)
    if policy is None:
        return True, ""

    max_per_day = policy.get("max_per_day", 999)
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = fetchone(
        "SELECT COUNT(*) AS cnt FROM ops_proposals "
        "WHERE kind = %s AND created_at >= %s",
        (kind, today_start),
    )
    count = row["cnt"] if row else 0
    if count >= max_per_day:
        return False, f"Kind cap '{kind}': {count}/{max_per_day}"
    return True, ""


def _should_auto_approve(kind: str) -> bool:
    """Check if this kind is eligible for auto-approval."""
    policy = get_policy("auto_approve", {"enabled": False, "kinds": []})
    if not policy.get("enabled", False):
        return False
    allowed_kinds = policy.get("kinds", [])
    return kind in allowed_kinds


def _snapshot_policy() -> dict:
    """Capture current policy state for audit."""
    rows = fetchall("SELECT key, value FROM ops_policy")
    return {r["key"]: r["value"] for r in rows}


def _create_mission_and_steps(proposal_id: str, title: str, kind: str) -> dict:
    """Create a mission and its steps from the proposal."""
    mission = execute_returning(
        "INSERT INTO ops_missions (proposal_id, title) "
        "VALUES (%s, %s) RETURNING *",
        (proposal_id, title),
    )
    if not mission:
        return None

    templates = STEP_TEMPLATES.get(kind, [{"kind": "analyze", "title": title}])
    steps = []
    for tmpl in templates:
        step = execute_returning(
            "INSERT INTO ops_steps (mission_id, kind, title, input) "
            "VALUES (%s, %s, %s, %s) RETURNING *",
            (
                mission["id"],
                tmpl["kind"],
                tmpl["title"],
                json.dumps({"proposal_id": str(proposal_id), "kind": kind}),
            ),
        )
        if step:
            steps.append(step)

    emit_event(
        "mission.created",
        source="proposal_service",
        payload={
            "mission_id": str(mission["id"]),
            "proposal_id": str(proposal_id),
            "step_count": len(steps),
        },
    )

    return {"mission": mission, "steps": steps}


def create_proposal_and_maybe_auto_approve(
    agent_id: str, kind: str, title: str, body: str = None
) -> dict:
    """
    Central entry point. Creates a proposal, checks gates, and optionally
    auto-approves it (creating a mission + steps).

    Returns dict with 'proposal' and optionally 'mission'.
    """
    # -- Gate checks --
    ok, reason = _check_daily_cap(agent_id)
    if not ok:
        log.warning("Proposal rejected (daily cap): %s — %s", agent_id, reason)
        emit_event(
            "proposal.rejected",
            source="proposal_service",
            payload={"agent_id": agent_id, "kind": kind, "reason": reason},
        )
        return {"error": reason, "proposal": None}

    ok, reason = _check_kind_cap(kind)
    if not ok:
        log.warning("Proposal rejected (kind cap): %s — %s", kind, reason)
        emit_event(
            "proposal.rejected",
            source="proposal_service",
            payload={"agent_id": agent_id, "kind": kind, "reason": reason},
        )
        return {"error": reason, "proposal": None}

    # -- Create proposal --
    snapshot = _snapshot_policy()
    proposal = execute_returning(
        "INSERT INTO ops_proposals (agent_id, kind, title, body, policy_snapshot) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING *",
        (agent_id, kind, title, body, json.dumps(snapshot)),
    )

    emit_event(
        "proposal.created",
        source="proposal_service",
        payload={
            "proposal_id": str(proposal["id"]),
            "agent_id": agent_id,
            "kind": kind,
        },
    )

    result = {"proposal": proposal, "mission": None}

    # -- Auto-approve check --
    if _should_auto_approve(kind):
        execute_returning(
            "UPDATE ops_proposals SET status = 'approved', decided_at = now() "
            "WHERE id = %s RETURNING id",
            (proposal["id"],),
        )
        proposal["status"] = "approved"

        emit_event(
            "proposal.approved",
            source="proposal_service",
            payload={
                "proposal_id": str(proposal["id"]),
                "auto": True,
            },
        )

        mission_data = _create_mission_and_steps(
            proposal["id"], title, kind
        )
        if mission_data:
            result["mission"] = mission_data

        log.info(
            "Proposal auto-approved: %s [%s] by %s",
            title, kind, agent_id,
        )
    else:
        log.info(
            "Proposal pending review: %s [%s] by %s",
            title, kind, agent_id,
        )

    return result


def approve_proposal(proposal_id: str) -> dict:
    """Manually approve a pending proposal."""
    proposal = fetchone(
        "SELECT * FROM ops_proposals WHERE id = %s", (proposal_id,)
    )
    if not proposal:
        return {"error": "Proposal not found"}
    if proposal["status"] != "pending":
        return {"error": f"Proposal is '{proposal['status']}', not 'pending'"}

    execute_returning(
        "UPDATE ops_proposals SET status = 'approved', decided_at = now() "
        "WHERE id = %s RETURNING id",
        (proposal_id,),
    )

    emit_event(
        "proposal.approved",
        source="proposal_service",
        payload={"proposal_id": str(proposal_id), "auto": False},
    )

    mission_data = _create_mission_and_steps(
        proposal_id, proposal["title"], proposal["kind"]
    )
    return {"proposal_id": proposal_id, "mission": mission_data}


def reject_proposal(proposal_id: str, reason: str = None) -> dict:
    """Reject a pending proposal."""
    result = execute_returning(
        "UPDATE ops_proposals SET status = 'rejected', decided_at = now() "
        "WHERE id = %s AND status = 'pending' RETURNING id",
        (proposal_id,),
    )
    if not result:
        return {"error": "Proposal not found or not pending"}

    emit_event(
        "proposal.rejected",
        source="proposal_service",
        payload={"proposal_id": str(proposal_id), "reason": reason},
    )
    return {"ok": True}
