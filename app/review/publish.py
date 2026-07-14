"""Idempotent publish path for approved review tasks."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProcessedMessage, ReviewTask
from app.database.repositories.message_repo import MessageRepository
from app.logging import get_logger
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.service import ReviewService
from app.review.state_machine import ReviewActionType, ReviewStatus
from app.schemas.message import MediaItem, MediaType, MessageStatus, NormalizedMessage
from app.services.media_service import MediaService
from app.services.retry_service import exception_summary

logger = get_logger(__name__)


class ReviewPublishService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        review_service: ReviewService,
        publisher: TelegramPublisher,
        media_service: MediaService,
    ) -> None:
        self.session_factory = session_factory
        self.review_service = review_service
        self.publisher = publisher
        self.media_service = media_service

    def _message_from_task(self, task: ReviewTask) -> NormalizedMessage:
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

        message = self._message_from_task(claimed)
        target = claimed.target_chat_id
        if target is None:
            await self.review_service.transition(
                claimed.id,
                ReviewStatus.FAILED,
                user_id=user_id,
                action=ReviewActionType.PUBLISH_FAILED,
                expected_revision=claimed.revision,
                error_message="missing target_chat_id",
            )
            return {"status": ReviewStatus.FAILED.value, "error": "missing target_chat_id"}

        # Ensure processed_message not already published (idempotency)
        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, claimed.processed_message_id)
            if processed and processed.target_message_ids:
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
            if processed:
                repo = MessageRepository(session)
                await repo.update_status(processed, MessageStatus.PUBLISHING.value)
                await session.commit()

        try:
            ids = await self.publisher.publish(message, int(target))
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
            detail={"target_message_ids": ids},
        )
        async with self.session_factory() as session:
            processed = await session.get(ProcessedMessage, claimed.processed_message_id)
            if processed:
                repo = MessageRepository(session)
                await repo.update_status(
                    processed,
                    MessageStatus.PUBLISHED.value,
                    target_message_ids=ids,
                )
                await session.commit()
        self.media_service.cleanup_message_files(message)
        return {
            "status": ReviewStatus.PUBLISHED.value,
            "already_published": False,
            "target_message_ids": ids,
        }
