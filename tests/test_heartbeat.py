"""Tests for ops.heartbeat."""
import pytest
from unittest.mock import patch
from ops.heartbeat import run_heartbeat_once, recover_stale_steps


class TestHeartbeat:
    def test_heartbeat_runs_all_actions(self, mock_db):
        """Heartbeat should run all registered actions."""
        results = run_heartbeat_once()
        assert len(results) >= 2
        action_names = [r["action"] for r in results]
        assert "recoverStaleSteps" in action_names
        assert "logHeartbeat" in action_names

    def test_heartbeat_records_action_runs(self, mock_db):
        """Each action should create an ops_action_runs entry."""
        run_heartbeat_once()
        # Check that action_runs were recorded
        runs = mock_db.tables["action_runs"]
        assert len(runs) >= 2

    def test_heartbeat_all_ok(self, mock_db):
        """All heartbeat actions should succeed."""
        results = run_heartbeat_once()
        for r in results:
            assert r["status"] == "ok", f"Action {r['action']} failed"

    def test_recover_stale_steps_empty(self, mock_db):
        """No stale steps → recovered = 0."""
        result = recover_stale_steps()
        assert result["recovered"] == 0

    def test_heartbeat_emits_tick_event(self, mock_db):
        """Heartbeat should emit a heartbeat.tick event."""
        run_heartbeat_once()
        tick_events = [e for e in mock_db.events if e["kind"] == "heartbeat.tick"]
        assert len(tick_events) >= 1
