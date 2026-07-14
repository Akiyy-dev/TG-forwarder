"""Review API and concurrent publish tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.publish import ReviewPublishService
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.message import MediaType, NormalizedMessage
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
) -> int:
    async with session_factory() as session:
        processed = ProcessedMessage(
            source_chat_id=-1001,
            source_message_id=7,
            status="pending_review",
            target_chat_id=-1002,
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
                source_chat_id=-1001,
                source_message_id=7,
                text="hello processed",
                media_type=MediaType.TEXT,
                target_chat_id=-1002,
            ),
        )
    return task.id


async def test_review_edit_publish_api(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=555))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    ctx = _ctx(settings_env, session_factory, publisher)
    await ctx.auth_service.create_user(username="rev", password="password123", role=Role.REVIEWER)
    task_id = await _seed_task(session_factory)
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

        detail = await client.get(f"/api/v1/reviews/{task_id}")
        assert detail.status_code == 200
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
    pub = ReviewPublishService(session_factory, svc, publisher, ctx.media_service)

    async def _pub() -> dict:
        return await pub.publish_task(task_id, expected_revision=approved.revision, user_id=1)

    r1, r2 = await asyncio.gather(_pub(), _pub())
    successes = [
        r for r in (r1, r2) if r.get("status") == "published" and not r.get("already_published")
    ]
    assert len(successes) <= 1
    assert bot.send_message.await_count <= 1 or any(r.get("already_published") for r in (r1, r2))
