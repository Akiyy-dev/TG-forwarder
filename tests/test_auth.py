"""Authentication API and service tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.api.app import create_api_app
from app.auth.passwords import hash_password, verify_password
from app.auth.roles import Role
from app.auth.service import AuthError, AuthService
from app.auth.tokens import ACCESS_COOKIE, REFRESH_COOKIE
from app.config import Settings
from app.context import AppContext
from app.publishers.telegram_publisher import TelegramPublisher
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
def auth_service(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> AuthService:
    return AuthService(settings_env, session_factory)


async def test_password_hash_roundtrip() -> None:
    digest = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", digest)
    assert not verify_password("wrong", digest)
    assert "correct-horse" not in digest


async def test_authenticate_success_and_failure(
    auth_service: AuthService,
) -> None:
    await auth_service.create_user(
        username="admin",
        password="password123",
        role=Role.SUPER_ADMIN,
    )
    user = await auth_service.authenticate("admin", "password123")
    assert user.username == "admin"
    with pytest.raises(AuthError):
        await auth_service.authenticate("admin", "bad-password")
    with pytest.raises(AuthError):
        await auth_service.authenticate("missing", "password123")


def _build_ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> AppContext:
    auth = AuthService(settings, session_factory)
    channel = ChannelService(settings, session_factory)
    media = MediaService(settings.download_dir, max_size_bytes=1024, ttl_minutes=1)
    publisher = TelegramPublisher(MagicMock(), max_retries=1, base_delay=0.01)
    message = MessageService(settings, session_factory, channel, publisher, media)
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=publisher,
        auth_service=auth,
    )


async def test_login_refresh_logout_me_change_password(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _build_ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(
        username="admin",
        password="password123",
        role=Role.SUPER_ADMIN,
    )
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fail = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert fail.status_code == 401
        assert "Invalid username or password" in fail.text

        unauth = await client.get("/api/v1/auth/me")
        assert unauth.status_code == 401

        ok = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password123"},
        )
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
        assert ACCESS_COOKIE in ok.cookies
        assert REFRESH_COOKIE in ok.cookies

        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["data"]["username"] == "admin"

        refreshed = await client.post("/api/v1/auth/refresh")
        assert refreshed.status_code == 200

        changed = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "password123", "new_password": "password456"},
        )
        assert changed.status_code == 200

        await client.post("/api/v1/auth/logout")
        after = await client.get("/api/v1/auth/me")
        assert after.status_code == 401

        relogin = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password456"},
        )
        assert relogin.status_code == 200


async def test_login_rate_limit(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEB_LOGIN_RATE_LIMIT", "3")
    monkeypatch.setenv("WEB_LOGIN_RATE_WINDOW_SECONDS", "60")
    from app.config import clear_settings_cache

    clear_settings_cache()
    settings = Settings()  # type: ignore[call-arg]
    ctx = _build_ctx(settings, session_factory)
    assert ctx.login_limiter is not None
    ctx.login_limiter.limit = 3
    await ctx.auth_service.create_user(
        username="admin",
        password="password123",
        role=Role.SUPER_ADMIN,
    )
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "bad"},
            )
            assert resp.status_code == 401
        limited = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "bad"},
        )
        assert limited.status_code == 429
