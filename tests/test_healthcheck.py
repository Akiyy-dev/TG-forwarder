"""Role-aware health check tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from scripts import healthcheck

Check = Callable[[], Awaitable[list[str]]]


def _recording_check(calls: list[str], name: str, errors: list[str] | None = None) -> Check:
    async def check() -> list[str]:
        calls.append(name)
        return errors or []

    return check


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("web", ["database", "redis", "download_dir"]),
        ("sender", ["database", "redis", "bot", "download_dir"]),
        (
            "telegram-receiver",
            ["database", "redis", "telegram_session", "download_dir"],
        ),
        ("safew-receiver", ["redis"]),
        ("all", ["database", "telegram_session", "bot", "download_dir"]),
    ],
)
async def test_healthcheck_only_runs_checks_for_role(
    monkeypatch: pytest.MonkeyPatch,
    role: str,
    expected: list[str],
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("APP_ROLE", role)
    monkeypatch.setattr(healthcheck, "load_dotenv", lambda: None)
    monkeypatch.setattr(healthcheck, "_check_database", _recording_check(calls, "database"))
    monkeypatch.setattr(healthcheck, "_check_redis", _recording_check(calls, "redis"))
    monkeypatch.setattr(
        healthcheck,
        "_check_telegram_session",
        _recording_check(calls, "telegram_session"),
    )
    monkeypatch.setattr(healthcheck, "_check_bot", _recording_check(calls, "bot"))
    monkeypatch.setattr(healthcheck, "_check_download_dir", _recording_check(calls, "download_dir"))

    assert await healthcheck._check() == 0
    assert calls == expected


async def test_telegram_receiver_does_not_require_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setenv("APP_ROLE", "telegram-receiver")
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    monkeypatch.setattr(healthcheck, "load_dotenv", lambda: None)
    monkeypatch.setattr(healthcheck, "_check_database", _recording_check(calls, "database"))
    monkeypatch.setattr(healthcheck, "_check_redis", _recording_check(calls, "redis"))
    monkeypatch.setattr(
        healthcheck,
        "_check_telegram_session",
        _recording_check(calls, "telegram_session"),
    )
    monkeypatch.setattr(healthcheck, "_check_download_dir", _recording_check(calls, "download_dir"))
    monkeypatch.setattr(
        healthcheck,
        "_check_bot",
        _recording_check(calls, "bot", ["bot_token_missing"]),
    )

    assert await healthcheck._check() == 0
    assert "bot" not in calls


async def test_healthcheck_rejects_unknown_role(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("APP_ROLE", "unknown")
    monkeypatch.setattr(healthcheck, "load_dotenv", lambda: None)

    assert await healthcheck._check() == 1
    assert "unsupported_app_role: unknown" in capsys.readouterr().out
