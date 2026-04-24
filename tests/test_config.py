"""
test_config.py — Tests for src/config.py Settings singleton.
"""

from __future__ import annotations

import os

import pytest


class TestSettings:
    def test_default_env(self):
        from src.config import Settings

        s = Settings()
        assert s.env == os.getenv("ENV", "dev")

    def test_default_tool_server_url(self):
        from src.config import Settings

        s = Settings()
        assert s.tool_server_url == os.getenv(
            "TOOL_SERVER_URL", "http://localhost:8000"
        )

    def test_default_budget_limit(self):
        from src.config import Settings

        s = Settings()
        assert isinstance(s.budget_limit, int)
        assert s.budget_limit > 0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("BUDGET_LIMIT", "2000")
        from src.config import Settings

        s = Settings()
        assert s.env == "prod"
        assert s.budget_limit == 2000

    def test_tool_server_url_override(self, monkeypatch):
        monkeypatch.setenv("TOOL_SERVER_URL", "http://custom-server:9000")
        from src.config import Settings

        s = Settings()
        assert s.tool_server_url == "http://custom-server:9000"

    def test_hf_token_default_empty(self):
        from src.config import Settings

        s = Settings()
        assert isinstance(s.hf_token, str)

    def test_model_name_default(self):
        from src.config import Settings

        s = Settings()
        assert s.model_name  # non-empty default

    def test_settings_singleton_importable(self):
        from src.config import settings

        assert settings is not None
        assert hasattr(settings, "env")
        assert hasattr(settings, "tool_server_url")
        assert hasattr(settings, "budget_limit")
