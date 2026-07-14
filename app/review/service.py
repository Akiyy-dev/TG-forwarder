"""Review task orchestration and version history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ContentRevision, ProcessedMessage, ReviewAction, ReviewTask
from app.logging import get_logger
from app.review.state_machine import (
    IllegalTransitionError,
    ReviewActionType,
    ReviewStatus,
    assert_transition,
)
from app.schemas.message import NormalizedMessage

logger = get_logger(__name__)


class ReviewConflictError(Exception):
    def __init__(self, message: str = "Review task was modified by another user") -> None:
        self.message = message
        super().__init__(message)


class ReviewService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def create_from_message(
        self,
        *,
        processed: ProcessedMessage,
        original_text: str,
        processed_message: NormalizedMessage,
        matched_rules: list[Any] | None = None,
        detected_keywords: list[Any] | None = None,
        decision_reason: str | None = None,
    ) -> ReviewTask:
        async with self.session_factory() as session:
            existing = await session.execute(
                select(ReviewTask).where(ReviewTask.processed_message_id == processed.id)
            )
            task = existing.scalar_one_or_none()
            if task is not None:
                return task

            media_snapshot = {
                "media_type": processed_message.media_type.value,
                "album_message_ids": processed_message.album_message_ids,
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
                    for i in processed_message.media_items
                ],
            }
            processed_text = processed_message.text or ""
            task = ReviewTask(
                processed_message_id=processed.id,
                status=ReviewStatus.PENDING.value,
                source_chat_id=processed.source_chat_id,
                source_message_id=processed.source_message_id,
                target_chat_id=processed.target_chat_id,
                original_text=original_text or "",
                processed_text=processed_text,
                final_text=processed_text,
                media_type=processed_message.media_type.value,
                media_count=len(processed_message.media_items),
                matched_rules=matched_rules or [],
                detected_keywords=detected_keywords or [],
                decision_reason=decision_reason,
                revision=1,
                media_snapshot=media_snapshot,
            )
            session.add(task)
            await session.flush()
            session.add(
                ContentRevision(
                    review_task_id=task.id,
                    revision_number=1,
                    source="original",
                    content=original_text or "",
                    created_by=None,
                )
            )
            session.add(
                ContentRevision(
                    review_task_id=task.id,
                    revision_number=2,
                    source="rules",
                    content=processed_text,
                    created_by=None,
                )
            )
            task.revision = 2
            session.add(
                ReviewAction(
                    review_task_id=task.id,
                    user_id=None,
                    action=ReviewActionType.CREATED.value,
                    old_status=None,
                    new_status=ReviewStatus.PENDING.value,
                    detail={"reason": decision_reason},
                )
            )
            await session.commit()
            await session.refresh(task)
            logger.info(
                "review_task_created",
                review_task_id=task.id,
                source_chat_id=task.source_chat_id,
                source_message_id=task.source_message_id,
            )
            return task

    async def transition(
        self,
        task_id: int,
        new_status: ReviewStatus,
        *,
        user_id: int | None = None,
        action: ReviewActionType,
        expected_revision: int | None = None,
        detail: dict[str, Any] | None = None,
        client_ip: str | None = None,
        user_agent: str | None = None,
        error_message: str | None = None,
    ) -> ReviewTask:
        async with self.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                msg = "review task not found"
                raise LookupError(msg)
            if expected_revision is not None and task.revision != expected_revision:
                raise ReviewConflictError()
            old = ReviewStatus(task.status)
            assert_transition(old, new_status)
            task.status = new_status.value
            task.revision += 1
            now = datetime.now(UTC)
            if new_status == ReviewStatus.APPROVED:
                task.approved_at = now
            elif new_status == ReviewStatus.REJECTED:
                task.rejected_at = now
            elif new_status == ReviewStatus.PUBLISHING:
                task.publishing_started_at = now
            elif new_status == ReviewStatus.PUBLISHED:
                task.published_at = now
                task.published_revision = task.revision
            elif new_status == ReviewStatus.FAILED:
                task.error_message = error_message
            session.add(
                ReviewAction(
                    review_task_id=task.id,
                    user_id=user_id,
                    action=action.value,
                    old_status=old.value,
                    new_status=new_status.value,
                    detail=detail,
                    client_ip=client_ip,
                    user_agent=user_agent,
                )
            )
            await session.commit()
            await session.refresh(task)
            return task

    async def edit_text(
        self,
        task_id: int,
        content: str,
        *,
        user_id: int,
        expected_revision: int,
        source: str = "reviewer",
    ) -> ReviewTask:
        async with self.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                msg = "review task not found"
                raise LookupError(msg)
            if task.revision != expected_revision:
                raise ReviewConflictError()
            old = ReviewStatus(task.status)
            if old == ReviewStatus.PENDING:
                assert_transition(old, ReviewStatus.EDITING)
                task.status = ReviewStatus.EDITING.value
            elif old not in {ReviewStatus.EDITING, ReviewStatus.PENDING}:
                raise IllegalTransitionError(old, ReviewStatus.EDITING)

            task.final_text = content
            task.revision += 1
            session.add(
                ContentRevision(
                    review_task_id=task.id,
                    revision_number=task.revision,
                    source=source,
                    content=content,
                    created_by=user_id,
                )
            )
            session.add(
                ReviewAction(
                    review_task_id=task.id,
                    user_id=user_id,
                    action=ReviewActionType.EDITED.value,
                    old_status=old.value,
                    new_status=task.status,
                    detail={"revision": task.revision},
                )
            )
            await session.commit()
            await session.refresh(task)
            return task

    async def restore_revision(
        self,
        task_id: int,
        revision_number: int,
        *,
        user_id: int,
        expected_revision: int,
    ) -> ReviewTask:
        async with self.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                raise LookupError("review task not found")
            if task.revision != expected_revision:
                raise ReviewConflictError()
            result = await session.execute(
                select(ContentRevision).where(
                    ContentRevision.review_task_id == task_id,
                    ContentRevision.revision_number == revision_number,
                )
            )
            rev = result.scalar_one_or_none()
            if rev is None:
                raise LookupError("revision not found")
            old = ReviewStatus(task.status)
            if old == ReviewStatus.PENDING:
                task.status = ReviewStatus.EDITING.value
            task.final_text = rev.content
            task.revision += 1
            session.add(
                ContentRevision(
                    review_task_id=task.id,
                    revision_number=task.revision,
                    source="restored",
                    content=rev.content,
                    created_by=user_id,
                )
            )
            session.add(
                ReviewAction(
                    review_task_id=task.id,
                    user_id=user_id,
                    action=ReviewActionType.RESTORED_ORIGINAL.value
                    if rev.source == "original"
                    else ReviewActionType.EDITED.value,
                    old_status=old.value,
                    new_status=task.status,
                    detail={"restored_from": revision_number},
                )
            )
            await session.commit()
            await session.refresh(task)
            return task

    async def claim_for_publish(
        self,
        task_id: int,
        *,
        expected_revision: int,
        user_id: int | None = None,
    ) -> ReviewTask | None:
        """Atomically move APPROVED/FAILED -> PUBLISHING. Returns None if lost race."""
        async with self.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                return None
            if task.revision != expected_revision:
                return None
            if task.status not in {
                ReviewStatus.APPROVED.value,
                ReviewStatus.FAILED.value,
            }:
                return None
            if task.published_at is not None:
                return None
            old = ReviewStatus(task.status)
            assert_transition(old, ReviewStatus.PUBLISHING)
            task.status = ReviewStatus.PUBLISHING.value
            task.revision += 1
            task.publishing_started_at = datetime.now(UTC)
            session.add(
                ReviewAction(
                    review_task_id=task.id,
                    user_id=user_id,
                    action=ReviewActionType.APPROVED.value,
                    old_status=old.value,
                    new_status=ReviewStatus.PUBLISHING.value,
                )
            )
            await session.commit()
            await session.refresh(task)
            return task
