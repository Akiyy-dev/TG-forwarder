"""Rules CRUD / test / reapply API tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import KeywordRule, ProcessedMessage, RuleExecutionLog
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.service import ReviewService
from app.review.state_machine import ReviewStatus
from app.schemas.message import MediaType, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _ctx(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> AppContext:
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


async def test_rules_crud_and_test(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(
        username="admin", password="password123", role=Role.SUPER_ADMIN
    )
    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "password123"},
        )
        created = await client.post(
            "/api/v1/rules",
            json={
                "name": "block-spam",
                "pattern": "spam",
                "action": "replace",
                "replacement": "[x]",
                "priority": 10,
            },
        )
        assert created.status_code == 200
        rule_id = created.json()["data"]["id"]

        listed = await client.get("/api/v1/rules")
        assert listed.status_code == 200
        assert listed.json()["data"]["meta"]["total"] == 1

        tested = await client.post(
            f"/api/v1/rules/{rule_id}/test",
            json={"sample_text": "buy spam now"},
        )
        assert tested.status_code == 200
        assert tested.json()["data"]["final_text"] == "buy [x] now"

        patched = await client.patch(
            f"/api/v1/rules/{rule_id}",
            json={"enabled": False},
        )
        assert patched.status_code == 200
        assert patched.json()["data"]["enabled"] is False

        dup = await client.post(f"/api/v1/rules/{rule_id}/duplicate")
        assert dup.status_code == 200
        assert dup.json()["data"]["name"].endswith("(copy)")

        exported = await client.get("/api/v1/rules/export")
        assert exported.status_code == 200
        assert len(exported.json()["data"]["items"]) == 2

        group = await client.post(
            "/api/v1/rule-groups",
            json={"name": "default", "priority": 1},
        )
        assert group.status_code == 200


async def test_reapply_rules_requires_confirm_for_reject(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    ctx = _ctx(settings_env, session_factory)
    await ctx.auth_service.create_user(
        username="rev", password="password123", role=Role.REVIEWER
    )
    await ctx.auth_service.create_user(
        username="admin", password="password123", role=Role.SUPER_ADMIN
    )

    async with session_factory() as session:
        session.add(
            KeywordRule(
                name="rejector",
                pattern="toxic",
                rule_type="keyword",
                match_type="contains",
                action="reject",
                enabled=True,
                priority=1,
                case_sensitive=False,
                whole_word=False,
                use_regex=False,
                stop_processing=False,
                hit_count=0,
            )
        )
        processed = ProcessedMessage(
            source_chat_id=-1001,
            source_message_id=9,
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
            original_text="this is toxic content",
            processed_message=NormalizedMessage(
                source_chat_id=-1001,
                source_message_id=9,
                text="this is toxic content",
                media_type=MediaType.TEXT,
                target_chat_id=-1002,
            ),
        )
        task_id = task.id
        revision = task.revision

    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post(
            "/api/v1/auth/login",
            json={"username": "rev", "password": "password123"},
        )
        preview = await client.post(
            f"/api/v1/reviews/{task_id}/reapply-rules",
            json={"expected_revision": revision, "source": "original"},
        )
        assert preview.status_code == 200
        body = preview.json()["data"]
        assert body["preview"]["needs_confirm"] is True
        assert "task" not in body

        confirmed = await client.post(
            f"/api/v1/reviews/{task_id}/reapply-rules",
            json={
                "expected_revision": revision,
                "source": "original",
                "confirm_reject": True,
            },
        )
        assert confirmed.status_code == 200
        task_data = confirmed.json()["data"]["task"]
        assert task_data["status"] == ReviewStatus.REJECTED.value

    async with session_factory() as session:
        logs = list((await session.execute(select(RuleExecutionLog))).scalars())
        assert len(logs) >= 1
        assert logs[0].review_task_id == task_id
