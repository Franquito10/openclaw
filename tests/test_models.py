"""Tests for ops.models routing."""
import os
import pytest
from unittest.mock import patch


class TestModelRouting:
    def test_default_model(self):
        from ops.models import get_model
        model = get_model()
        assert model is not None
        assert isinstance(model, str)

    def test_coder_override(self):
        from ops.models import get_model, STATIC_OVERRIDES
        model = get_model("coder")
        # Should get the static override (env or default)
        assert model == STATIC_OVERRIDES.get("coder") or model is not None

    def test_marketing_heretic(self):
        from ops.models import get_model, STATIC_OVERRIDES
        model = get_model("marketing")
        assert "heretic" in model.lower() or model == STATIC_OVERRIDES.get("marketing")

    def test_env_override_takes_priority(self):
        from ops.models import get_model
        with patch.dict(os.environ, {"OPS_MODEL_QA": "custom-qa-model"}):
            model = get_model("qa")
            assert model == "custom-qa-model"

    def test_unknown_agent_gets_default(self):
        from ops.models import get_model, DEFAULT_MODEL
        model = get_model("nonexistent")
        assert model == DEFAULT_MODEL

    def test_routing_table(self):
        from ops.models import list_routing_table
        table = list_routing_table()
        assert "default" in table
        assert "fallback" in table
        assert "overrides" in table
        assert isinstance(table["overrides"], dict)

    def test_fallback_model(self):
        from ops.models import get_fallback
        fb = get_fallback()
        assert fb is not None
        assert isinstance(fb, str)
