"""Message orchestration: enqueue, process, publish, recover."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.repositories.message_repo import MessageRepository
from app.database.repositories.settings_repo import SettingsRepository
from app.logging import get_logger
from app.processors.deduplication import DeduplicationProcessor
from app.processors.pipeline import ProcessorPipeline, build_default_pipeline
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.service import ReviewService
from app.schemas.channel import PublishMode
from app.schemas.message import (
    MessageStatus,
    NormalizedMessage,
    ProcessAction,
    ProcessingContext,
)
from app.services.channel_service import ChannelService
from app.services.history_service import HistoryService
from app.services.media_service import MediaService
from app.services.retry_service import exception_summary

logger = get_logger(__name__)


@dataclass
class QueueItem:
    message: NormalizedMessage
    raw_messages: list[Any] | None = None


class MessageService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        channel_service: ChannelService,
        publisher: TelegramPublisher,
        media_service: MediaService,
        review_service: ReviewService | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.channel_service = channel_service
        self.publisher = publisher
        self.media_service = media_service
        self.review_service = review_service or ReviewService(session_factory)
        self.history = HistoryService()
        self.queue: asyncio.Queue[QueueItem | None] = asyncio.Queue(maxsize=settings.queue_maxsize)
        self._channel_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_sem = asyncio.Semaphore(settings.max_concurrency)
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._paused = False
        self._last_error: str | None = None
        self._queue_depth = 0
        self.pipeline = self._build_pipeline()

    def _build_pipeline(self) -> ProcessorPipeline:
        async def exists(content_hash: str) -> bool:
            async with self.session_factory() as session:
                repo = MessageRepository(session)
                found = await repo.find_by_content_hash(
                    content_hash,
                    within_hours=self.settings.duplicate_content_window_hours,
                )
                return found is not None

        return build_default_pipeline(
            self.settings,
            duplicate_exists_fn=exists,
            session_factory=self.session_factory,
        )

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def queue_size(self) -> int:
        return self.queue.qsize()

    async def refresh_paused(self) -> bool:
        async with self.session_factory() as session:
            repo = SettingsRepository(session)
            self._paused = await repo.is_paused()
        return self._paused

    async def set_paused(self, paused: bool) -> None:
        async with self.session_factory() as session:
            repo = SettingsRepository(session)
            await repo.set_paused(paused)
            await session.commit()
        self._paused = paused

    async def resume_publishing(self) -> int:
        """Clear pause flag and re-queue pending_publish / stuck jobs."""
        await self.set_paused(False)
        return await self.recover_pending()

    async def start_workers(self, worker_count: int | None = None) -> None:
        await self.refresh_paused()
        self._running = True
        n = worker_count or max(1, self.settings.max_concurrency)
        self._workers = [asyncio.create_task(self._worker_loop(i)) for i in range(n)]
        logger.info("workers_started", count=n)

    async def stop_workers(self) -> None:
        self._running = False
        for _ in self._workers:
            await self.queue.put(None)
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("workers_stopped")

    async def enqueue(
        self,
        message: NormalizedMessage,
        raw_messages: list[Any] | None = None,
    ) -> bool:
        """Fast path from listener: register + enqueue. Returns False if duplicate."""
        targets = self.channel_service.get_targets_for(message.source_chat_id)
        if not message.target_chat_ids:
            message.target_chat_ids = list(targets)
        if message.target_chat_id is None:
            message.target_chat_id = targets[0] if targets else self.settings.target_channel_id

        # Idempotency: create rows for primary and album parts
        ids_to_register = message.album_message_ids or [message.source_message_id]
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            created_any = False
            primary: Any = None
            for mid in ids_to_register:
                status = (
                    MessageStatus.COLLECTING_ALBUM.value
                    if message.grouped_id and mid != message.source_message_id
                    else MessageStatus.RECEIVED.value
                )
                record = await repo.try_create(
                    source_chat_id=message.source_chat_id,
                    source_message_id=mid,
                    grouped_id=message.grouped_id,
                    status=status,
                    target_chat_id=message.target_chat_id,
                )
                if record is not None:
                    created_any = True
                    if mid == message.source_message_id:
                        primary = record
                elif mid == message.source_message_id:
                    existing = await repo.get_by_source(message.source_chat_id, mid)
                    if existing and existing.status in {
                        MessageStatus.PUBLISHED.value,
                        MessageStatus.FILTERED.value,
                        MessageStatus.PUBLISHING.value,
                        MessageStatus.PENDING_PUBLISH.value,
                        MessageStatus.PROCESSING.value,
                    }:
                        await session.commit()
                        logger.info(
                            "message_duplicate_skipped",
                            source_chat_id=message.source_chat_id,
                            source_message_id=mid,
                            status=existing.status,
                        )
                        return False
            await session.commit()

        if not created_any and primary is None:
            # All ids already known; still allow recovery retries via explicit retry path
            async with self.session_factory() as session:
                repo = MessageRepository(session)
                existing = await repo.get_by_source(
                    message.source_chat_id, message.source_message_id
                )
                if existing and existing.status == MessageStatus.PUBLISHED.value:
                    return False

        try:
            self.queue.put_nowait(QueueItem(message=message, raw_messages=raw_messages))
        except asyncio.QueueFull:
            self._last_error = "QueueFull"
            logger.error(
                "queue_full",
                source_chat_id=message.source_chat_id,
                source_message_id=message.source_message_id,
            )
            return False
        return True

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            item = await self.queue.get()
            try:
                if item is None:
                    return
                async with self._global_sem:
                    lock = self._channel_locks[item.message.source_chat_id]
                    async with lock:
                        await self.process_one(item)
            except Exception as exc:
                self._last_error = type(exc).__name__
                logger.exception(
                    "worker_error",
                    worker_id=worker_id,
                    exception_type=type(exc).__name__,
                )
            finally:
                self.queue.task_done()

    async def process_one(self, item: QueueItem) -> None:
        message = item.message
        targets = message.target_chat_ids or self.channel_service.get_targets_for(
            message.source_chat_id
        )
        message.target_chat_ids = list(targets)
        if message.target_chat_id is None:
            message.target_chat_id = targets[0] if targets else self.settings.target_channel_id
        target = message.target_chat_id

        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                record = await repo.try_create(
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    grouped_id=message.grouped_id,
                    status=MessageStatus.RECEIVED.value,
                    target_chat_id=target,
                )
            if record is None:
                await session.commit()
                return
            if record.status == MessageStatus.PUBLISHED.value and record.target_message_ids:
                await session.commit()
                return
            await repo.update_status(record, MessageStatus.PROCESSING.value)
            await session.commit()
            record_id = record.id

        original_text = message.text or ""

        # Download media
        try:
            message = await self.media_service.materialize(message, item.raw_messages)
            if self.media_service.media_missing(message):
                msg = "media incomplete after download"
                raise FileNotFoundError(msg)
        except Exception as exc:
            await self._mark_failed(message, exc, record_id)
            return

        context = ProcessingContext(
            target_chat_id=target,
            source_username=message.source_chat_username,
            paused=self._paused,
        )
        result, logs = await self.pipeline.run(message, context)
        content_hash = context.extra.get("content_hash") or DeduplicationProcessor.compute_hash(
            result.message or message
        )

        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                await session.commit()
                return
            for entry in logs:
                await repo.add_log(
                    record.id,
                    entry["processor"],
                    entry["status"],
                    detail={"reason": entry.get("reason"), **(entry.get("detail") or {})},
                    duration_ms=entry.get("duration_ms"),
                )

            if result.action == ProcessAction.DROP:
                await repo.update_status(
                    record,
                    MessageStatus.FILTERED.value,
                    skip_reason=result.reason,
                    content_hash=content_hash,
                    processing_result={"action": result.action.value},
                )
                await session.commit()
                self.media_service.cleanup_message_files(message)
                self.history.write(
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    payload={
                        "status": MessageStatus.FILTERED.value,
                        "text": original_text,
                        "reason": result.reason,
                        "media_type": message.media_type.value,
                    },
                )
                return

            if result.action == ProcessAction.FAIL:
                await repo.update_status(
                    record,
                    MessageStatus.FAILED.value,
                    error_message=result.reason,
                    content_hash=content_hash,
                )
                await session.commit()
                return

            publish_mode = self.channel_service.get_publish_mode(message.source_chat_id)
            force_review = (
                result.action == ProcessAction.CONTINUE and publish_mode == PublishMode.REVIEW
            )
            if result.action == ProcessAction.REVIEW or force_review:
                decision_reason = (
                    result.reason
                    if result.action == ProcessAction.REVIEW
                    else "channel_publish_mode_review"
                )
                await repo.update_status(
                    record,
                    MessageStatus.PENDING_REVIEW.value,
                    skip_reason=decision_reason,
                    content_hash=content_hash,
                    processing_result={
                        "action": ProcessAction.REVIEW.value,
                        "text": (result.message or message).text,
                        "publish_mode": publish_mode.value,
                    },
                )
                await session.commit()
                processed_msg = result.message or message
                detail = result.detail if isinstance(result.detail, dict) else {}
                await self.review_service.create_from_message(
                    processed=record,
                    original_text=original_text,
                    processed_message=processed_msg,
                    decision_reason=decision_reason,
                    matched_rules=list(detail.get("matched_rules") or []),
                    detected_keywords=list(detail.get("detected_keywords") or []),
                )
                self.history.write(
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    payload={
                        "status": MessageStatus.PENDING_REVIEW.value,
                        "text": processed_msg.text,
                        "original_text": original_text,
                        "reason": decision_reason,
                        "matched_rules": detail.get("matched_rules"),
                        "media_type": processed_msg.media_type.value,
                        "target_chat_ids": processed_msg.target_chat_ids,
                    },
                )
                return

            publish_msg = result.message or message
            await repo.update_status(
                record,
                MessageStatus.PENDING_PUBLISH.value,
                content_hash=content_hash,
                processing_result={
                    "text": publish_msg.text,
                    "media_type": publish_msg.media_type.value,
                    "album_message_ids": publish_msg.album_message_ids,
                    "publish_mode": publish_mode.value,
                    "media_items": [
                        {
                            "media_type": i.media_type.value,
                            "local_path": i.local_path,
                            "original_filename": i.original_filename,
                            "mime_type": i.mime_type,
                            "file_size": i.file_size,
                            "source_message_id": i.source_message_id,
                            "order": i.order,
                            "file_unique_id": i.file_unique_id,
                        }
                        for i in publish_msg.media_items
                    ],
                },
            )
            await session.commit()

        publish_mode = self.channel_service.get_publish_mode(message.source_chat_id)
        if self._paused or publish_mode == PublishMode.PAUSED:
            logger.info(
                "publish_paused",
                source_chat_id=message.source_chat_id,
                source_message_id=message.source_message_id,
                publish_mode=publish_mode.value,
                global_paused=self._paused,
            )
            return

        await self._publish(result.message or message, target, record_id)

    async def _publish(
        self,
        message: NormalizedMessage,
        target: int,
        record_id: int,
    ) -> None:
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                return
            if record.target_message_ids:
                await session.commit()
                return
            await repo.update_status(record, MessageStatus.PUBLISHING.value)
            await session.commit()

        try:
            targets = list(message.target_chat_ids) or [target]
            ids: list[int] = []
            last_exc: BaseException | None = None
            success = 0
            for t in targets:
                try:
                    ids.extend(await self.publisher.publish(message, int(t)))
                    success += 1
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            if success == 0 and last_exc is not None:
                raise last_exc
        except Exception as exc:
            await self._mark_failed(message, exc, record_id, increment_retry=True)
            return

        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is not None:
                await repo.update_status(
                    record,
                    MessageStatus.PUBLISHED.value,
                    target_message_ids=ids,
                )
            await session.commit()
        self.media_service.cleanup_message_files(message)
        self.history.write(
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            payload={
                "status": MessageStatus.PUBLISHED.value,
                "text": message.text,
                "media_type": message.media_type.value,
                "target_chat_ids": message.target_chat_ids or [target],
                "target_message_ids": ids,
            },
        )

    async def _mark_failed(
        self,
        message: NormalizedMessage,
        exc: BaseException,
        record_id: int,
        *,
        increment_retry: bool = False,
    ) -> None:
        summary = exception_summary(exc)
        self._last_error = summary["exception_type"]
        retry_count = 0
        status = MessageStatus.FAILED.value
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                return
            status = MessageStatus.RETRYING.value if increment_retry else MessageStatus.FAILED.value
            if increment_retry and record.retry_count + 1 >= self.settings.max_retries:
                status = MessageStatus.FAILED.value
            await repo.update_status(
                record,
                status,
                error_message=summary["message"],
                increment_retry=increment_retry,
                processing_result=summary,
            )
            retry_count = record.retry_count
            await session.commit()
        logger.error(
            "message_failed",
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            exception_type=summary["exception_type"],
            status=status,
            retry_count=retry_count,
        )

    async def retry_failed(self, limit: int = 50) -> int:
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            records = await repo.list_by_status(
                [MessageStatus.FAILED.value, MessageStatus.RETRYING.value],
                limit=limit,
            )
            # Reset to pending; full re-download needs live Telethon refs — phase-1 retries
            # text-only / already-local paths by re-enqueueing shell messages.
            count = 0
            for record in records:
                if record.target_message_ids:
                    continue
                await repo.update_status(record, MessageStatus.PENDING_PUBLISH.value)
                msg = self._message_from_record(record)
                count += 1
                await self.queue.put(QueueItem(message=msg))
            await session.commit()
        return count

    def _message_from_record(self, record: Any) -> NormalizedMessage:
        from app.schemas.message import MediaItem, MediaType

        payload = record.processing_result if isinstance(record.processing_result, dict) else {}
        media_type = MediaType(payload.get("media_type", MediaType.TEXT.value))
        items = []
        for raw in payload.get("media_items") or []:
            items.append(
                MediaItem(
                    media_type=MediaType(raw.get("media_type", MediaType.DOCUMENT.value)),
                    local_path=raw.get("local_path"),
                    original_filename=raw.get("original_filename"),
                    mime_type=raw.get("mime_type"),
                    file_size=raw.get("file_size"),
                    source_message_id=raw.get("source_message_id"),
                    order=int(raw.get("order") or 0),
                    file_unique_id=raw.get("file_unique_id"),
                )
            )
        return NormalizedMessage(
            source_chat_id=record.source_chat_id,
            source_message_id=record.source_message_id,
            grouped_id=record.grouped_id,
            text=str(payload.get("text") or ""),
            media_type=media_type,
            media_items=items,
            album_message_ids=list(payload.get("album_message_ids") or []),
            target_chat_id=record.target_chat_id or self.settings.target_channel_id,
        )

    async def recover_pending(self) -> int:
        """On startup, re-queue messages stuck in recoverable states."""
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            records = await repo.list_by_status(
                [
                    MessageStatus.PENDING_PUBLISH.value,
                    MessageStatus.RETRYING.value,
                    MessageStatus.PUBLISHING.value,
                    MessageStatus.PROCESSING.value,
                    MessageStatus.RECEIVED.value,
                ],
                limit=200,
            )
            count = 0
            for record in records:
                if record.target_message_ids:
                    await repo.update_status(record, MessageStatus.PUBLISHED.value)
                    continue
                # Stuck publishing -> retry
                if record.status == MessageStatus.PUBLISHING.value:
                    await repo.update_status(record, MessageStatus.RETRYING.value)
                msg = self._message_from_record(record)
                try:
                    self.queue.put_nowait(QueueItem(message=msg))
                    count += 1
                except asyncio.QueueFull:
                    break
            await session.commit()
        logger.info("recovered_pending", count=count)
        return count

    async def stats(self) -> dict[str, int]:
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            return await repo.count_by_status()

    async def recent_errors(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            rows = await repo.recent_errors()
        return [
            {
                "source_chat_id": r.source_chat_id,
                "source_message_id": r.source_message_id,
                "error": r.error_message,
                "retry_count": r.retry_count,
            }
            for r in rows
        ]
