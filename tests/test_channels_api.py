"""Channel publish mode and management API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage, ReviewTask
from app.publishers.telegram_publisher import TelegramPublisher
from app.schemas.channel import PublishMode
from app.schemas.message import MediaType, MessageStatus, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService, QueueItem
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    publisher: TelegramPublisher | None = None,
    bot: MagicMock | None = None,
) -> AppContext:
    auth = AuthService(settings, session_factory)
    channel = ChannelService(settings, session_factory)
    media = MediaService(settings.download_dir, max_size_bytes=1024, ttl_minutes=1)
    pub = publisher or TelegramPublisher(MagicMock(), max_retries=1, base_delay=0.01)
    message = MessageService(settings, session_factory, channel, pub, media)
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=pub,
        auth_service=auth,
        bot=bot,
    )


async def test_channels_crud_default_review(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(
        username="admin", password="password123", role=Role.SUPER_ADMIN
    )
    await ctx.auth_service.create_user(username="viewer", password="password123", role=Role.VIEWER)
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password123"},
        )
        created = await client.post(
            "/api/v1/channels",
            json={"chat_id": -100111, "title": "Source A"},
        )
        assert created.status_code == 200
        data = created.json()["data"]
        assert data["publish_mode"] == PublishMode.REVIEW.value
        source_id = data["id"]

        patched = await client.patch(
            f"/api/v1/channels/{source_id}",
            json={"publish_mode": "paused"},
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["publish_mode"] == "paused"
        assert ctx.channel_service.get_publish_mode(-100111) == PublishMode.PAUSED

        target = await client.post(
            "/api/v1/targets",
            json={"chat_id": -100222, "title": "Target A"},
        )
        assert target.status_code == 200
        target_id = target.json()["data"]["id"]

        bot = MagicMock()
        bot.get_me = AsyncMock(return_value=MagicMock(id=1, username="testbot"))
        bot.get_chat_member = AsyncMock(
            return_value=MagicMock(status="administrator", can_post_messages=True)
        )
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=99))
        ctx.bot = bot

        checked = await client.post(f"/api/v1/targets/{target_id}/check-permissions")
        assert checked.status_code == 200
        assert checked.json()["data"]["permission_status"] == "ok"

        tested = await client.post(
            f"/api/v1/targets/{target_id}/test-message",
            json={"text": "ping"},
        )
        assert tested.status_code == 200
        assert tested.json()["data"]["message_id"] == 99

        await client.post("/api/v1/auth/logout")
        await client.post(
            "/api/v1/auth/login",
            json={"username": "viewer", "password": "password123"},
        )
        listed = await client.get("/api/v1/channels")
        assert listed.status_code == 200
        forbidden = await client.patch(
            f"/api/v1/channels/{source_id}",
            json={"enabled": False},
        )
        assert forbidden.status_code == 403


async def test_publish_mode_review_and_paused(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher=publisher)
    await ctx.channel_service.create_source(
        {
            "chat_id": -100301,
            "title": "review-src",
            "publish_mode": PublishMode.REVIEW.value,
            "target_channel_id": -100302,
        }
    )
    msg = NormalizedMessage(
        source_chat_id=-100301,
        source_message_id=1,
        text="hello world",
        media_type=MediaType.TEXT,
        target_chat_id=-100302,
    )
    await ctx.message_service.process_one(QueueItem(message=msg))

    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == -100301,
                    ProcessedMessage.source_message_id == 1,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.PENDING_REVIEW.value
        task = (
            await session.execute(
                select(ReviewTask).where(ReviewTask.processed_message_id == record.id)
            )
        ).scalar_one_or_none()
        assert task is not None

    bot.send_message.reset_mock()
    sources, _ = await ctx.channel_service.list_sources_paginated(page=1, page_size=10)
    source = next(s for s in sources if s.chat_id == -100301)
    await ctx.channel_service.update_source(source.id, {"publish_mode": PublishMode.PAUSED.value})

    msg2 = NormalizedMessage(
        source_chat_id=-100301,
        source_message_id=2,
        text="paused msg",
        media_type=MediaType.TEXT,
        target_chat_id=-100302,
    )
    await ctx.message_service.process_one(QueueItem(message=msg2))
    bot.send_message.assert_not_called()

    async with session_factory() as session:
        record2 = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == -100301,
                    ProcessedMessage.source_message_id == 2,
                )
            )
        ).scalar_one()
        assert record2.status == MessageStatus.PENDING_PUBLISH.value
