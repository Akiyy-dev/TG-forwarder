"""Idempotent publish path for approved review tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProcessedMessage, ReviewTask
from app.database.repositories.message_repo import MessageRepository
from app.logging import get_logger
from app.messaging.models import message_to_dict
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.message import MediaItem, MediaType, MessageStatus, NormalizedMessage
from app.services.api_delivery_service import ApiDeliveryService
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.retry_service import exception_summary

logger = get_logger(__name__)

NO_CURRENT_REVIEW_TARGET = "no currently enabled target is bound to this review source"
REVIEW_SOURCE_DISABLED = "review source channel is currently disabled"


def message_from_task(task: ReviewTask) -> NormalizedMessage:
    snap = task.media_snapshot if isinstance(task.media_snapshot, dict) else {}
    items: list[MediaItem] = []
    for raw in snap.get("media_items") or []:
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
        source_chat_id=task.source_chat_id,
        source_message_id=task.source_message_id,
        text=task.final_text or "",
        media_type=MediaType(task.media_type or MediaType.TEXT.value),
        media_items=items,
        album_message_ids=list(snap.get("album_message_ids") or []),
        target_chat_id=task.target_chat_id,
    )


class ReviewPublishService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        review_service: ReviewService,
        publisher: TelegramPublisher,
        media_service: MediaService,
        channel_service: ChannelService,
    ) -> None:
        self.session_factory = session_factory
        self.review_service = review_service
        self.publisher = publisher
        self.media_service = media_service
        self.channel_service = channel_service
        self.api_delivery = ApiDeliveryService(session_factory)

    def _message_from_task(self, task: ReviewTask) -> NormalizedMessage:
        return message_from_task(task)

    async def ensure_task_media(self, task: ReviewTask) -> NormalizedMessage:
        """Rebuild local media files when TTL cleanup removed them."""
        message = message_from_task(task)
        if not self.media_service.media_missing(message):
            return message
        logger.info(
            "review_media_rematerialize",
            review_task_id=task.id,
            source_chat_id=task.source_chat_id,
            source_message_id=task.source_message_id,
        )
        message = await self.media_service.ensure_materialized(message)
        if self.media_service.media_missing(message):
            missing = [
                i.source_message_id or task.source_message_id
                for i in message.media_items
                if not i.local_path or not Path(i.local_path).is_file()
            ]
            msg = f"media file missing after rematerialize: {missing}"
            raise FileNotFoundError(msg)
        await self.review_service.update_media_snapshot(task.id, message)
        return message

    async def _current_targets(
        self,
        task: ReviewTask,
        snapshot_targets: list[int],
    ) -> list[int]:
        """Filter a review snapshot against the current channel routing state."""
        await self.channel_service.load_from_db()

        # Keep the snapshot order while preventing an accidental duplicate send.
        candidates = list(dict.fromkeys(int(target) for target in snapshot_targets))
        if task.source_chat_id in self.channel_service.configured_chat_ids:
            if not self.channel_service.is_enabled(task.source_chat_id):
                return []
            active_bindings = set(self.channel_service.get_targets_for(task.source_chat_id))
            return [target for target in candidates if target in active_bindings]
        return []

    async def _current_api_targets(
        self,
        task: ReviewTask,
        snapshot_targets: list[int],
    ) -> list[int]:
        return await self.api_delivery.active_endpoint_ids(task.source_chat_id, snapshot_targets)

    def _routing_block_reason(
        self,
        task: ReviewTask,
        targets: list[int],
        api_targets: list[int] | None = None,
    ) -> str | None:
        if (
            task.source_chat_id in self.channel_service.configured_chat_ids
            and not self.channel_service.is_enabled(task.source_chat_id)
        ):
            return REVIEW_SOURCE_DISABLED
        if not targets and not api_targets:
            return NO_CURRENT_REVIEW_TARGET
        return None

    async def _fail_claimed_task(
        self,
        task: ReviewTask,
        *,
        user_id: int | None,
        error_message: str,
        detail: dict[str, Any] | None = None,
        increment_retry: bool = False,
    ) -> dict[str, Any]:
        """Mark both halves of a claimed review publish as failed."""
        await self.review_service.transition(
            task.id,
            ReviewStatus.FAILED,
            user_id=user_id,
            action=ReviewActionType.PUBLISH_FAILED,
            expected_revision=task.revision,
            error_message=error_message,
            detail=detail,
        )
        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, task.processed_message_id)
            if processed:
                repo = MessageRepository(session)
                await repo.update_status(
                    processed,
                    MessageStatus.FAILED.value,
                    error_message=error_message,
                    increment_retry=increment_retry,
                )
                await session.commit()
        return {"status": ReviewStatus.FAILED.value, "error": error_message}

    async def publish_task(
        self,
        task_id: int,
        *,
        expected_revision: int,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        claimed = await self.review_service.claim_for_publish(
            task_id,
            expected_revision=expected_revision,
            user_id=user_id,
        )
        if claimed is None:
            async with self.session_factory() as session:
                task = await session.get(ReviewTask, task_id)
                if task and task.status == ReviewStatus.PUBLISHED.value:
                    return {
                        "status": task.status,
                        "already_published": True,
                        "target_message_ids": None,
                    }
            return {"status": "conflict", "already_published": False}

        snapshot_targets: list[int] = []
        if claimed.target_chat_ids:
            snapshot_targets = [int(x) for x in claimed.target_chat_ids if x is not None]
        elif claimed.target_chat_id is not None:
            snapshot_targets = [int(claimed.target_chat_id)]
        snapshot_api_targets = [int(value) for value in (claimed.target_api_endpoint_ids or [])]

        # Ensure processed_message not already published (idempotency)
        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, claimed.processed_message_id)
            if processed and processed.status == MessageStatus.PUBLISHED.value:
                await self.review_service.transition(
                    claimed.id,
                    ReviewStatus.PUBLISHED,
                    user_id=user_id,
                    action=ReviewActionType.PUBLISHED,
                    expected_revision=claimed.revision,
                    detail={"reused_target_ids": processed.target_message_ids},
                )
                return {
                    "status": ReviewStatus.PUBLISHED.value,
                    "already_published": True,
                    "target_message_ids": processed.target_message_ids,
                }

        try:
            targets = await self._current_targets(claimed, snapshot_targets)
            api_targets = await self._current_api_targets(claimed, snapshot_api_targets)
        except Exception as exc:  # noqa: BLE001
            summary = exception_summary(exc)
            logger.warning(
                "review_target_validation_failed",
                review_task_id=claimed.id,
                exception_type=summary["exception_type"],
            )
            return await self._fail_claimed_task(
                claimed,
                user_id=user_id,
                error_message=summary["message"],
                detail={"stage": "target_validation", **summary},
                increment_retry=True,
            )

        routing_block = self._routing_block_reason(claimed, targets, api_targets)
        if routing_block is not None:
            error_message = routing_block
            logger.warning(
                "review_publish_blocked_by_current_routing",
                review_task_id=claimed.id,
                source_chat_id=claimed.source_chat_id,
                reason=error_message,
            )
            return await self._fail_claimed_task(
                claimed,
                user_id=user_id,
                error_message=error_message,
                detail={
                    "stage": "target_validation",
                    "snapshot_target_chat_ids": snapshot_targets,
                    "snapshot_api_endpoint_ids": snapshot_api_targets,
                },
            )

        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, claimed.processed_message_id)
            if processed:
                repo = MessageRepository(session)
                await repo.update_status(processed, MessageStatus.PUBLISHING.value)
                await session.commit()

        try:
            message = (
                await self.ensure_task_media(claimed)
                if targets
                else self._message_from_task(claimed)
            )
            # Media recovery may take long enough for a source, target, or link
            # to be disabled. Re-resolve after it completes before sending.
            targets = await self._current_targets(claimed, snapshot_targets)
            api_targets = await self._current_api_targets(claimed, snapshot_api_targets)
            routing_block = self._routing_block_reason(claimed, targets, api_targets)
            if routing_block is not None:
                return await self._fail_claimed_task(
                    claimed,
                    user_id=user_id,
                    error_message=routing_block,
                    detail={
                        "stage": "post_media_target_validation",
                        "snapshot_target_chat_ids": snapshot_targets,
                        "snapshot_api_endpoint_ids": snapshot_api_targets,
                    },
                )
            message.target_chat_ids = list(targets)
            message.target_chat_id = targets[0] if targets else None
            all_ids: list[int] = []
            per_target: dict[str, Any] = {}
            errors: list[dict[str, Any]] = []
            routing_errors: list[dict[str, Any]] = []
            send_errors: list[dict[str, Any]] = []
            try:
                delivered_api_ids = await self.api_delivery.enqueue(
                    source_chat_id=claimed.source_chat_id,
                    processed_message_id=claimed.processed_message_id,
                    message=message,
                    endpoint_ids=api_targets,
                    review_task_id=claimed.id,
                )
            except Exception as exc:  # noqa: BLE001
                delivered_api_ids = []
                summary = exception_summary(exc)
                for endpoint_id in api_targets:
                    error = {"api_endpoint_id": endpoint_id, **summary}
                    per_target[f"api:{endpoint_id}"] = {
                        "ok": False,
                        "error": summary,
                    }
                    errors.append(error)
                    send_errors.append(error)
            published_count = len(delivered_api_ids)
            for endpoint_id in delivered_api_ids:
                per_target[f"api:{endpoint_id}"] = {"ok": True}
            for target in targets:
                # Minimise the validation-to-send window for multi-target tasks:
                # each destination must still be enabled and bound immediately
                # before its individual Telegram API call.
                current_targets = await self._current_targets(claimed, snapshot_targets)
                current_api_targets = await self._current_api_targets(claimed, snapshot_api_targets)
                current_block = self._routing_block_reason(
                    claimed, current_targets, current_api_targets
                )
                if current_block == REVIEW_SOURCE_DISABLED:
                    summary = {
                        "exception_type": "RoutingChanged",
                        "message": current_block,
                        "retry_class": "fatal",
                    }
                    error = {"target_chat_id": target, **summary}
                    per_target[str(target)] = {"ok": False, "error": summary}
                    errors.append(error)
                    routing_errors.append(error)
                    break
                if int(target) not in current_targets:
                    summary = {
                        "exception_type": "RoutingChanged",
                        "message": "target is no longer enabled and bound to this review source",
                        "retry_class": "fatal",
                    }
                    error = {"target_chat_id": target, **summary}
                    per_target[str(target)] = {"ok": False, "error": summary}
                    errors.append(error)
                    routing_errors.append(error)
                    continue

                message.target_chat_ids = list(current_targets)
                message.target_chat_id = current_targets[0]
                try:
                    ids = await self.publisher.publish(message, int(target))
                    all_ids.extend(ids)
                    per_target[str(target)] = {"ok": True, "message_ids": ids}
                    published_count += 1
                except Exception as exc:  # noqa: BLE001
                    summary = exception_summary(exc)
                    per_target[str(target)] = {"ok": False, "error": summary}
                    error = {"target_chat_id": target, **summary}
                    errors.append(error)
                    send_errors.append(error)
            if published_count == 0 and routing_errors and not send_errors:
                return await self._fail_claimed_task(
                    claimed,
                    user_id=user_id,
                    error_message=routing_errors[0]["message"],
                    detail={
                        "stage": "pre_send_target_validation",
                        "snapshot_target_chat_ids": snapshot_targets,
                        "routing_errors": routing_errors,
                    },
                )
            if published_count == 0:
                raise RuntimeError(errors[0]["message"] if errors else "publish failed")
            ids = all_ids
            publish_detail = {
                "target_message_ids": ids,
                "api_endpoint_ids": delivered_api_ids,
                "per_target": per_target,
            }
            if errors:
                publish_detail["partial_errors"] = errors
        except Exception as exc:
            summary = exception_summary(exc)
            await self.review_service.transition(
                claimed.id,
                ReviewStatus.FAILED,
                user_id=user_id,
                action=ReviewActionType.PUBLISH_FAILED,
                expected_revision=claimed.revision,
                error_message=summary["message"],
                detail=summary,
            )
            async with self.session_factory() as session:
                processed = await session.get(ProcessedMessage, claimed.processed_message_id)
                if processed:
                    repo = MessageRepository(session)
                    await repo.update_status(
                        processed,
                        MessageStatus.FAILED.value,
                        error_message=summary["message"],
                        increment_retry=True,
                    )
                    await session.commit()
            logger.warning(
                "review_publish_failed",
                review_task_id=claimed.id,
                exception_type=summary["exception_type"],
            )
            return {"status": ReviewStatus.FAILED.value, "error": summary["message"]}

        await self.review_service.transition(
            claimed.id,
            ReviewStatus.PUBLISHED,
            user_id=user_id,
            action=ReviewActionType.PUBLISHED,
            expected_revision=claimed.revision,
            detail=publish_detail,
        )
        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, claimed.processed_message_id)
            if processed:
                repo = MessageRepository(session)
                await repo.update_status(
                    processed,
                    MessageStatus.PUBLISHED.value,
                    target_message_ids=ids,
                    processing_result={
                        **message_to_dict(message),
                        "publish_mode": "review",
                    },
                )
                await session.commit()
        self.media_service.cleanup_message_files(message)
        return {
            "status": ReviewStatus.PUBLISHED.value,
            "already_published": False,
            "target_message_ids": ids,
            "per_target": per_target,
            "partial_errors": errors or None,
        }
