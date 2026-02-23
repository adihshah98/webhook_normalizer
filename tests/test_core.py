import os

import pytest

from app.core.config import Settings


def test_settings_defaults():
    s = Settings()
    assert "sqlite" in s.database_url
    assert s.log_level == "INFO"
    assert s.env == "development"


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/db")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://localhost/db"
