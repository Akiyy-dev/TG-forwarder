"""Inbound text API security, durable receipts, retries, and source isolation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import IngestReceipt, IngestSource, ProcessedMessage, SourceChannel
from app.entrypoints.sender import _accept_or_register_source
from app.messaging.models import IncomingMessageEvent, message_from_dict, message_to_dict
from app.processors.deduplication import DeduplicationProcessor
from app.schemas.message import NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from app.services.telegram_source_registry import load_telegram_source_snapshot
from app.source_backends import source_backend_for_chat_id
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class RecordingBus:
    """External queue boundary; retain messages even when its ack is lost."""

    def __init__(self) -> None:
        self.messages: list[NormalizedMessage] = []
        self.failure: str | None = None
        self.pause: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def publish_incoming(self, backend: str, message: NormalizedMessage) -> str:
        assert backend == "api"
        self.entered.set()
        if self.pause is not None:
            await self.pause.wait()
        if self.failure == "unavailable":
            raise ConnectionError("queue unavailable")
        self.messages.append(message_from_dict(message_to_dict(message)))
        if self.failure == "lost_ack":
            raise TimeoutError("queue accepted but acknowledgment was lost")
        return f"{len(self.messages)}-0"


@pytest_asyncio.fixture
async def ingest_client(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, AppContext, RecordingBus]]:
    channel = ChannelService(settings_env, session_factory)
    media = MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1)
    publisher = MagicMock()
    auth = AuthService(settings_env, session_factory)
    message = MessageService(settings_env, session_factory, channel, publisher, media)
    bus = RecordingBus()
    ctx = AppContext(
        settings=settings_env,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=publisher,
        auth_service=auth,
        command_bus=bus,
    )
    await auth.create_user(username="admin", password="password123", role=Role.SUPER_ADMIN)
    async with AsyncClient(
        transport=ASGITransport(app=create_api_app(ctx)), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/api/v1/auth/login", json={"username": "admin", "password": "password123"}
            )
        ).status_code == 200
        yield client, ctx, bus


async def _create(client: AsyncClient, name: str = "Desktop capture") -> dict[str, Any]:
    response = await client.post("/api/v1/ingest-sources", json={"name": name})
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def _headers(item: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {item['token']}"}


def _payload(**changes: Any) -> dict[str, Any]:
    return {"message_id": "capture-1", "text": "  untouched captured text  ", **changes}


async def test_ingress_endpoint_requires_its_own_bearer_token(settings_env: Settings) -> None:
    ctx = MagicMock(settings=settings_env)
    async with AsyncClient(
        transport=ASGITransport(app=create_api_app(ctx)), base_url="http://test"
    ) as client:
        response = await client.post("/api/ingest/v1/messages", json=_payload())
    assert response.status_code == 401


async def test_creation_stores_secret_hash_and_api_source_with_review_default(ingest_client):
    client, ctx, _bus = ingest_client
    item = await _create(client)
    assert item["token"].startswith("tgfi_")
    assert -2_000_000_000_000_000 < item["source_chat_id"] <= -1_000_000_000_000_000
    assert source_backend_for_chat_id(item["source_chat_id"]) == "api"
    source = await ctx.channel_service.get_source(item["source_id"])
    assert source.title == "Desktop capture"
    assert source.enabled is True
    assert source.publish_mode == "review"
    listed = (await client.get("/api/v1/ingest-sources")).json()["data"]["items"]
    assert len(listed) == 1
    assert listed[0]["source_id"] == source.id
    assert "token" not in listed[0]
    assert "token_hash" not in listed[0]
    async with ctx.session_factory() as session:
        credential = await session.get(IngestSource, item["id"])
        assert credential is not None
        assert len(credential.token_hash) == 64
        assert credential.token_hash != item["token"]


async def test_receipt_preserves_identity_and_missing_timestamp_retries(ingest_client):
    client, _ctx, bus = ingest_client
    item = await _create(client)
    body = _payload(conversation_id="project-1", conversation_name="项目群", sender="Alice")
    first = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=body)
    assert first.status_code == 202, first.text
    receipt = first.json()["data"]
    assert receipt["source_id"] == item["source_id"]
    assert receipt["conversation_id"] == "project-1"
    assert receipt["message_id"] == "capture-1"
    assert receipt["status"] == "queued"
    assert receipt["duplicate"] is False
    second = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=body)
    assert second.status_code in {200, 202}
    assert second.json()["data"]["receipt_id"] == receipt["receipt_id"]
    assert second.json()["data"]["duplicate"] is True
    assert len(bus.messages) == 1
    message = bus.messages[0]
    assert message.source_message_id == receipt["receipt_id"]
    assert message.text == "  untouched captured text  "
    assert message.date is not None and message.date.tzinfo is not None
    assert message.raw_metadata == {
        "source_backend": "api",
        "sender": "Alice",
        "conversation_id": "project-1",
        "conversation_name": "项目群",
        "external_message_id": "capture-1",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"text": "changed"},
        {"sender": "Bob"},
        {"conversation_name": "changed"},
        {"timestamp": "2026-10-21T00:00:00Z"},
    ],
)
async def test_same_key_changed_submitted_data_is_conflict(ingest_client, change):
    client, _ctx, bus = ingest_client
    item = await _create(client)
    accepted = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert accepted.status_code == 202
    conflict = await client.post(
        "/api/ingest/v1/messages", headers=_headers(item), json=_payload(**change)
    )
    assert conflict.status_code == 409
    assert len(bus.messages) == 1


async def test_equivalent_supplied_timestamp_is_canonicalized(ingest_client):
    client, _ctx, bus = ingest_client
    item = await _create(client)
    first = await client.post(
        "/api/ingest/v1/messages",
        headers=_headers(item),
        json=_payload(timestamp="2026-10-21T08:00:00+08:00"),
    )
    assert first.status_code == 202
    duplicate = await client.post(
        "/api/ingest/v1/messages",
        headers=_headers(item),
        json=_payload(timestamp="2026-10-21T00:00:00Z"),
    )
    assert duplicate.status_code in {200, 202}
    assert duplicate.json()["data"]["duplicate"] is True
    assert len(bus.messages) == 1


@pytest.mark.parametrize(
    "body",
    [
        _payload(message_id=""),
        _payload(message_id="  "),
        _payload(message_id="a" * 129),
        _payload(conversation_id=" "),
        _payload(conversation_id="a" * 129),
        _payload(text=" \n "),
        _payload(text="a" * 65537),
        _payload(sender="a" * 257),
        _payload(conversation_name="a" * 257),
        _payload(timestamp="2026-10-21T00:00:00"),
        _payload(timestamp="1770000000"),
        _payload(timestamp="1770000000000"),
        _payload(timestamp="2026-10-21"),
        _payload(attachments=[]),
        _payload(source_id=1),
        _payload(target_chat_id=1),
    ],
)
async def test_invalid_or_routing_overriding_payloads_are_rejected(ingest_client, body):
    client, _ctx, bus = ingest_client
    item = await _create(client)
    response = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=body)
    assert response.status_code == 422
    assert bus.messages == []


async def test_ingress_auth_is_separate_and_revoke_retains_source(ingest_client):
    client, ctx, bus = ingest_client
    item = await _create(client)
    outbound = (await client.post("/api/v1/api-endpoints", json={"name": "outbound"})).json()[
        "data"
    ]
    for headers in [{}, {"Authorization": "Bearer invalid"}, _headers(outbound)]:
        denied = await client.post("/api/ingest/v1/messages", headers=headers, json=_payload())
        assert denied.status_code == 401
    # Admin cookie on the same client never provides ingress authorization.
    assert bus.messages == []
    outbound_denied = await client.get("/api/public/v1/messages", headers=_headers(item))
    assert outbound_denied.status_code == 401
    rotated = await client.post(f"/api/v1/ingest-sources/{item['id']}/rotate-token")
    assert rotated.status_code == 200
    new_item = rotated.json()["data"]
    assert new_item["token"] != item["token"]
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    ).status_code == 401
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(new_item), json=_payload())
    ).status_code == 202
    removed = await client.delete(f"/api/v1/ingest-sources/{item['id']}")
    assert removed.status_code == 200
    assert await ctx.channel_service.get_source(item["source_id"]) is not None
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(new_item), json=_payload())
    ).status_code == 401
    assert (await client.get("/api/v1/ingest-sources")).json()["data"]["items"] == []


async def test_disabled_expired_credentials_and_disabled_source_are_denied(ingest_client):
    client, ctx, _bus = ingest_client
    item = await _create(client)
    url = f"/api/v1/ingest-sources/{item['id']}"
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    for changes in [{"enabled": False}, {"enabled": True, "expires_at": expired}]:
        assert (await client.patch(url, json=changes)).status_code == 200
        assert (
            await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
        ).status_code == 401
    assert (await client.patch(url, json={"expires_at": None})).status_code == 200
    await ctx.channel_service.update_source(item["source_id"], {"enabled": False})
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    ).status_code == 401
    assert (await client.patch(url, json={"name": "Renamed"})).status_code == 200
    assert (await ctx.channel_service.get_source(item["source_id"])).title == "Renamed"


@pytest.mark.parametrize("operation", ["create", "patch"])
async def test_expiry_offsets_are_compared_as_the_same_utc_instant(ingest_client, operation):
    client, _ctx, bus = ingest_client
    expired = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=8)))
    if operation == "create":
        created = await client.post(
            "/api/v1/ingest-sources",
            json={"name": "expired local offset", "expires_at": expired.isoformat()},
        )
        assert created.status_code == 200
        item = created.json()["data"]
    else:
        item = await _create(client)
        changed = await client.patch(
            f"/api/v1/ingest-sources/{item['id']}", json={"expires_at": expired.isoformat()}
        )
        assert changed.status_code == 200
    denied = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert denied.status_code == 401
    assert bus.messages == []


async def test_management_timestamps_keep_explicit_utc_offsets(ingest_client):
    client, _ctx, _bus = ingest_client
    expiry = (datetime.now(UTC) + timedelta(hours=1)).astimezone(timezone(timedelta(hours=8)))
    created = await client.post(
        "/api/v1/ingest-sources", json={"name": "clock", "expires_at": expiry.isoformat()}
    )
    assert created.status_code == 200
    item = created.json()["data"]
    expires_at = datetime.fromisoformat(item["expires_at"].replace("Z", "+00:00"))
    assert expires_at.tzinfo is not None
    assert expires_at == expiry
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    ).status_code == 202
    listed = (await client.get("/api/v1/ingest-sources")).json()["data"]["items"][0]
    for key in ["expires_at", "created_at", "last_access_at"]:
        assert datetime.fromisoformat(listed[key].replace("Z", "+00:00")).tzinfo is not None


async def test_viewer_can_list_but_cannot_manage_ingress(ingest_client):
    client, ctx, _bus = ingest_client
    item = await _create(client)
    await ctx.auth_service.create_user(username="viewer", password="password123", role=Role.VIEWER)
    assert (
        await client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": "password123"}
        )
    ).status_code == 200
    assert (await client.get("/api/v1/ingest-sources")).status_code == 200
    assert (await client.post("/api/v1/ingest-sources", json={"name": "denied"})).status_code == 403
    assert (
        await client.patch(f"/api/v1/ingest-sources/{item['id']}", json={"enabled": False})
    ).status_code == 403
    assert (
        await client.post(f"/api/v1/ingest-sources/{item['id']}/rotate-token")
    ).status_code == 403
    assert (await client.delete(f"/api/v1/ingest-sources/{item['id']}")).status_code == 403


@pytest.mark.parametrize("failure", ["unavailable", "lost_ack"])
async def test_failed_or_ambiguous_queue_ack_is_retryable_without_new_receipt(
    ingest_client, failure
):
    client, ctx, bus = ingest_client
    item = await _create(client)
    bus.failure = failure
    first = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert first.status_code == 503
    bus.failure = None
    retried = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert retried.status_code == 202, retried.text
    assert retried.json()["data"]["duplicate"] is True
    receipt_id = retried.json()["data"]["receipt_id"]
    assert all(message.source_message_id == receipt_id for message in bus.messages)
    async with ctx.session_factory() as session:
        rows = (await session.execute(select(IngestReceipt))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "queued"
        assert rows[0].payload["text"] == "  untouched captured text  "


async def test_simultaneous_duplicates_serialize_delivery(ingest_client):
    client, _ctx, bus = ingest_client
    item = await _create(client)
    bus.pause = asyncio.Event()
    first_task = asyncio.create_task(
        client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    )
    await asyncio.wait_for(bus.entered.wait(), 2)
    second_task = asyncio.create_task(
        client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    )
    await asyncio.sleep(0.05)
    bus.pause.set()
    responses = await asyncio.gather(first_task, second_task)
    assert all(response.status_code in {200, 202} for response in responses)
    assert len({response.json()["data"]["receipt_id"] for response in responses}) == 1
    assert sorted(response.json()["data"]["duplicate"] for response in responses) == [False, True]
    assert len(bus.messages) == 1


async def test_concurrent_first_insert_is_one_durable_receipt(ingest_client):
    client, ctx, bus = ingest_client
    item = await _create(client)
    responses = await asyncio.gather(
        *[
            client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
            for _ in range(8)
        ]
    )
    assert all(response.status_code in {200, 202} for response in responses)
    assert len({response.json()["data"]["receipt_id"] for response in responses}) == 1
    assert len(bus.messages) == 1
    async with ctx.session_factory() as session:
        rows = (await session.execute(select(IngestReceipt))).scalars().all()
        assert len(rows) == 1


async def test_crashed_publisher_lease_can_expire_and_resume_same_receipt(ingest_client):
    client, ctx, bus = ingest_client
    item = await _create(client)
    bus.failure = "unavailable"
    assert (
        await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    ).status_code == 503
    async with ctx.session_factory() as session:
        receipt = (await session.execute(select(IngestReceipt))).scalar_one()
        receipt_id = receipt.id
        original_date = receipt.payload["date"]
        receipt.lease_token = "crashed-worker"
        receipt.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)
        await session.commit()
    bus.failure = None
    busy = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert busy.status_code == 503
    assert bus.messages == []
    changed = await client.post(
        "/api/ingest/v1/messages", headers=_headers(item), json=_payload(text="different")
    )
    assert changed.status_code == 409
    async with ctx.session_factory() as session:
        receipt = await session.get(IngestReceipt, receipt_id)
        assert receipt is not None
        receipt.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    retried = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert retried.status_code == 202
    assert retried.json()["data"]["receipt_id"] == receipt_id
    assert retried.json()["data"]["duplicate"] is True
    assert bus.messages[0].date is not None
    assert bus.messages[0].date.isoformat() == original_date


async def test_conversations_and_sources_have_independent_receipts_and_hashes(ingest_client):
    client, _ctx, bus = ingest_client
    first = await _create(client, "one")
    other = await _create(client, "two")
    for item, conversation in [(first, "one"), (first, "two"), (other, "one")]:
        response = await client.post(
            "/api/ingest/v1/messages",
            headers=_headers(item),
            json=_payload(conversation_id=conversation, sender="Alice"),
        )
        assert response.status_code == 202
    assert len({message.source_message_id for message in bus.messages}) == 3
    assert len({DeduplicationProcessor.compute_hash(message) for message in bus.messages}) == 3
    assert bus.messages[0].source_chat_id == first["source_chat_id"]
    assert bus.messages[2].source_chat_id == other["source_chat_id"]


async def test_local_queue_full_remains_retryable(ingest_client):
    client, ctx, _bus = ingest_client
    ctx.command_bus = None
    item = await _create(client)
    ctx.message_service.queue = asyncio.Queue(maxsize=1)
    await ctx.message_service.queue.put(None)
    full = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert full.status_code == 503
    assert ctx.message_service.queue.get_nowait() is None
    retried = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert retried.status_code == 202
    queued = ctx.message_service.queue.get_nowait()
    assert queued is not None
    assert queued.message.source_message_id == retried.json()["data"]["receipt_id"]


async def test_orphan_pending_review_with_full_local_queue_remains_retryable(ingest_client):
    client, ctx, bus = ingest_client
    item = await _create(client)
    bus.failure = "unavailable"
    first = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert first.status_code == 503
    async with ctx.session_factory() as session:
        receipt = (await session.execute(select(IngestReceipt))).scalar_one()
        receipt_id = receipt.id
        session.add(
            ProcessedMessage(
                source_chat_id=item["source_chat_id"],
                source_message_id=receipt_id,
                status="pending_review",
            )
        )
        await session.commit()
    ctx.command_bus = None
    ctx.message_service.queue = asyncio.Queue(maxsize=1)
    await ctx.message_service.queue.put(None)
    full = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert full.status_code == 503
    async with ctx.session_factory() as session:
        receipt = await session.get(IngestReceipt, receipt_id)
        assert receipt is not None and receipt.queued_at is None
    assert ctx.message_service.queue.get_nowait() is None
    retried = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert retried.status_code == 202
    assert retried.json()["data"]["receipt_id"] == receipt_id
    queued = ctx.message_service.queue.get_nowait()
    assert queued is not None and queued.message.source_message_id == receipt_id


@pytest.mark.parametrize("previous_status", ["pending_review", "filtered", "failed"])
@pytest.mark.parametrize("transport", ["redis", "local"])
async def test_redelivery_cannot_bypass_review_or_filter_after_route_mode_change(
    ingest_client, previous_status, transport
):
    client, ctx, bus = ingest_client
    item = await _create(client)
    outbound = await client.post(
        "/api/v1/api-endpoints", json={"name": "consumer", "source_ids": [item["source_id"]]}
    )
    assert outbound.status_code == 200
    accepted = await client.post("/api/ingest/v1/messages", headers=_headers(item), json=_payload())
    assert accepted.status_code == 202
    if transport == "redis":
        await ctx.message_service.process_durable(bus.messages[0])
    else:
        assert await ctx.message_service.enqueue(bus.messages[0]) is True
        queued = ctx.message_service.queue.get_nowait()
        assert queued is not None
        await ctx.message_service.process_one(queued)
    async with ctx.session_factory() as session:
        record = (await session.execute(select(ProcessedMessage))).scalar_one()
        assert record.status == "pending_review"
        original_payload = dict(record.processing_result or {})
        record.status = previous_status
        source = await session.get(SourceChannel, item["source_id"])
        assert source is not None
        source.publish_mode = "rule_based"
        await session.commit()
    # Transport redelivery must preserve the previous decision even if an admin
    # has meanwhile changed how future messages are handled.
    if transport == "redis":
        await ctx.message_service.process_durable(bus.messages[0])
    elif await ctx.message_service.enqueue(bus.messages[0]):
        queued = ctx.message_service.queue.get_nowait()
        assert queued is not None
        await ctx.message_service.process_one(queued)
    async with ctx.session_factory() as session:
        record = (await session.execute(select(ProcessedMessage))).scalar_one()
        assert record.status == previous_status
        assert record.processing_result == original_payload
    pulled = await client.get("/api/public/v1/messages", headers=_headers(outbound.json()["data"]))
    assert pulled.json()["data"]["items"] == []


async def test_api_sources_are_excluded_from_telegram_and_refreshed_for_sender(ingest_client):
    client, ctx, _bus = ingest_client
    stale = ChannelService(ctx.settings, ctx.session_factory)
    await stale.load_from_db()
    item = await _create(client)
    snapshot = await load_telegram_source_snapshot(ctx.session_factory)
    assert item["source_chat_id"] not in snapshot.enabled_chat_ids
    message = NormalizedMessage(source_chat_id=item["source_chat_id"], source_message_id=1)
    event = IncomingMessageEvent.create("api", message)
    assert await _accept_or_register_source(event, ctx.settings, stale) is True
    assert item["source_chat_id"] in stale.configured_chat_ids
    async with ctx.session_factory() as session:
        source = await session.get(SourceChannel, item["source_id"])
        assert source is not None
        source.enabled = False
        source.access_status = "missing"
        await session.commit()
    telegram_client = MagicMock()
    await ctx.channel_service.update_source(
        item["source_id"], {"enabled": True}, client=telegram_client
    )
    telegram_client.get_entity.assert_not_called()
    async with ctx.session_factory() as session:
        source = await session.get(SourceChannel, item["source_id"])
        assert source is not None and source.access_status == "ok"


async def test_sender_refreshes_cached_disabled_api_source_after_reenable(ingest_client):
    client, ctx, _bus = ingest_client
    item = await _create(client)
    await ctx.channel_service.update_source(item["source_id"], {"enabled": False})
    stale = ChannelService(ctx.settings, ctx.session_factory)
    await stale.load_from_db()
    assert stale.is_enabled(item["source_chat_id"]) is False
    await ctx.channel_service.update_source(item["source_id"], {"enabled": True})
    event = IncomingMessageEvent.create(
        "api", NormalizedMessage(source_chat_id=item["source_chat_id"], source_message_id=1)
    )
    assert await _accept_or_register_source(event, ctx.settings, stale) is True
    assert stale.is_enabled(item["source_chat_id"]) is True


@pytest.mark.parametrize(
    ("chat_id", "expected"),
    [
        (-2_000_000_000_000_001, "safew"),
        (-2_000_000_000_000_000, "safew"),
        (-1_999_999_999_999_999, "api"),
        (-1_000_000_000_000_000, "api"),
        (-999_999_999_999_999, "telegram"),
        (-1001234567890, "telegram"),
    ],
)
def test_api_namespace_keeps_telegram_and_safew_disjoint(chat_id: int, expected: str) -> None:
    assert source_backend_for_chat_id(chat_id) == expected
