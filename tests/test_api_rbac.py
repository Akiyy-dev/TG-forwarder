"""RBAC and API envelope tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.publishers.telegram_publisher import TelegramPublisher
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ctx(
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


async def test_viewer_forbidden_from_user_admin(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(username="viewer1", password="password123", role=Role.VIEWER)
    await ctx.auth_service.create_user(
        username="boss", password="password123", role=Role.SUPER_ADMIN
    )
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer1", "password": "password123"},
        )
        denied = await client.get("/api/v1/users")
        assert denied.status_code == 403
        assert denied.json()["ok"] is False
        assert denied.json()["error"]["code"] == "forbidden"

        await client.post("/api/v1/auth/logout")
        await client.post(
            "/api/v1/auth/login",
            json={"username": "boss", "password": "password123"},
        )
        allowed = await client.get("/api/v1/users")
        assert allowed.status_code == 200
        assert allowed.json()["ok"] is True
        assert "meta" in allowed.json()["data"]


async def test_docs_can_be_disabled(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    monkeypatch.setenv("WEB_DOCS_ENABLED", "false")
    from app.config import clear_settings_cache

    clear_settings_cache()
    settings = Settings()  # type: ignore[call-arg]
    ctx = _ctx(settings, session_factory)
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/api/docs")
        assert docs.status_code == 404
        openapi = await client.get("/api/openapi.json")
        assert openapi.status_code == 404
