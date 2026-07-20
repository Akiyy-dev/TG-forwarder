"""SafeW Bot API publisher and outbound routing tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.database.models import ProcessedMessage
from app.publishers.outbound_publisher import OutboundPublisher
from app.publishers.safew_publisher import SafeWForbiddenError, SafeWPublisher
from app.schemas.channel import PublishMode, TargetBackend, TargetRoute
from app.schemas.message import MediaItem, MediaType, MessageStatus, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from sqlalchemy import select


def _message(*, media_type: MediaType = MediaType.TEXT) -> NormalizedMessage:
    return NormalizedMessage(
        source_chat_id=-1,
        source_message_id=2,
        text="processed text",
        media_type=media_type,
    )


async def test_safew_text_publish_uses_documented_bot_url() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 73}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = SafeWPublisher(
        "123:secret",
        api_base_url="https://api.safew.bot",
        max_retries=1,
        client=client,
    )

    assert await publisher.publish(_message(), -1009) == [73]
    assert seen == {
        "url": "https://api.safew.bot/bot123:secret/sendMessage",
        "body": {"chat_id": -1009, "text": "processed text"},
    }
    await client.aclose()


async def test_safew_photo_publish_uploads_multipart(tmp_path: Path) -> None:
    photo = tmp_path / "sample.jpg"
    photo.write_bytes(b"image-bytes")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/sendPhoto")
        assert request.headers["content-type"].startswith("multipart/form-data;")
        body = await request.aread()
        assert b'name="chat_id"' in body
        assert b'name="photo"; filename="sample.jpg"' in body
        assert b"processed text" in body
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 74}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = SafeWPublisher("token", max_retries=1, client=client)
    message = _message(media_type=MediaType.PHOTO)
    message.media_items = [
        MediaItem(
            media_type=MediaType.PHOTO,
            local_path=str(photo),
            original_filename="sample.jpg",
            mime_type="image/jpeg",
        )
    ]

    assert await publisher.publish(message, -1010) == [74]
    await client.aclose()


async def test_safew_api_error_is_fatal() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"ok": False, "error_code": 403, "description": "Bot cannot post"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = SafeWPublisher("token", max_retries=3, base_delay=0, client=client)
    with pytest.raises(SafeWForbiddenError, match="Bot cannot post"):
        await publisher.publish(_message(), -1011)
    await client.aclose()


async def test_outbound_router_selects_safew() -> None:
    telegram = AsyncMock()
    telegram.bot = AsyncMock()
    safew = AsyncMock()
    safew.publish = AsyncMock(return_value=[88])
    router = OutboundPublisher(telegram, safew)
    target = TargetRoute(
        id=4,
        target_backend=TargetBackend.SAFEW,
        chat_id=-1012,
    )

    assert await router.publish_target(_message(), target) == [88]
    safew.publish.assert_awaited_once()
    telegram.publish.assert_not_awaited()


async def test_message_service_routes_safew_target(
    settings_env,
    session_factory,
) -> None:
    telegram = MagicMock()
    telegram.bot = MagicMock()
    telegram.publish = AsyncMock(return_value=[1])
    safew = MagicMock()
    safew.publish = AsyncMock(return_value=[91])
    router = OutboundPublisher(telegram, safew)
    channels = ChannelService(settings_env, session_factory)
    target = await channels.create_target(
        {
            "chat_id": -1001200,
            "target_backend": TargetBackend.SAFEW.value,
            "title": "SafeW destination",
        }
    )
    source = await channels.create_source(
        {
            "chat_id": -1001201,
            "title": "source",
            "publish_mode": PublishMode.AUTO.value,
            "target_ids": [target.id],
        }
    )
    service = MessageService(
        settings_env,
        session_factory,
        channels,
        router,
        MediaService(settings_env.download_dir, max_size_bytes=1024, ttl_minutes=1),
    )

    message = NormalizedMessage(
        source_chat_id=source.chat_id,
        source_message_id=12,
        text="send to SafeW",
    )
    await service.process_durable(message)

    safew.publish.assert_awaited_once()
    assert safew.publish.await_args.args[1] == target.chat_id
    telegram.publish.assert_not_awaited()
    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == source.chat_id,
                    ProcessedMessage.source_message_id == message.source_message_id,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.PUBLISHED.value
        assert record.target_message_ids == [91]
