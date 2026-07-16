"""Configuration loading tests."""

from __future__ import annotations

import pytest
from app.config import Settings, clear_settings_cache
from pydantic import ValidationError


def test_settings_load_lists_and_replacements(settings_env: Settings) -> None:
    assert settings_env.bot_admin_ids == [111, 222]
    assert "@demo_channel" in settings_env.source_channels
    assert settings_env.text_replacements == [("Foo", "Bar"), ("old", "new")]
    assert "***" in repr(settings_env)
    assert settings_env.bot_token not in repr(settings_env)
    assert settings_env.telegram_api_hash not in repr(settings_env)


def test_settings_require_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    monkeypatch.setenv("BOT_TOKEN", "1:token")
    monkeypatch.setenv("BOT_ADMIN_IDS", "1")
    monkeypatch.setenv("TARGET_CHANNEL_ID", "-1001")
    monkeypatch.setenv("SOURCE_CHANNELS", "")
    monkeypatch.setenv("WEB_ENABLED", "false")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_safew_role_does_not_require_telegram_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "BOT_TOKEN",
        "BOT_ADMIN_IDS",
        "TARGET_CHANNEL_ID",
        "SOURCE_CHANNELS",
        "WEB_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(app_role="safew-receiver", _env_file=None)
    assert settings.app_role == "safew-receiver"
