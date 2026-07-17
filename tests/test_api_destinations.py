"""Public API destination, token security, and workflow integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ApiDelivery, ProcessedMessage, ReviewTask
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.publish import ReviewPublishService
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.channel import PublishMode
from app.schemas.message import MediaType, MessageStatus, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService, QueueItem
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AppContext, MagicMock]:
    auth = AuthService(settings, session_factory)
    channel = ChannelService(settings, session_factory)
    media = MediaService(settings.download_dir, max_size_bytes=1024, ttl_minutes=1)
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    publisher = TelegramPublisher(bot, max_retries=1, base_delay=0.01)
    message = MessageService(settings, session_factory, channel, publisher, media)
    return (
        AppContext(
            settings=settings,
            session_factory=session_factory,
            channel_service=channel,
            media_service=media,
            message_service=message,
            publisher=publisher,
            auth_service=auth,
        ),
        bot,
    )


async def _login_admin(client: AsyncClient, ctx: AppContext) -> None:
    await ctx.auth_service.create_user(
        username="admin", password="password123", role=Role.SUPER_ADMIN
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "password123"},
    )
    assert response.status_code == 200


async def test_api_only_rule_based_publish_pull_cursor_history_and_expiry(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx, bot = _ctx(settings_env, session_factory)
    app = create_api_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _login_admin(client, ctx)
        source = await ctx.channel_service.create_source(
            {
                "chat_id": -1009001,
                "title": "API source",
                "publish_mode": PublishMode.RULE_BASED.value,
            }
        )
        created = await client.post(
            "/api/v1/api-endpoints",
            json={"name": "consumer", "source_ids": [source.id]},
        )
        assert created.status_code == 200
        endpoint = created.json()["data"]
        token = endpoint["token"]
        assert token.startswith("tgf_")
        assert endpoint["token_prefix"] in token
        linked = await client.put(
            f"/api/v1/channels/{source.id}/api-endpoints",
            json={"api_endpoint_ids": [endpoint["id"]]},
        )
        assert linked.status_code == 200
        source_response = await client.get(f"/api/v1/channels/{source.id}")
        assert source_response.json()["data"]["api_endpoint_ids"] == [endpoint["id"]]

        message = NormalizedMessage(
            source_chat_id=source.chat_id,
            source_message_id=10,
            text="processed API message",
            media_type=MediaType.TEXT,
        )
        await ctx.message_service.process_one(QueueItem(message=message))
        await ctx.message_service.process_one(QueueItem(message=message))
        bot.send_message.assert_not_awaited()

        denied = await client.get(
            "/api/public/v1/messages", headers={"Authorization": "Bearer wrong-token"}
        )
        assert denied.status_code == 401

        pulled = await client.get(
            "/api/public/v1/messages?cursor=0&limit=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pulled.status_code == 200
        data = pulled.json()["data"]
        assert len(data["items"]) == 1
        assert "processed API message" in data["items"][0]["text"]
        assert data["items"][0]["source_chat_id"] == source.chat_id
        cursor = data["next_cursor"]

        empty = await client.get(
            f"/api/public/v1/messages?cursor={cursor}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert empty.json()["data"]["items"] == []

        history = await client.get(f"/api/v1/history?source_id={source.id}")
        assert history.status_code == 200
        history_item = history.json()["data"]["items"][0]
        assert history_item["status"] == MessageStatus.PUBLISHED.value
        assert history_item["publish_mode"] == PublishMode.RULE_BASED.value
        assert history_item["api_delivery_count"] == 1

        expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        patched = await client.patch(
            f"/api/v1/api-endpoints/{endpoint['id']}", json={"expires_at": expired}
        )
        assert patched.status_code == 200
        expired_pull = await client.get(
            "/api/public/v1/messages", headers={"Authorization": f"Bearer {token}"}
        )
        assert expired_pull.status_code == 401

    async with session_factory() as session:
        count = int((await session.execute(select(func.count(ApiDelivery.id)))).scalar_one())
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == source.chat_id,
                    ProcessedMessage.source_message_id == 10,
                )
            )
        ).scalar_one()
        assert count == 1
        assert record.status == MessageStatus.PUBLISHED.value


async def test_api_review_delivery_is_created_only_after_approval(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx, bot = _ctx(settings_env, session_factory)
    source = await ctx.channel_service.create_source(
        {
            "chat_id": -1009002,
            "title": "review API source",
            "publish_mode": PublishMode.REVIEW.value,
        }
    )
    app = create_api_app(ctx)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _login_admin(client, ctx)
        created = await client.post(
            "/api/v1/api-endpoints",
            json={"name": "review consumer", "source_ids": [source.id]},
        )
        assert created.status_code == 200
        endpoint_id = int(created.json()["data"]["id"])

    await ctx.message_service.process_one(
        QueueItem(
            message=NormalizedMessage(
                source_chat_id=source.chat_id,
                source_message_id=20,
                text="must be approved",
                media_type=MediaType.TEXT,
            )
        )
    )
    async with session_factory() as session:
        task = (
            await session.execute(select(ReviewTask).where(ReviewTask.source_message_id == 20))
        ).scalar_one()
        assert task.target_api_endpoint_ids == [endpoint_id]
        assert int((await session.execute(select(func.count(ApiDelivery.id)))).scalar_one()) == 0
        task_id = task.id
        revision = task.revision

    review_service = ReviewService(session_factory)
    approved = await review_service.transition(
        task_id,
        ReviewStatus.APPROVED,
        user_id=None,
        action=ReviewActionType.APPROVED,
        expected_revision=revision,
    )
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        ctx.publisher,
        ctx.media_service,
        ctx.channel_service,
    )
    result = await publish_service.publish_task(
        task_id, expected_revision=approved.revision, user_id=None
    )
    assert result["status"] == ReviewStatus.PUBLISHED.value
    assert result["target_message_ids"] == []
    bot.send_message.assert_not_awaited()

    async with session_factory() as session:
        delivery = (await session.execute(select(ApiDelivery))).scalar_one()
        assert delivery.api_endpoint_id == endpoint_id
        assert "must be approved" in delivery.payload["text"]
        processed = await session.get(ProcessedMessage, delivery.processed_message_id)
        assert processed is not None
        assert processed.status == MessageStatus.PUBLISHED.value
