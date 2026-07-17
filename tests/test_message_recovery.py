"""Regression tests for durable normalized-message payload recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.config import Settings
from app.database.models import ProcessedMessage
from app.database.repositories.message_repo import MessageRepository
from app.messaging.models import message_from_dict, message_to_dict
from app.schemas.message import (
    ForwardInfo,
    MediaItem,
    MediaType,
    MessageEntity,
    MessageStatus,
    NormalizedMessage,
)
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import INVALID_STORED_PAYLOAD, MessageService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _service(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> MessageService:
    return MessageService(
        settings,
        session_factory,
        ChannelService(settings, session_factory),
        MagicMock(),
        MediaService(settings.download_dir, max_size_bytes=1024, ttl_minutes=1),
    )


def _message(*, source_message_id: int = 10) -> NormalizedMessage:
    return NormalizedMessage(
        source_chat_id=-100700,
        source_message_id=source_message_id,
        source_chat_username="source_name",
        source_chat_title="Source title",
        grouped_id=77,
        date=datetime(2026, 7, 17, 3, 0, tzinfo=UTC),
        text="payload survives",
        entities=[MessageEntity(type="bold", offset=0, length=7)],
        media_type=MediaType.VIDEO,
        media_items=[
            MediaItem(
                media_type=MediaType.VIDEO,
                local_path="/data/downloads/video.mp4",
                file_id="file-id",
                file_unique_id="unique-id",
                original_filename="video.mp4",
                mime_type="video/mp4",
                file_size=321,
                width=1280,
                height=720,
                duration=8,
                source_message_id=source_message_id,
                order=2,
            )
        ],
        reply_to_message_id=5,
        forward_info=ForwardInfo(from_chat_id=-100900, from_message_id=4),
        raw_metadata={"source_backend": "telegram", "nested": {"ok": True}},
        target_chat_id=-100801,
        target_chat_ids=[-100801, -100802],
        album_message_ids=[source_message_id, source_message_id + 1],
    )


async def test_enqueue_persists_full_payload_before_processing(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(settings_env, session_factory)
    message = _message()

    assert await service.enqueue(message) is True

    async with session_factory() as session:
        record = (
            await session.execute(
                select(ProcessedMessage).where(
                    ProcessedMessage.source_chat_id == message.source_chat_id,
                    ProcessedMessage.source_message_id == message.source_message_id,
                )
            )
        ).scalar_one()
        assert record.status == MessageStatus.RECEIVED.value
        assert record.processing_result == message_to_dict(message)
        restored = message_from_dict(record.processing_result)

    assert restored.target_chat_ids == [-100801, -100802]
    assert restored.entities[0].type == "bold"
    assert restored.media_items[0].file_id == "file-id"
    assert restored.media_items[0].width == 1280
    assert restored.raw_metadata["source_backend"] == "telegram"


async def test_mark_failed_keeps_payload_and_stores_error_separately(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(settings_env, session_factory)
    message = _message()
    async with session_factory() as session:
        repo = MessageRepository(session)
        record = await repo.try_create(
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            status=MessageStatus.PUBLISHING.value,
            target_chat_id=message.target_chat_id,
            processing_result=message_to_dict(message),
        )
        assert record is not None
        record_id = record.id
        await session.commit()

    await service._mark_failed(  # noqa: SLF001
        message,
        RuntimeError("publisher exploded"),
        record_id,
        increment_retry=True,
    )

    async with session_factory() as session:
        record = (
            await session.execute(select(ProcessedMessage).where(ProcessedMessage.id == record_id))
        ).scalar_one()
        assert record.status == MessageStatus.RETRYING.value
        assert record.error_message == "publisher exploded"
        assert record.processing_result == message_to_dict(message)
        assert "exception_type" not in record.processing_result


async def test_retry_rebuilds_complete_payload_and_rejects_old_error_summary(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(settings_env, session_factory)
    valid = _message()
    async with session_factory() as session:
        repo = MessageRepository(session)
        valid_record = await repo.try_create(
            source_chat_id=valid.source_chat_id,
            source_message_id=valid.source_message_id,
            status=MessageStatus.FAILED.value,
            target_chat_id=valid.target_chat_id,
            processing_result=message_to_dict(valid),
        )
        invalid_record = await repo.try_create(
            source_chat_id=-100701,
            source_message_id=11,
            status=MessageStatus.FAILED.value,
            target_chat_id=-100801,
            processing_result={
                "exception_type": "RuntimeError",
                "message": "the old payload was overwritten",
                "retry_class": "fatal",
            },
        )
        assert valid_record is not None
        assert invalid_record is not None
        valid_id = valid_record.id
        invalid_id = invalid_record.id
        await session.commit()

    assert await service.retry_failed() == 1
    queued = service.queue.get_nowait()
    assert queued is not None
    restored = queued.message
    assert restored.text == valid.text
    assert restored.target_chat_ids == valid.target_chat_ids
    assert restored.media_items[0].file_id == "file-id"
    assert restored.media_items[0].file_unique_id == "unique-id"
    assert restored.media_items[0].width == 1280
    assert restored.media_items[0].duration == 8
    assert service.queue.empty()

    async with session_factory() as session:
        valid_record = await session.get(ProcessedMessage, valid_id)
        invalid_record = await session.get(ProcessedMessage, invalid_id)
        assert valid_record is not None
        assert invalid_record is not None
        assert valid_record.status == MessageStatus.PENDING_PUBLISH.value
        assert invalid_record.status == MessageStatus.FAILED.value
        assert invalid_record.error_message == INVALID_STORED_PAYLOAD


async def test_recover_pending_skips_legacy_received_row_without_payload(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = _service(settings_env, session_factory)
    async with session_factory() as session:
        repo = MessageRepository(session)
        record = await repo.try_create(
            source_chat_id=-100702,
            source_message_id=12,
            status=MessageStatus.RECEIVED.value,
            target_chat_id=-100801,
        )
        assert record is not None
        record_id = record.id
        await session.commit()

    assert await service.recover_pending() == 0
    assert service.queue.empty()

    async with session_factory() as session:
        record = await session.get(ProcessedMessage, record_id)
        assert record is not None
        assert record.status == MessageStatus.FAILED.value
        assert record.error_message == INVALID_STORED_PAYLOAD
