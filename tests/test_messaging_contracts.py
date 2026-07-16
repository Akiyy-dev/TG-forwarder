"""Versioned cross-container event contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.messaging.models import CommandEvent, IncomingMessageEvent
from app.schemas.message import (
    ForwardInfo,
    MediaItem,
    MediaType,
    MessageEntity,
    NormalizedMessage,
)


def test_incoming_message_event_round_trip() -> None:
    message = NormalizedMessage(
        source_chat_id=-100123,
        source_message_id=42,
        source_chat_username="source",
        source_chat_title="Source",
        date=datetime(2026, 7, 16, 8, 30, tzinfo=UTC),
        text="hello",
        entities=[MessageEntity(type="bold", offset=0, length=5)],
        media_type=MediaType.PHOTO,
        media_items=[
            MediaItem(
                media_type=MediaType.PHOTO,
                local_path="/data/downloads/photo.jpg",
                source_message_id=42,
                order=0,
            )
        ],
        forward_info=ForwardInfo(from_name="origin", date=datetime(2026, 7, 15, tzinfo=UTC)),
        raw_metadata={"source_backend": "telegram"},
        target_chat_ids=[-100999],
    )
    encoded = IncomingMessageEvent.create("telegram", message).to_json()
    decoded = IncomingMessageEvent.from_json(encoded)

    assert decoded.backend == "telegram"
    assert decoded.message.source_chat_id == -100123
    assert decoded.message.date == message.date
    assert decoded.message.media_type is MediaType.PHOTO
    assert decoded.message.media_items[0].local_path == "/data/downloads/photo.jpg"
    assert decoded.message.entities[0].type == "bold"
    assert decoded.message.forward_info is not None
    assert decoded.message.forward_info.from_name == "origin"


def test_command_event_round_trip() -> None:
    encoded = CommandEvent.create(
        "publish_review", {"task_id": 10, "expected_revision": 2}
    ).to_json()
    decoded = CommandEvent.from_json(encoded)

    assert decoded.kind == "publish_review"
    assert decoded.payload == {"task_id": 10, "expected_revision": 2}
