"""Review API and concurrent publish tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import (
    ProcessedMessage,
    ReviewTask,
    SourceChannel,
    SourceTargetLink,
    TargetChannel,
)
from app.listeners.safew_notifications import safew_chat_id
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.publish import ReviewPublishService
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.message import MediaType, MessageStatus, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    publisher: TelegramPublisher | None = None,
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
    )


async def _seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_chat_id: int = -1001,
    source_message_id: int = 7,
    target_chat_ids: list[int] | None = None,
) -> int:
    targets = target_chat_ids if target_chat_ids is not None else [-1002]
    primary_target = targets[0] if targets else None
    async with session_factory() as session:
        processed = ProcessedMessage(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            status="pending_review",
            target_chat_id=primary_target,
        )
        session.add(processed)
        await session.commit()
        await session.refresh(processed)
        pid = processed.id
    svc = ReviewService(session_factory)
    async with session_factory() as session:
        processed = await session.get(ProcessedMessage, pid)
        assert processed is not None
        task = await svc.create_from_message(
            processed=processed,
            original_text="hello original",
            processed_message=NormalizedMessage(
                source_chat_id=source_chat_id,
                source_message_id=source_message_id,
                text="hello processed",
                media_type=MediaType.TEXT,
                target_chat_id=primary_target,
                target_chat_ids=list(targets),
            ),
        )
    return task.id


async def _seed_routing(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_chat_id: int = -1001,
    target_chat_id: int = -1002,
) -> None:
    async with session_factory() as session:
        source = SourceChannel(
            chat_id=source_chat_id,
            title="source",
            enabled=True,
            target_channel_id=target_chat_id,
        )
        target = TargetChannel(chat_id=target_chat_id, title="target", enabled=True)
        session.add_all([source, target])
        await session.flush()
        session.add(SourceTargetLink(source_id=source.id, target_id=target.id))
        await session.commit()


async def _approve_task(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: int,
) -> tuple[ReviewService, int]:
    service = ReviewService(session_factory)
    async with session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        assert task is not None
        revision = task.revision
    approved = await service.transition(
        task_id,
        ReviewStatus.APPROVED,
        user_id=1,
        action=ReviewActionType.APPROVED,
        expected_revision=revision,
    )
    return service, approved.revision


async def test_review_edit_publish_api(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher)
    await ctx.auth_service.create_user(username="rev", password="password123", role=Role.REVIEWER)
    await _seed_routing(session_factory)
    task_id = await _seed_task(session_factory)
    safew_task_id = await _seed_task(
        session_factory,
        source_chat_id=safew_chat_id("SafeW Group"),
        source_message_id=8,
    )
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "rev", "password": "password123"},
        )
        listed = await client.get("/api/v1/reviews")
        assert listed.status_code == 200
        assert listed.json()["data"]["meta"]["total"] >= 1
        safew_item = next(
            item for item in listed.json()["data"]["items"] if item["id"] == safew_task_id
        )
        assert safew_item["source_backend"] == "safew"

        detail = await client.get(f"/api/v1/reviews/{task_id}")
        assert detail.status_code == 200
        assert detail.json()["data"]["task"]["source_backend"] == "telegram"
        revision = detail.json()["data"]["task"]["revision"]

        edited = await client.post(
            f"/api/v1/reviews/{task_id}/edit",
            json={"content": "edited text", "expected_revision": revision},
        )
        assert edited.status_code == 200
        revision = edited.json()["data"]["revision"]

        published = await client.post(
            f"/api/v1/reviews/{task_id}/publish",
            json={"expected_revision": revision},
        )
        assert published.status_code == 200
        assert published.json()["data"]["status"] == "published"
        bot.send_message.assert_awaited()

        again = await client.post(
            f"/api/v1/reviews/{task_id}/publish",
            json={"expected_revision": revision},
        )
        # published tasks should short-circuit
        assert again.status_code in {200, 400}


async def test_concurrent_publish_once(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher)
    await _seed_routing(session_factory)
    task_id = await _seed_task(session_factory)
    svc = ReviewService(session_factory)
    async with session_factory() as session:
        from app.database.models import ReviewTask

        task = await session.get(ReviewTask, task_id)
        assert task is not None
        revision = task.revision
    approved = await svc.transition(
        task_id,
        ReviewStatus.APPROVED,
        user_id=1,
        action=ReviewActionType.APPROVED,
        expected_revision=revision,
    )
    pub = ReviewPublishService(
        session_factory,
        svc,
        publisher,
        ctx.media_service,
        ctx.channel_service,
    )

    async def _pub() -> dict:
        return await pub.publish_task(task_id, expected_revision=approved.revision, user_id=1)

    r1, r2 = await asyncio.gather(_pub(), _pub())
    successes = [
        r for r in (r1, r2) if r.get("status") == "published" and not r.get("already_published")
    ]
    assert len(successes) <= 1
    assert bot.send_message.await_count <= 1 or any(r.get("already_published") for r in (r1, r2))


async def test_review_publish_rejects_disabled_current_target(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_chat_id = -1003001
    target_chat_id = -1003002
    async with session_factory() as session:
        source = SourceChannel(
            chat_id=source_chat_id,
            title="source",
            enabled=True,
            target_channel_id=target_chat_id,
        )
        target = TargetChannel(
            chat_id=target_chat_id,
            title="disabled target",
            enabled=False,
        )
        session.add_all([source, target])
        await session.flush()
        session.add(SourceTargetLink(source_id=source.id, target_id=target.id))
        await session.commit()

    task_id = await _seed_task(
        session_factory,
        source_chat_id=source_chat_id,
        source_message_id=301,
        target_chat_ids=[target_chat_id],
    )
    review_service, revision = await _approve_task(session_factory, task_id)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    channel_service = ChannelService(settings_env, session_factory)
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        publisher,
        MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1),
        channel_service,
    )

    result = await publish_service.publish_task(
        task_id,
        expected_revision=revision,
        user_id=1,
    )

    assert result["status"] == ReviewStatus.FAILED.value
    assert "currently enabled target" in result["error"]
    bot.send_message.assert_not_awaited()
    async with session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        assert task is not None
        processed = await session.get(ProcessedMessage, task.processed_message_id)
        assert processed is not None
        assert task.status == ReviewStatus.FAILED.value
        assert task.error_message == result["error"]
        assert processed.status == "failed"
        assert processed.error_message == result["error"]


async def test_review_publish_filters_deleted_snapshot_target(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_chat_id = -1004001
    active_target_id = -1004002
    deleted_target_id = -1004003
    async with session_factory() as session:
        source = SourceChannel(
            chat_id=source_chat_id,
            title="source",
            enabled=True,
            target_channel_id=active_target_id,
        )
        active = TargetChannel(
            chat_id=active_target_id,
            title="active target",
            enabled=True,
        )
        session.add_all([source, active])
        await session.flush()
        session.add(SourceTargetLink(source_id=source.id, target_id=active.id))
        await session.commit()

    task_id = await _seed_task(
        session_factory,
        source_chat_id=source_chat_id,
        source_message_id=401,
        target_chat_ids=[active_target_id, deleted_target_id],
    )
    review_service, revision = await _approve_task(session_factory, task_id)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=44))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        publisher,
        MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1),
        ChannelService(settings_env, session_factory),
    )

    result = await publish_service.publish_task(
        task_id,
        expected_revision=revision,
        user_id=1,
    )

    assert result["status"] == ReviewStatus.PUBLISHED.value
    assert result["per_target"] == {str(active_target_id): {"ok": True, "message_ids": [44]}}
    bot.send_message.assert_awaited_once_with(active_target_id, "hello processed")


async def test_review_publish_rejects_disabled_current_source(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_chat_id = -1005001
    target_chat_id = -1005002
    async with session_factory() as session:
        source = SourceChannel(
            chat_id=source_chat_id,
            title="disabled source",
            enabled=False,
            target_channel_id=target_chat_id,
        )
        target = TargetChannel(chat_id=target_chat_id, title="active target", enabled=True)
        session.add_all([source, target])
        await session.flush()
        session.add(SourceTargetLink(source_id=source.id, target_id=target.id))
        await session.commit()

    task_id = await _seed_task(
        session_factory,
        source_chat_id=source_chat_id,
        source_message_id=501,
        target_chat_ids=[target_chat_id],
    )
    review_service, revision = await _approve_task(session_factory, task_id)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        TelegramPublisher(bot, max_retries=1, base_delay=0.01),
        MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1),
        ChannelService(settings_env, session_factory),
    )

    result = await publish_service.publish_task(
        task_id,
        expected_revision=revision,
        user_id=1,
    )

    assert result == {
        "status": ReviewStatus.FAILED.value,
        "error": "review source channel is currently disabled",
    }
    bot.send_message.assert_not_awaited()
    async with session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        assert task is not None
        processed = await session.get(ProcessedMessage, task.processed_message_id)
        assert processed is not None
        assert task.status == ReviewStatus.FAILED.value
        assert processed.status == MessageStatus.FAILED.value
        assert processed.retry_count == 0


async def test_review_publish_revalidates_target_immediately_before_send(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    target_chat_id = -1006002
    task_id = await _seed_task(
        session_factory,
        source_chat_id=-1006001,
        source_message_id=601,
        target_chat_ids=[target_chat_id],
    )
    review_service, revision = await _approve_task(session_factory, task_id)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        TelegramPublisher(bot, max_retries=1, base_delay=0.01),
        MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1),
        ChannelService(settings_env, session_factory),
    )
    current_targets = AsyncMock(
        side_effect=[
            [target_chat_id],  # initial validation
            [target_chat_id],  # validation after media recovery
            [],  # target disabled immediately before its send
        ]
    )
    publish_service._current_targets = current_targets  # type: ignore[method-assign]

    result = await publish_service.publish_task(
        task_id,
        expected_revision=revision,
        user_id=1,
    )

    assert result["status"] == ReviewStatus.FAILED.value
    assert "no longer enabled and bound" in result["error"]
    assert current_targets.await_count == 3
    bot.send_message.assert_not_awaited()
    async with session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        assert task is not None
        processed = await session.get(ProcessedMessage, task.processed_message_id)
        assert processed is not None
        assert processed.status == MessageStatus.FAILED.value
        assert processed.retry_count == 0
