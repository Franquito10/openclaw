"""Tests for ops.compat bridge."""
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


class TestCompat:
    def test_scan_inbox_detects_new_task(self, tmp_path):
        """New .txt file in inbox should emit event."""
        from ops import compat

        events = []

        def mock_emit(kind, payload=None):
            events.append({"kind": kind, "payload": payload})

        # Point compat at tmp dir
        old_inbox = compat.INBOX
        compat.INBOX = str(tmp_path)
        compat._seen_inbox = set()

        try:
            with patch("ops.compat._emit", side_effect=mock_emit):
                # Create a task file
                (tmp_path / "test_task.txt").write_text("hello")
                compat.scan_inbox()

                assert len(events) == 1
                assert events[0]["kind"] == "file.task_created"
                assert events[0]["payload"]["filename"] == "test_task.txt"
        finally:
            compat.INBOX = old_inbox

    def test_scan_inbox_detects_completion(self, tmp_path):
        """New .txt.done file should emit completion event."""
        from ops import compat

        events = []

        def mock_emit(kind, payload=None):
            events.append({"kind": kind, "payload": payload})

        old_inbox = compat.INBOX
        compat.INBOX = str(tmp_path)
        compat._seen_inbox = set()

        try:
            with patch("ops.compat._emit", side_effect=mock_emit):
                (tmp_path / "test_task.txt.done").write_text("done")
                compat.scan_inbox()

                task_completed = [e for e in events if e["kind"] == "file.task_completed"]
                assert len(task_completed) == 1
        finally:
            compat.INBOX = old_inbox

    def test_scan_ignores_already_seen(self, tmp_path):
        """Already-seen files should not re-emit events."""
        from ops import compat

        events = []

        def mock_emit(kind, payload=None):
            events.append({"kind": kind})

        old_inbox = compat.INBOX
        compat.INBOX = str(tmp_path)
        compat._seen_inbox = set()

        try:
            with patch("ops.compat._emit", side_effect=mock_emit):
                (tmp_path / "task.txt").write_text("hi")
                compat.scan_inbox()
                count_after_first = len(events)

                compat.scan_inbox()
                assert len(events) == count_after_first  # No new events
        finally:
            compat.INBOX = old_inbox

    def test_scan_outputs_detects_new(self, tmp_path):
        """New .md file in outputs should emit event."""
        from ops import compat

        events = []

        def mock_emit(kind, payload=None):
            events.append({"kind": kind, "payload": payload})

        old_out = compat.OUT
        compat.OUT = str(tmp_path)
        compat._seen_outputs = set()

        try:
            with patch("ops.compat._emit", side_effect=mock_emit):
                (tmp_path / "result.md").write_text("# Result")
                compat.scan_outputs()

                assert len(events) == 1
                assert events[0]["kind"] == "file.output_created"
        finally:
            compat.OUT = old_out
