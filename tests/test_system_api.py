"""System control and resume requeue tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.app import create_api_app
from app.api.routes.system import _status_event_stream
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage
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
        status_data = status.json()["data"]
        assert "queue_size" in status_data
        assert status_data["queue_size_available"] is True
        assert status_data["queue_size_source"] == "process_memory"
        assert status_data["last_error_source"] == "process_memory"
        assert status_data["sender_running"] is True
        assert status_data["publisher_running"] is True
        assert status_data["bot_polling_enabled"] is True
        assert status_data["bot_available"] is True

        logs = await client.get("/api/v1/logs/review-actions")
        assert logs.status_code == 200
        assert "items" in logs.json()["data"]


async def test_system_status_reports_disabled_bot_polling_separately(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings_env.bot_polling_enabled = False
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(username="viewer", password="password123", role=Role.VIEWER)
    app = create_api_app(ctx)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password123"},
        )
        response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["sender_running"] is True
    assert data["publisher_running"] is True
    assert data["bot_polling_enabled"] is False
    assert data["bot_available"] is False


async def test_distributed_system_status_uses_shared_queue_and_database_error(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    ctx.message_service._last_error = "stale-web-process-error"
    bus = MagicMock()
    bus.role_alive = AsyncMock(return_value=True)
    bus.incoming_queue_size = AsyncMock(return_value=7)
    ctx.command_bus = bus
    await ctx.auth_service.create_user(username="viewer", password="password123", role=Role.VIEWER)
    async with session_factory() as session:
        session.add(
            ProcessedMessage(
                source_chat_id=-1001,
                source_message_id=99,
                status="failed",
                target_chat_id=-1002,
                error_message="sender database failure",
            )
        )
        await session.commit()
    app = create_api_app(ctx)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password123"},
        )
        response = await client.get("/api/v1/system/status")
        bus.incoming_queue_size.return_value = None
        unavailable_response = await client.get("/api/v1/system/status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["queue_size"] == 7
    assert data["queue_size_available"] is True
    assert data["queue_size_source"] == "redis_stream"
    assert data["last_error"] == "sender database failure"
    assert data["last_error_source"] == "database"
    unavailable = unavailable_response.json()["data"]
    assert unavailable["queue_size"] is None
    assert unavailable["queue_size_available"] is False
    assert unavailable["queue_size_source"] == "redis_stream"
    assert bus.incoming_queue_size.await_count == 2


async def test_status_event_stream_refreshes_and_emits_pause_changes(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    bus = MagicMock()
    bus.incoming_queue_size = AsyncMock(side_effect=[4, 5])
    ctx.command_bus = bus
    request = MagicMock()
    request.is_disconnected = AsyncMock(side_effect=[False, False, True])

    refresh_paused = AsyncMock(side_effect=[False, True])
    with (
        patch.object(ctx.message_service, "refresh_paused", new=refresh_paused),
        patch("app.api.routes.system.asyncio.sleep", new=AsyncMock()),
    ):
        stream = _status_event_stream(request, ctx)
        first = await anext(stream)
        second = await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)

    assert '"publishing_paused": false' in first
    assert '"publishing_paused": true' in second
    assert '"queue_size": 4' in first
    assert '"queue_size": 5' in second
    assert '"queue_size_source": "redis_stream"' in first
    assert refresh_paused.await_count == 2
