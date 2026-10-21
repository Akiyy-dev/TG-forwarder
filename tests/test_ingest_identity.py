"""Sender and conversation identity survives the existing review/publish pipeline."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from app.api.app import create_api_app
from app.api.routes.history import _item
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage, ReviewTask
from app.messaging.models import message_from_dict, message_to_dict
from app.review.publish import ReviewPublishService, message_from_task
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.message import NormalizedMessage
from app.services.api_delivery_service import ApiDeliveryService
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

IDENTITY: dict[str, Any] = {
    "sender": "Alice",
    "conversation_id": "team-1",
    "conversation_name": "Project group",
    "external_message_id": "capture-1",
}


def test_review_reconstruction_preserves_sender_and_conversation() -> None:
    message = NormalizedMessage(
        source_chat_id=-1_000_000_000_000_123,
        source_message_id=7,
        text="Original body",
        raw_metadata={**IDENTITY, "source_backend": "api"},
    )
    snapshot = ReviewService.media_snapshot_from_message(message)
    task = ReviewTask(
        source_chat_id=message.source_chat_id,
        source_message_id=7,
        final_text="Edited body",
        media_type="text",
        media_snapshot=snapshot,
    )
    rebuilt = message_from_task(task)
    assert rebuilt.text == "Edited body"
    assert rebuilt.raw_metadata == {**IDENTITY, "source_backend": "api"}
    recovered = message_from_dict(message_to_dict(rebuilt))
    public = ApiDeliveryService.public_payload(recovered)
    for key, value in IDENTITY.items():
        assert public[key] == value
    assert "local_path" not in public


def test_history_exposes_identity_without_changing_body() -> None:
    row = ProcessedMessage(
        id=4,
        source_chat_id=-1_000_000_000_000_123,
        source_message_id=7,
        status="published",
        processing_result={"text": "Original body", "raw_metadata": IDENTITY},
    )
    result = _item(row, None, 1)
    assert result["text"] == "Original body"
    for key, value in IDENTITY.items():
        assert result[key] == value


def test_legacy_history_and_review_identity_is_optional() -> None:
    row = ProcessedMessage(
        id=4,
        source_chat_id=-100123,
        source_message_id=7,
        status="published",
        processing_result={"text": "Legacy message"},
    )
    result = _item(row, None, 0)
    assert result["sender"] is None
    message = message_from_task(
        ReviewTask(
            source_chat_id=-100123,
            source_message_id=7,
            final_text="Legacy message",
            media_type="text",
            media_snapshot={},
        )
    )
    assert message.raw_metadata == {}


async def test_history_filters_and_review_response_expose_identity(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    auth = AuthService(settings_env, session_factory)
    channel = ChannelService(settings_env, session_factory)
    media = MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1)
    publisher = MagicMock()
    ctx = AppContext(
        settings=settings_env,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        publisher=publisher,
        auth_service=auth,
        message_service=MessageService(settings_env, session_factory, channel, publisher, media),
    )
    await auth.create_user(username="identity-admin", password="password123", role=Role.SUPER_ADMIN)
    async with session_factory() as session:
        record = ProcessedMessage(
            source_chat_id=-100123,
            source_message_id=1,
            status="pending_review",
            processing_result={"text": "Body 1", "raw_metadata": IDENTITY},
        )
        other = ProcessedMessage(
            source_chat_id=-100123,
            source_message_id=2,
            status="published",
            processing_result={
                "text": "Body 2",
                "raw_metadata": {
                    **IDENTITY,
                    "sender": "Bob",
                    "conversation_id": "team-2",
                },
            },
        )
        session.add_all([record, other])
        await session.flush()
        task = ReviewTask(
            processed_message_id=record.id,
            source_chat_id=-100123,
            source_message_id=1,
            original_text="Body 1",
            processed_text="Body 1",
            final_text="Body 1",
            media_type="text",
            media_snapshot={"raw_metadata": IDENTITY},
        )
        session.add(task)
        await session.commit()
        task_id = task.id
    async with AsyncClient(
        transport=ASGITransport(app=create_api_app(ctx)), base_url="http://test"
    ) as client:
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "username": "identity-admin",
                "password": "password123",
            },
        )
        assert login.status_code == 200
        for query in (
            "sender=Alice",
            "conversation_id=team-1",
            "sender=Alice&conversation_id=team-1",
        ):
            response = await client.get(f"/api/v1/history?{query}")
            assert response.status_code == 200
            assert response.json()["data"]["meta"]["total"] == 1
            assert response.json()["data"]["items"][0]["sender"] == "Alice"
        empty = await client.get("/api/v1/history?sender=Alice&conversation_id=team-2")
        assert empty.json()["data"]["items"] == []
        review = await client.get(f"/api/v1/reviews/{task_id}")
        assert review.status_code == 200
        for key, value in IDENTITY.items():
            assert review.json()["data"]["task"][key] == value


@pytest.mark.parametrize("mode", ["auto", "review"])
async def test_ingest_through_publish_and_review_preserves_identity(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    mode: str,
) -> None:
    # Exercise long API-only content without the optional Telegram-sized footer.
    if mode == "review":
        settings_env.message_footer = ""
    auth = AuthService(settings_env, session_factory)
    channel = ChannelService(settings_env, session_factory)
    media = MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1)
    publisher = MagicMock()
    message_service = MessageService(settings_env, session_factory, channel, publisher, media)

    class CaptureBus:
        messages: list[NormalizedMessage]

        def __init__(self) -> None:
            self.messages = []

        async def publish_incoming(self, backend: str, message: NormalizedMessage) -> str:
            assert backend == "api"
            self.messages.append(message_from_dict(message_to_dict(message)))
            return "1-0"

    bus = CaptureBus()
    ctx = AppContext(
        settings=settings_env,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        publisher=publisher,
        auth_service=auth,
        message_service=message_service,
        command_bus=bus,
    )
    await auth.create_user(username="pipeline-admin", password="password123", role=Role.SUPER_ADMIN)
    async with AsyncClient(
        transport=ASGITransport(app=create_api_app(ctx)),
        base_url="http://test",
    ) as client:
        await client.post(
            "/api/v1/auth/login",
            json={
                "username": "pipeline-admin",
                "password": "password123",
            },
        )
        created = await client.post("/api/v1/ingest-sources", json={"name": "Capture software"})
        assert created.status_code == 200
        source = created.json()["data"]
        await client.patch(f"/api/v1/channels/{source['source_id']}", json={"publish_mode": mode})
        endpoint = (
            await client.post(
                "/api/v1/api-endpoints",
                json={
                    "name": "Consumer",
                    "source_ids": [source["source_id"]],
                },
            )
        ).json()["data"]
        submitted = {key: value for key, value in IDENTITY.items() if key != "external_message_id"}
        body = "Captured body" + (" x" * 3000 if mode == "review" else "")
        submitted.update(message_id="capture-1", text=body)
        accepted = await client.post(
            "/api/ingest/v1/messages",
            json=submitted,
            headers={
                "Authorization": f"Bearer {source['token']}",
            },
        )
        assert accepted.status_code == 202
        assert len(bus.messages) == 1
        await message_service.process_durable(bus.messages[0])
        if mode == "review":
            review = (await client.get("/api/v1/reviews")).json()["data"]["items"][0]
            assert review["sender"] == "Alice"
            edited = await client.post(
                f"/api/v1/reviews/{review['id']}/edit",
                json={
                    "content": review["final_text"] + "\nEdited",
                    "expected_revision": review["revision"],
                },
            )
            assert edited.status_code == 200
            review = edited.json()["data"]
            review_service = ReviewService(session_factory)
            approved = await review_service.transition(
                review["id"],
                ReviewStatus.APPROVED,
                user_id=None,
                action=ReviewActionType.APPROVED,
                expected_revision=review["revision"],
            )
            result = await ReviewPublishService(
                session_factory,
                review_service,
                publisher,
                media,
                channel,
            ).publish_task(review["id"], expected_revision=approved.revision, user_id=None)
            assert result["status"] == "published"
        # A redelivered queue event must not send a second public delivery.
        await message_service.process_durable(bus.messages[0])
        pulled = await client.get(
            "/api/public/v1/messages",
            headers={
                "Authorization": f"Bearer {endpoint['token']}",
            },
        )
        items = pulled.json()["data"]["items"]
        assert len(items) == 1
        for key, value in IDENTITY.items():
            assert items[0][key] == value
        assert items[0]["source_backend"] == "api"
        assert "Captured body" in items[0]["text"]
        if mode == "review":
            assert items[0]["text"].endswith("Edited")
