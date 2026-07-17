"""Processed message repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ProcessedMessage, ProcessingLog
from app.schemas.message import MessageStatus


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_source(
        self, source_chat_id: int, source_message_id: int
    ) -> ProcessedMessage | None:
        result = await self._session.execute(
            select(ProcessedMessage).where(
                ProcessedMessage.source_chat_id == source_chat_id,
                ProcessedMessage.source_message_id == source_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def try_create(
        self,
        *,
        source_chat_id: int,
        source_message_id: int,
        grouped_id: int | None = None,
        status: str = MessageStatus.RECEIVED.value,
        target_chat_id: int | None = None,
        content_hash: str | None = None,
        processing_result: dict[str, Any] | None = None,
    ) -> ProcessedMessage | None:
        """Insert a record; return None if unique constraint violated (already seen)."""
        record = ProcessedMessage(
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            grouped_id=grouped_id,
            status=status,
            target_chat_id=target_chat_id,
            content_hash=content_hash,
            processing_result=processing_result,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            return None
        return record

    async def update_payload(
        self,
        record: ProcessedMessage,
        payload: dict[str, Any],
    ) -> ProcessedMessage:
        """Persist the normalized message snapshot without changing its status."""
        record.processing_result = payload
        await self._session.flush()
        return record

    async def update_status(
        self,
        record: ProcessedMessage,
        status: str,
        *,
        skip_reason: str | None = None,
        error_message: str | None = None,
        content_hash: str | None = None,
        target_message_ids: list[int] | None = None,
        processing_result: dict[str, Any] | None = None,
        increment_retry: bool = False,
    ) -> ProcessedMessage:
        record.status = status
        if skip_reason is not None:
            record.skip_reason = skip_reason
        if error_message is not None:
            record.error_message = error_message
        if content_hash is not None:
            record.content_hash = content_hash
        if target_message_ids is not None:
            record.target_message_ids = target_message_ids
        if processing_result is not None:
            record.processing_result = processing_result
        if increment_retry:
            record.retry_count += 1
        now = datetime.now(UTC)
        if status == MessageStatus.PROCESSING.value:
            record.processed_at = now
        if status == MessageStatus.PUBLISHED.value:
            record.published_at = now
        await self._session.flush()
        return record

    async def add_log(
        self,
        message_record_id: int,
        processor_name: str,
        status: str,
        detail: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> ProcessingLog:
        log = ProcessingLog(
            message_record_id=message_record_id,
            processor_name=processor_name,
            status=status,
            detail=detail,
            duration_ms=duration_ms,
        )
        self._session.add(log)
        await self._session.flush()
        return log

    async def find_by_content_hash(
        self,
        content_hash: str,
        *,
        within_hours: int,
        exclude_id: int | None = None,
    ) -> ProcessedMessage | None:
        since = datetime.now(UTC) - timedelta(hours=within_hours)
        # Only treat already-published content as duplicates so recovers/retries
        # of the same message are not self-filtered by content hash.
        stmt = select(ProcessedMessage).where(
            ProcessedMessage.content_hash == content_hash,
            ProcessedMessage.created_at >= since,
            ProcessedMessage.status == MessageStatus.PUBLISHED.value,
        )
        if exclude_id is not None:
            stmt = stmt.where(ProcessedMessage.id != exclude_id)
        result = await self._session.execute(stmt.limit(1))
        return result.scalar_one_or_none()

    async def list_by_status(self, statuses: list[str], limit: int = 100) -> list[ProcessedMessage]:
        result = await self._session.execute(
            select(ProcessedMessage)
            .where(ProcessedMessage.status.in_(statuses))
            .order_by(ProcessedMessage.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        result = await self._session.execute(
            select(ProcessedMessage.status, func.count()).group_by(ProcessedMessage.status)
        )
        return {row[0]: int(row[1]) for row in result.all()}

    async def recent_errors(self, limit: int = 5) -> list[ProcessedMessage]:
        result = await self._session.execute(
            select(ProcessedMessage)
            .where(ProcessedMessage.status == MessageStatus.FAILED.value)
            .order_by(ProcessedMessage.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
