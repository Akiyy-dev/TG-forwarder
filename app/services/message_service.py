"""Message orchestration: enqueue, process, publish, recover."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.repositories.message_repo import MessageRepository
from app.database.repositories.settings_repo import SettingsRepository
from app.logging import get_logger
from app.messaging.models import message_from_dict, message_to_dict
from app.processors.deduplication import DeduplicationProcessor
from app.processors.pipeline import ProcessorPipeline, build_default_pipeline
from app.review.service import ReviewService
from app.schemas.channel import PublishMode, TargetRoute
from app.schemas.message import (
    MessageStatus,
    NormalizedMessage,
    ProcessAction,
    ProcessingContext,
)
from app.services.api_delivery_service import ApiDeliveryService
from app.services.channel_service import ChannelService
from app.services.history_service import HistoryService
from app.services.media_service import MediaService
from app.services.retry_service import exception_summary
from app.source_backends import source_backend_for_chat_id

logger = get_logger(__name__)

INVALID_STORED_PAYLOAD = "stored normalized payload is missing or invalid; recovery skipped"
NO_ENABLED_TARGET = "no enabled target channel configured"
SOURCE_DISABLED = "source channel is currently disabled"


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
        publisher: Any,
        media_service: MediaService,
        review_service: ReviewService | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.channel_service = channel_service
        self.publisher = publisher
        self.media_service = media_service
        self.review_service = review_service or ReviewService(session_factory)
        self.api_delivery = ApiDeliveryService(session_factory)
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

    async def _publish_target(
        self,
        message: NormalizedMessage,
        target: TargetRoute,
    ) -> list[int]:
        publish_target = getattr(self.publisher, "publish_target", None)
        if publish_target is not None:
            return cast(list[int], await publish_target(message, target))
        return cast(list[int], await self.publisher.publish(message, target.chat_id))

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

    def _resolve_targets(self, message: NormalizedMessage) -> list[int]:
        """Resolve routing exclusively from the current Web-managed registry."""
        return self.channel_service.get_targets_for(message.source_chat_id)

    def _routing_block_reason(
        self,
        source_chat_id: int,
        targets: list[int],
        has_api_target: bool = False,
    ) -> str | None:
        if (
            source_chat_id in self.channel_service.configured_chat_ids
            and not self.channel_service.is_enabled(source_chat_id)
        ):
            return SOURCE_DISABLED
        if not targets and not has_api_target:
            return NO_ENABLED_TARGET
        return None

    async def _refresh_routing(
        self,
        message: NormalizedMessage,
    ) -> tuple[list[int], str | None]:
        """Reload routing and return only destinations that are still publishable."""
        await self.channel_service.load_from_db()
        targets = self._resolve_targets(message)
        api_endpoint_ids = await self.api_delivery.active_endpoint_ids(message.source_chat_id)
        reason = self._routing_block_reason(message.source_chat_id, targets, bool(api_endpoint_ids))
        if reason == SOURCE_DISABLED:
            targets = []
        message.target_chat_ids = list(targets)
        message.target_chat_id = targets[0] if targets else None
        return targets, reason

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
        targets = self._resolve_targets(message)
        message.target_chat_ids = list(targets)
        message.target_chat_id = targets[0] if targets else None
        payload = message_to_dict(message)

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
                    processing_result=(payload if mid == message.source_message_id else None),
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
                    if existing is not None:
                        await repo.update_payload(existing, payload)
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
        # Incoming stream events and locally queued retries can outlive the
        # sender's routing cache. Always consult the database before deciding
        # whether this source is still enabled or where it may publish.
        targets, routing_block = await self._refresh_routing(message)
        payload = message_to_dict(message)

        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                record = await repo.try_create(
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    grouped_id=message.grouped_id,
                    status=MessageStatus.RECEIVED.value,
                    target_chat_id=message.target_chat_id,
                    processing_result=payload,
                )
            if record is None:
                await session.commit()
                return
            if record.status == MessageStatus.PUBLISHED.value:
                await session.commit()
                return
            if routing_block is not None:
                reason = routing_block
                record.target_chat_id = None
                await repo.update_status(
                    record,
                    MessageStatus.FAILED.value,
                    error_message=reason,
                    processing_result=payload,
                )
                await session.commit()
                self._last_error = (
                    "SourceDisabled" if reason == SOURCE_DISABLED else "NoEnabledTarget"
                )
                logger.error(
                    "message_routing_blocked",
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    reason=reason,
                )
                self.history.write(
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    payload={
                        "status": MessageStatus.FAILED.value,
                        "text": message.text,
                        "reason": reason,
                        "media_type": message.media_type.value,
                        "target_chat_ids": [],
                    },
                )
                return
            await repo.update_status(
                record,
                MessageStatus.PROCESSING.value,
                processing_result=payload,
            )
            await session.commit()
            record_id = record.id

        # Processing rules historically receive a Telegram destination. API-only
        # sources use 0 as a neutral context value; delivery routing is handled
        # independently after processing has completed.
        target = targets[0] if targets else 0

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
                filtered_message = result.message or message
                filtered_payload = message_to_dict(filtered_message)
                filtered_payload["action"] = result.action.value
                await repo.update_status(
                    record,
                    MessageStatus.FILTERED.value,
                    skip_reason=result.reason,
                    content_hash=content_hash,
                    processing_result=filtered_payload,
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
                failed_message = result.message or message
                await repo.update_status(
                    record,
                    MessageStatus.FAILED.value,
                    error_message=result.reason,
                    content_hash=content_hash,
                    processing_result=message_to_dict(failed_message),
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
                processed_msg = result.message or message
                review_payload = message_to_dict(processed_msg)
                review_payload.update(
                    {
                        "action": ProcessAction.REVIEW.value,
                        "publish_mode": publish_mode.value,
                    }
                )
                await repo.update_status(
                    record,
                    MessageStatus.PENDING_REVIEW.value,
                    skip_reason=decision_reason,
                    content_hash=content_hash,
                    processing_result=review_payload,
                )
                await session.commit()
                detail = result.detail if isinstance(result.detail, dict) else {}
                api_endpoint_ids = await self.api_delivery.active_endpoint_ids(
                    message.source_chat_id
                )
                target_destination_ids = [
                    route.id
                    for route in self.channel_service.get_target_routes_for(
                        message.source_chat_id
                    )
                ]
                await self.review_service.create_from_message(
                    processed=record,
                    original_text=original_text,
                    processed_message=processed_msg,
                    decision_reason=decision_reason,
                    matched_rules=list(detail.get("matched_rules") or []),
                    detected_keywords=list(detail.get("detected_keywords") or []),
                    target_destination_ids=target_destination_ids,
                    target_api_endpoint_ids=api_endpoint_ids,
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
            publish_payload = message_to_dict(publish_msg)
            publish_payload["publish_mode"] = publish_mode.value
            await repo.update_status(
                record,
                MessageStatus.PENDING_PUBLISH.value,
                content_hash=content_hash,
                processing_result=publish_payload,
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

        await self._publish(result.message or message, record_id)

    async def process_durable(self, message: NormalizedMessage) -> None:
        """Process a stream event before its external acknowledgement.

        Redis consumers use this path so a sender crash leaves the event pending
        with its complete normalized payload and shared-volume media paths.
        """
        async with self._global_sem:
            lock = self._channel_locks[message.source_chat_id]
            async with lock:
                await self.process_one(QueueItem(message=message))

    async def _publish(
        self,
        message: NormalizedMessage,
        record_id: int,
    ) -> None:
        try:
            targets, routing_block = await self._refresh_routing(message)
            target_routes = self.channel_service.get_target_routes_for(message.source_chat_id)
            api_endpoint_ids = await self.api_delivery.active_endpoint_ids(message.source_chat_id)
        except Exception as exc:
            await self._mark_failed(message, exc, record_id, increment_retry=True)
            return

        if routing_block is not None:
            await self._mark_routing_failed(message, routing_block)
            return

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

        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                return
            if record.status == MessageStatus.PUBLISHED.value:
                await session.commit()
                return
            await repo.update_status(record, MessageStatus.PUBLISHING.value)
            await session.commit()

        try:
            ids: list[int] = []
            published_targets: list[int] = []
            last_exc: BaseException | None = None
            try:
                delivered_api_ids = await self.api_delivery.enqueue(
                    source_chat_id=message.source_chat_id,
                    processed_message_id=record_id,
                    message=message,
                    endpoint_ids=api_endpoint_ids,
                )
            except Exception as exc:  # noqa: BLE001
                delivered_api_ids = []
                last_exc = exc
            success = len(delivered_api_ids)
            routing_failure: str | None = None
            published_destinations: list[dict[str, Any]] = []
            for route in target_routes:
                current_targets, current_block = await self._refresh_routing(message)
                current_routes = self.channel_service.get_target_routes_for(message.source_chat_id)
                if current_block == SOURCE_DISABLED:
                    routing_failure = current_block
                    break
                if route.id not in {current.id for current in current_routes}:
                    routing_failure = NO_ENABLED_TARGET
                    continue
                try:
                    ids.extend(await self._publish_target(message, route))
                    published_targets.append(route.chat_id)
                    published_destinations.append(
                        {
                            "id": route.id,
                            "target_backend": route.target_backend.value,
                            "chat_id": route.chat_id,
                        }
                    )
                    success += 1
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            if success == 0:
                if last_exc is not None:
                    raise last_exc
                await self._mark_routing_failed(
                    message,
                    routing_failure or NO_ENABLED_TARGET,
                )
                return
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
                "target_chat_ids": published_targets,
                "target_destinations": published_destinations,
                "target_message_ids": ids,
                "api_endpoint_ids": delivered_api_ids,
            },
        )

    async def _mark_routing_failed(
        self,
        message: NormalizedMessage,
        reason: str,
    ) -> None:
        """Terminally fail a stale queued event when its current route is blocked."""
        self._last_error = "SourceDisabled" if reason == SOURCE_DISABLED else "NoEnabledTarget"
        message.target_chat_ids = []
        message.target_chat_id = None
        async with self.session_factory() as session:
            repo = MessageRepository(session)
            record = await repo.get_by_source(message.source_chat_id, message.source_message_id)
            if record is None:
                return
            record.target_chat_id = None
            await repo.update_status(
                record,
                MessageStatus.FAILED.value,
                error_message=reason,
                processing_result=message_to_dict(message),
            )
            await session.commit()
        logger.warning(
            "message_routing_blocked_before_publish",
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            reason=reason,
        )
        self.history.write(
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            payload={
                "status": MessageStatus.FAILED.value,
                "text": message.text,
                "reason": reason,
                "media_type": message.media_type.value,
                "target_chat_ids": [],
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
                processing_result=message_to_dict(message),
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
                msg = self._message_from_record(record)
                if msg is None:
                    await self._mark_invalid_stored_payload(repo, record)
                    continue
                await repo.update_status(record, MessageStatus.PENDING_PUBLISH.value)
                count += 1
                await self.queue.put(QueueItem(message=msg))
            await session.commit()
        return count

    def _message_from_record(self, record: Any) -> NormalizedMessage | None:
        payload = record.processing_result
        if not isinstance(payload, dict):
            return None

        # Legacy recoverable records stored a partial message dictionary. Backfill
        # identifiers from their columns, but reject error summaries and empty
        # shells so they can never become blank outbound Telegram messages.
        has_legacy_message_shape = any(
            key in payload for key in ("text", "media_type", "media_items")
        )
        if not has_legacy_message_shape:
            return None
        restored_payload = dict(payload)
        restored_payload.setdefault("source_chat_id", record.source_chat_id)
        restored_payload.setdefault("source_message_id", record.source_message_id)
        restored_payload.setdefault("grouped_id", record.grouped_id)
        restored_payload.setdefault("target_chat_id", record.target_chat_id)
        if "target_chat_ids" not in restored_payload:
            target = record.target_chat_id
            restored_payload["target_chat_ids"] = [target] if target is not None else []

        try:
            message = message_from_dict(restored_payload)
        except (KeyError, TypeError, ValueError):
            return None
        if message.source_chat_id != record.source_chat_id:
            return None
        if message.source_message_id != record.source_message_id:
            return None
        if not message.text.strip() and not message.media_items:
            return None
        return message

    async def _mark_invalid_stored_payload(self, repo: MessageRepository, record: Any) -> None:
        self._last_error = "InvalidStoredPayload"
        previous_status = record.status
        await repo.update_status(
            record,
            MessageStatus.FAILED.value,
            error_message=INVALID_STORED_PAYLOAD,
        )
        logger.error(
            "message_recovery_skipped_invalid_payload",
            source_chat_id=record.source_chat_id,
            source_message_id=record.source_message_id,
            previous_status=previous_status,
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
                msg = self._message_from_record(record)
                if msg is None:
                    await self._mark_invalid_stored_payload(repo, record)
                    continue
                # Stuck publishing -> retry
                if record.status == MessageStatus.PUBLISHING.value:
                    await repo.update_status(record, MessageStatus.RETRYING.value)
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
                "source_backend": source_backend_for_chat_id(int(r.source_chat_id)),
                "error": r.error_message,
                "retry_count": r.retry_count,
            }
            for r in rows
        ]
