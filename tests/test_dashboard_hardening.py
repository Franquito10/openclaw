"""Tests for dashboard_api.py security hardening."""
import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestPathTraversal:
    def test_safe_path_normal(self):
        from dashboard_api import _is_safe_path
        assert _is_safe_path("/tmp/outputs", "test.md") is True

    def test_safe_path_traversal_blocked(self):
        from dashboard_api import _is_safe_path
        assert _is_safe_path("/tmp/outputs", "../etc/passwd") is False

    def test_safe_path_double_traversal(self):
        from dashboard_api import _is_safe_path
        assert _is_safe_path("/tmp/outputs", "../../etc/shadow") is False

    def test_safe_path_encoded(self):
        from dashboard_api import _is_safe_path
        # Direct path component test
        assert _is_safe_path("/tmp/outputs", "..%2f..%2fetc%2fpasswd") is True  # Won't resolve
        assert _is_safe_path("/tmp/outputs", "../../../../etc/passwd") is False


class TestSafeFilename:
    def test_normal(self):
        from dashboard_api import safe_filename
        assert safe_filename("test") == "test.txt"

    def test_with_extension(self):
        from dashboard_api import safe_filename
        assert safe_filename("test.txt") == "test.txt"

    def test_sanitize_special_chars(self):
        from dashboard_api import safe_filename
        result = safe_filename("test/../../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_empty(self):
        from dashboard_api import safe_filename
        assert safe_filename("") == "tarea_web.txt"

    def test_none(self):
        from dashboard_api import safe_filename
        assert safe_filename(None) == "tarea_web.txt"


class TestSecurityConfig:
    def test_default_bind_localhost(self):
        """By default, should bind to 127.0.0.1."""
        with patch.dict(os.environ, {"MC_BIND_ALL": "0"}, clear=False):
            # Re-import to pick up env
            import importlib
            import dashboard_api
            importlib.reload(dashboard_api)
            assert dashboard_api.BIND_HOST == "127.0.0.1"

    def test_bind_all_when_enabled(self):
        """MC_BIND_ALL=1 should bind to 0.0.0.0."""
        with patch.dict(os.environ, {"MC_BIND_ALL": "1"}, clear=False):
            import importlib
            import dashboard_api
            importlib.reload(dashboard_api)
            assert dashboard_api.BIND_HOST == "0.0.0.0"


class TestAuthCheck:
    def test_auth_disabled_when_no_key(self):
        """Without MC_API_KEY, all requests should be allowed."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MC_API_KEY", None)
            import importlib
            import dashboard_api
            importlib.reload(dashboard_api)
            handler = MagicMock(spec=dashboard_api.H)
            handler.headers = {}
            dashboard_api.API_KEY = ""
            assert dashboard_api.H._check_auth(handler, "/api/inbox") is True

    def test_status_exempt(self):
        """'/api/status' should be accessible without auth."""
        import dashboard_api
        handler = MagicMock(spec=dashboard_api.H)
        handler.headers = {}
        old_key = dashboard_api.API_KEY
        dashboard_api.API_KEY = "test-secret"
        try:
            assert dashboard_api.H._check_auth(handler, "/api/status") is True
        finally:
            dashboard_api.API_KEY = old_key

    def test_valid_bearer_token(self):
        """Valid Bearer token should pass."""
        import dashboard_api
        handler = MagicMock(spec=dashboard_api.H)
        handler.headers = {"Authorization": "Bearer test-secret"}
        old_key = dashboard_api.API_KEY
        dashboard_api.API_KEY = "test-secret"
        try:
            assert dashboard_api.H._check_auth(handler, "/api/inbox") is True
        finally:
            dashboard_api.API_KEY = old_key

    def test_invalid_bearer_token(self):
        """Invalid Bearer token should fail."""
        import dashboard_api
        handler = MagicMock(spec=dashboard_api.H)
        handler.headers = {"Authorization": "Bearer wrong-token"}
        old_key = dashboard_api.API_KEY
        dashboard_api.API_KEY = "test-secret"
        try:
            assert dashboard_api.H._check_auth(handler, "/api/inbox") is False
        finally:
            dashboard_api.API_KEY = old_key

    def test_missing_auth_header(self):
        """Missing Authorization header should fail when key is set."""
        import dashboard_api
        handler = MagicMock(spec=dashboard_api.H)
        handler.headers = {}
        old_key = dashboard_api.API_KEY
        dashboard_api.API_KEY = "test-secret"
        try:
            assert dashboard_api.H._check_auth(handler, "/api/inbox") is False
        finally:
            dashboard_api.API_KEY = old_key
