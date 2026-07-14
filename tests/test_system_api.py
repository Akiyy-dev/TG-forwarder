"""System control and resume requeue tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


def _ctx(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> AppContext:
    auth = AuthService(settings, session_factory)
    channel = ChannelService(settings, session_factory)
    media = MediaService(settings.download_dir, max_size_bytes=1024, ttl_minutes=1)
    pub = TelegramPublisher(MagicMock(), max_retries=1, base_delay=0.01)
    message = MessageService(settings, session_factory, channel, pub, media)
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=pub,
        auth_service=auth,
    )


async def test_system_pause_resume_requeues(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(
        username="admin", password="password123", role=Role.SUPER_ADMIN
    )
    app = create_api_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password123"},
        )
        paused = await client.post("/api/v1/system/pause")
        assert paused.status_code == 200
        assert paused.json()["data"]["publishing_paused"] is True

        with patch.object(
            ctx.message_service, "recover_pending", new=AsyncMock(return_value=3)
        ) as recover:
            resumed = await client.post("/api/v1/system/resume")
            assert resumed.status_code == 200
            body = resumed.json()["data"]
            assert body["publishing_paused"] is False
            assert body["requeued"] == 3
            recover.assert_awaited_once()

        status = await client.get("/api/v1/system/status")
        assert status.status_code == 200
        assert "queue_size" in status.json()["data"]

        logs = await client.get("/api/v1/logs/review-actions")
        assert logs.status_code == 200
        assert "items" in logs.json()["data"]
