"""Channel publish mode and management API tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage, ReviewTask, SourceChannel
from app.listeners.safew_notifications import safew_chat_id
from app.publishers.telegram_publisher import TelegramPublisher
from app.schemas.channel import PublishMode
from app.schemas.message import MediaType, MessageStatus, NormalizedMessage
from app.services.channel_service import ChannelService, ChannelServiceError
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
        assert data["source_backend"] == "telegram"
        source_id = data["id"]

        safew = await client.post(
            "/api/v1/channels",
            json={"chat_id": safew_chat_id("SafeW Group"), "title": "SafeW Group"},
        )
        assert safew.status_code == 200
        assert safew.json()["data"]["source_backend"] == "safew"

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
    target = await ctx.channel_service.create_target({"chat_id": -100302, "title": "review-target"})
    await ctx.channel_service.create_source(
        {
            "chat_id": -100301,
            "title": "review-src",
            "publish_mode": PublishMode.REVIEW.value,
            "target_ids": [target.id],
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


async def test_disabled_targets_are_excluded_and_message_fails_without_retry(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher=publisher)

    # Unregistered sources never inherit an environment target.
    assert ctx.channel_service.get_targets_for(-100909) == []

    default_target_chat_id = -1001234567890
    default_target = await ctx.channel_service.create_target(
        {
            "chat_id": default_target_chat_id,
            "title": "disabled default",
            "enabled": False,
        }
    )
    assert default_target.enabled is False
    disabled = await ctx.channel_service.create_target(
        {"chat_id": -100401, "title": "disabled", "enabled": False}
    )
    active = await ctx.channel_service.create_target(
        {"chat_id": -100402, "title": "active", "enabled": True}
    )
    source = await ctx.channel_service.create_source(
        {
            "chat_id": -100403,
            "title": "source",
            "target_ids": [disabled.id, active.id],
        }
    )

    assert ctx.channel_service.get_targets_for(source.chat_id) == [active.chat_id]

    await ctx.channel_service.update_target(active.id, {"enabled": False})
    configs = await ctx.channel_service.list_sources()
    config = next(item for item in configs if item.id == source.id)
    assert config.target_chat_ids == []
    assert config.target_channel_id is None
    assert ctx.channel_service.get_targets_for(source.chat_id) == []
    assert ctx.channel_service.get_targets_for(-100909) == []

    # A stale incoming target must not bypass the current disabled-target map.
    message = NormalizedMessage(
        source_chat_id=source.chat_id,
        source_message_id=99,
        text="must not publish",
        media_type=MediaType.TEXT,
        target_chat_id=active.chat_id,
        target_chat_ids=[active.chat_id],
    )
    await ctx.message_service.process_durable(message)

    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == source.chat_id,
                    ProcessedMessage.source_message_id == 99,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.FAILED.value
        assert record.target_chat_id is None
        assert record.error_message == "no enabled target channel configured"
        assert record.retry_count == 0
    bot.send_message.assert_not_awaited()


async def test_unlinked_primary_target_column_is_not_a_routing_fallback(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = ChannelService(settings_env, session_factory)
    target = await service.create_target({"chat_id": -100490, "title": "registered target"})
    async with session_factory() as session:
        source = SourceChannel(
            chat_id=-100491,
            title="stale source",
            enabled=True,
            target_channel_id=target.chat_id,
        )
        session.add(source)
        await session.commit()

    await service.load_from_db()

    assert service.get_targets_for(source.chat_id) == []


async def test_queued_message_from_disabled_source_fails_without_publish_or_retry(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher=publisher)
    target = await ctx.channel_service.create_target(
        {"chat_id": -100451, "title": "active target", "enabled": True}
    )
    source = await ctx.channel_service.create_source(
        {
            "chat_id": -100452,
            "title": "source",
            "publish_mode": PublishMode.AUTO.value,
            "target_ids": [target.id],
        }
    )
    message = NormalizedMessage(
        source_chat_id=source.chat_id,
        source_message_id=100,
        text="queued before source was disabled",
        media_type=MediaType.TEXT,
        target_chat_id=target.chat_id,
        target_chat_ids=[target.chat_id],
    )
    assert await ctx.message_service.enqueue(message) is True

    await ctx.channel_service.update_source(source.id, {"enabled": False})
    queued = ctx.message_service.queue.get_nowait()
    assert queued is not None
    await ctx.message_service.process_one(queued)

    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == source.chat_id,
                    ProcessedMessage.source_message_id == message.source_message_id,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.FAILED.value
        assert record.target_chat_id is None
        assert record.error_message == "source channel is currently disabled"
        assert record.retry_count == 0
    bot.send_message.assert_not_awaited()


async def test_message_revalidates_target_after_processing_before_publish(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher=publisher)
    target = await ctx.channel_service.create_target(
        {"chat_id": -100461, "title": "active target", "enabled": True}
    )
    source = await ctx.channel_service.create_source(
        {
            "chat_id": -100462,
            "title": "source",
            "publish_mode": PublishMode.AUTO.value,
            "target_ids": [target.id],
        }
    )
    message = NormalizedMessage(
        source_chat_id=source.chat_id,
        source_message_id=101,
        text="target changes while processing",
        media_type=MediaType.TEXT,
        target_chat_id=target.chat_id,
        target_chat_ids=[target.chat_id],
    )
    routing = AsyncMock(
        side_effect=[
            ([target.chat_id], None),
            ([], "no enabled target channel configured"),
        ]
    )
    ctx.message_service._refresh_routing = routing  # type: ignore[method-assign]

    await ctx.message_service.process_durable(message)

    assert routing.await_count == 2
    bot.send_message.assert_not_awaited()
    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == source.chat_id,
                    ProcessedMessage.source_message_id == message.source_message_id,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.FAILED.value
        assert record.error_message == "no enabled target channel configured"
        assert record.retry_count == 0


async def test_delete_target_recomputes_and_clears_legacy_primary(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = ChannelService(settings_env, session_factory)
    first = await service.create_target({"chat_id": -100501, "title": "first", "enabled": True})
    second = await service.create_target({"chat_id": -100502, "title": "second", "enabled": True})
    source = await service.create_source(
        {
            "chat_id": -100503,
            "title": "source",
            "target_ids": [first.id, second.id],
        }
    )
    assert source.target_channel_id == first.chat_id

    await service.delete_target(first.id)
    source = await service.get_source(source.id)
    assert source.target_channel_id == second.chat_id
    assert await service.get_linked_target_ids(source.id) == [second.id]
    assert service.get_targets_for(source.chat_id) == [second.chat_id]

    await service.delete_target(second.id)
    source = await service.get_source(source.id)
    assert source.target_channel_id is None
    assert await service.get_linked_target_ids(source.id) == []
    assert service.get_targets_for(source.chat_id) == []
    assert service.get_target_for(source.chat_id) is None


async def test_delete_last_telegram_source_does_not_resurrect_from_environment(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = ChannelService(settings_env, session_factory)
    first = await service.create_source({"chat_id": -100601, "title": "first"})
    last = await service.create_source({"chat_id": -100602, "title": "last"})
    safew = await service.create_source(
        {"chat_id": safew_chat_id("SafeW source"), "title": "SafeW source"}
    )

    await service.delete_source(first.id)

    await service.delete_source(last.id)
    with pytest.raises(ChannelServiceError) as deleted_telegram:
        await service.get_source(last.id)
    assert deleted_telegram.value.code == "not_found"

    # SafeW sources do not act as Telegram tombstones and remain independently deletable.
    await service.delete_source(safew.id)
    with pytest.raises(ChannelServiceError) as deleted_exc:
        await service.get_source(safew.id)
    assert deleted_exc.value.code == "not_found"
