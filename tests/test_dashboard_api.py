"""Dashboard summary API test."""

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


async def test_dashboard_summary(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    auth = AuthService(settings_env, session_factory)
    channel = ChannelService(settings_env, session_factory)
    media = MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1)
    pub = TelegramPublisher(MagicMock(), max_retries=1, base_delay=0.01)
    message = MessageService(settings_env, session_factory, channel, pub, media)
    ctx = AppContext(
        settings=settings_env,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=pub,
        auth_service=auth,
    )
    await auth.create_user(username="viewer", password="password123", role=Role.VIEWER)
    app = create_api_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password123"},
        )
        res = await client.get("/api/v1/dashboard")
        assert res.status_code == 200
        data = res.json()["data"]
        assert "service" in data
        assert "counts" in data
        assert "pending_review" in data["counts"]
