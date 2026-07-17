"""Configuration loading tests."""

from __future__ import annotations

import pytest
from app.config import Settings, clear_settings_cache


def test_settings_load_lists_and_replacements(settings_env: Settings) -> None:
    assert settings_env.bot_admin_ids == [111, 222]
    assert settings_env.text_replacements == [("Foo", "Bar"), ("old", "new")]
    assert "***" in repr(settings_env)
    assert settings_env.bot_token not in repr(settings_env)
    assert settings_env.telegram_api_hash not in repr(settings_env)


def test_legacy_channel_environment_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("BOT_TOKEN", "1:token")
    monkeypatch.setenv("BOT_POLLING_ENABLED", "false")
    monkeypatch.setenv("TARGET_CHANNEL_ID", "-1001")
    monkeypatch.setenv("SOURCE_CHANNELS", "@legacy")
    monkeypatch.setenv("CHANNELS_CONFIG_PATH", "./config/channels.yaml")

    settings = Settings(app_role="sender", _env_file=None)

    assert not hasattr(settings, "target_channel_id")
    assert not hasattr(settings, "source_channels")
    assert not hasattr(settings, "channels_config_path")


def test_safew_role_does_not_require_telegram_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "BOT_TOKEN",
        "BOT_ADMIN_IDS",
        "WEB_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    settings = Settings(app_role="safew-receiver", _env_file=None)
    assert settings.app_role == "safew-receiver"


def test_telegram_receiver_can_start_without_environment_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_API_ID", "1")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")

    settings = Settings(app_role="telegram-receiver", _env_file=None)

    assert settings.app_role == "telegram-receiver"


def test_sender_can_disable_bot_polling_without_admin_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOT_TOKEN", "1:token")
    monkeypatch.delenv("BOT_ADMIN_IDS", raising=False)
    monkeypatch.setenv("BOT_POLLING_ENABLED", "false")

    settings = Settings(app_role="sender", _env_file=None)

    assert settings.bot_polling_enabled is False
    assert settings.bot_admin_ids == []
