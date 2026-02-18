"""Tests for ops.api dispatch."""
import pytest
from ops.api import handle_ops_request


class TestOpsAPI:
    def test_health(self, mock_db):
        code, body = handle_ops_request("GET", "/api/ops/health")
        assert code == 200
        assert body["db"] is True

    def test_create_proposal(self, mock_db):
        code, body = handle_ops_request("POST", "/api/ops/proposals", {
            "agent_id": "pm",
            "kind": "analysis",
            "title": "API test",
        })
        assert code == 201
        assert body["proposal"] is not None

    def test_create_proposal_missing_fields(self, mock_db):
        code, body = handle_ops_request("POST", "/api/ops/proposals", {
            "agent_id": "pm",
        })
        assert code == 400
        assert "error" in body

    def test_list_proposals(self, mock_db):
        # Create one first
        handle_ops_request("POST", "/api/ops/proposals", {
            "agent_id": "pm",
            "kind": "analysis",
            "title": "List test",
        })
        code, body = handle_ops_request("GET", "/api/ops/proposals")
        assert code == 200
        assert "proposals" in body

    def test_list_missions(self, mock_db):
        code, body = handle_ops_request("GET", "/api/ops/missions")
        assert code == 200
        assert "missions" in body

    def test_list_events(self, mock_db):
        code, body = handle_ops_request("GET", "/api/ops/events")
        assert code == 200
        assert "events" in body

    def test_heartbeat_manual(self, mock_db):
        code, body = handle_ops_request("POST", "/api/ops/heartbeat")
        assert code == 200
        assert "actions" in body
        assert len(body["actions"]) >= 2

    def test_policy(self, mock_db):
        code, body = handle_ops_request("GET", "/api/ops/policy")
        assert code == 200
        assert "policy" in body

    def test_unknown_route(self, mock_db):
        code, body = handle_ops_request("GET", "/api/ops/nonexistent")
        assert code == 404


class TestProposalWorkflow:
    def test_full_lifecycle(self, mock_db):
        """Create → auto-approve → mission → steps workflow."""
        # Create proposal (auto-approved)
        code, body = handle_ops_request("POST", "/api/ops/proposals", {
            "agent_id": "research",
            "kind": "research",
            "title": "Deep dive into topic X",
            "body": "We need to understand X better",
        })
        assert code == 201
        assert body["proposal"]["status"] == "approved"
        assert body["mission"] is not None

        # List missions
        code, missions_body = handle_ops_request("GET", "/api/ops/missions")
        assert code == 200
        assert len(missions_body["missions"]) >= 1

    def test_deploy_requires_manual_approval(self, mock_db):
        """Deploy proposals need manual approval."""
        # Create deploy proposal
        code, body = handle_ops_request("POST", "/api/ops/proposals", {
            "agent_id": "ops",
            "kind": "deploy",
            "title": "Deploy v4",
        })
        assert code == 201
        assert body["proposal"]["status"] == "pending"
        assert body["mission"] is None

        # Manually approve
        pid = body["proposal"]["id"]
        code, approve_body = handle_ops_request(
            "POST", f"/api/ops/proposals/{pid}/approve"
        )
        assert code == 200
        assert approve_body.get("mission") is not None
