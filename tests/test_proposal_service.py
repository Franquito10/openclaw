"""Tests for ops.proposal_service."""
import pytest
from ops.proposal_service import (
    create_proposal_and_maybe_auto_approve,
    approve_proposal,
    reject_proposal,
)


class TestCreateProposal:
    def test_auto_approve_analysis(self, mock_db):
        """Analysis kind should be auto-approved per default policy."""
        result = create_proposal_and_maybe_auto_approve(
            agent_id="pm",
            kind="analysis",
            title="Test analysis",
            body="Analyze something",
        )
        assert result["proposal"] is not None
        assert result["proposal"]["status"] == "approved"
        assert result["mission"] is not None
        assert result["mission"]["mission"] is not None
        assert len(result["mission"]["steps"]) >= 1

    def test_auto_approve_content(self, mock_db):
        """Content kind should be auto-approved and create 3 steps."""
        result = create_proposal_and_maybe_auto_approve(
            agent_id="marketing",
            kind="content",
            title="Write blog post",
        )
        assert result["proposal"]["status"] == "approved"
        steps = result["mission"]["steps"]
        assert len(steps) == 3
        kinds = [s["kind"] for s in steps]
        assert "analyze" in kinds
        assert "generate" in kinds
        assert "review" in kinds

    def test_deploy_not_auto_approved(self, mock_db):
        """Deploy kind should NOT be auto-approved."""
        result = create_proposal_and_maybe_auto_approve(
            agent_id="ops",
            kind="deploy",
            title="Deploy v2",
        )
        assert result["proposal"]["status"] == "pending"
        assert result["mission"] is None

    def test_daily_cap_blocks(self, mock_db):
        """Once daily cap is reached, proposals are rejected."""
        mock_db.policy["daily_proposal_cap"] = {"max": 0}
        result = create_proposal_and_maybe_auto_approve(
            agent_id="pm",
            kind="analysis",
            title="Should be blocked",
        )
        assert result.get("error") is not None
        assert result["proposal"] is None

    def test_events_emitted(self, mock_db):
        """Creating a proposal should emit events."""
        create_proposal_and_maybe_auto_approve(
            agent_id="pm",
            kind="analysis",
            title="Event test",
        )
        event_kinds = [e["kind"] for e in mock_db.events]
        assert "proposal.created" in event_kinds
        assert "proposal.approved" in event_kinds
        assert "mission.created" in event_kinds


class TestApproveProposal:
    def test_approve_pending(self, mock_db):
        """Manually approving a pending proposal should work."""
        # Create a deploy proposal (won't auto-approve)
        result = create_proposal_and_maybe_auto_approve(
            agent_id="ops",
            kind="deploy",
            title="Deploy v3",
        )
        pid = result["proposal"]["id"]
        assert result["proposal"]["status"] == "pending"

        # Now approve it
        approve_result = approve_proposal(pid)
        assert "error" not in approve_result
        assert approve_result.get("mission") is not None

    def test_approve_nonexistent(self, mock_db):
        """Approving a non-existent proposal returns error."""
        result = approve_proposal("00000000-0000-0000-0000-000000000000")
        assert "error" in result


class TestRejectProposal:
    def test_reject_pending(self, mock_db):
        """Rejecting a pending proposal should work."""
        result = create_proposal_and_maybe_auto_approve(
            agent_id="ops",
            kind="deploy",
            title="Deploy to reject",
        )
        pid = result["proposal"]["id"]
        reject_result = reject_proposal(pid, reason="Not ready")
        assert reject_result.get("ok") is True
