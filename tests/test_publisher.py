"""Publisher media routing tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.publishers.media_sender import MediaSender, route_media_type
from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.services.retry_service import RetryClass, classify_exception, should_retry


def test_route_media_types() -> None:
    assert route_media_type(MediaType.TEXT) == "send_message"
    assert route_media_type(MediaType.PHOTO) == "send_photo"
    assert route_media_type(MediaType.VIDEO) == "send_video"
    assert route_media_type(MediaType.DOCUMENT) == "send_document"
    assert route_media_type(MediaType.ANIMATION) == "send_animation"
    assert route_media_type(MediaType.AUDIO) == "send_audio"
    assert route_media_type(MediaType.VOICE) == "send_voice"
    assert route_media_type(MediaType.ALBUM) == "send_media_group"
    assert route_media_type(MediaType.STICKER) == "unsupported"


async def test_send_photo_uses_send_photo(tmp_path: Path) -> None:
    media = tmp_path / "a.jpg"
    media.write_bytes(b"fake")
    bot = MagicMock()
    sent = MagicMock(message_id=99)
    bot.send_photo = AsyncMock(return_value=sent)
    sender = MediaSender(bot)
    msg = NormalizedMessage(
        source_chat_id=-1,
        source_message_id=1,
        text="cap",
        media_type=MediaType.PHOTO,
        media_items=[MediaItem(media_type=MediaType.PHOTO, local_path=str(media))],
    )
    ids = await sender.send(-1002, msg)
    assert ids == [99]
    bot.send_photo.assert_awaited()


async def test_unsupported_raises() -> None:
    sender = MediaSender(MagicMock())
    msg = NormalizedMessage(
        source_chat_id=-1,
        source_message_id=1,
        media_type=MediaType.STICKER,
    )
    with pytest.raises(ValueError):
        await sender.send(-1002, msg)


def test_retry_classification() -> None:
    class TelegramRetryAfter(Exception):
        def __init__(self) -> None:
            self.retry_after = 1

    class TelegramForbiddenError(Exception):
        pass

    assert classify_exception(TelegramRetryAfter()) == RetryClass.WAIT
    assert classify_exception(TelegramForbiddenError()) == RetryClass.FATAL
    assert should_retry(TimeoutError(), 1, 3) is True
    assert should_retry(TelegramForbiddenError(), 1, 3) is False
