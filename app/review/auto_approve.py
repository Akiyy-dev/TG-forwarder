"""Background auto-approve + publish for timed-out review tasks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ReviewTask
from app.logging import get_logger
from app.review.publish import ReviewPublishService
from app.review.service import ReviewConflictError, ReviewService
from app.review.state_machine import IllegalTransitionError, ReviewActionType, ReviewStatus
from app.services.runtime_settings import get_runtime_settings

logger = get_logger(__name__)

# How often to scan for timed-out reviews.
SCAN_INTERVAL_SECONDS = 30.0
BATCH_LIMIT = 20


class ReviewAutoApproveService:
    """Periodically approve+publish reviews older than configured minutes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        publish_service: ReviewPublishService,
        *,
        is_paused: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.publish_service = publish_service
        self.review_service = ReviewService(session_factory)
        self._is_paused = is_paused
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="review_auto_approve")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        logger.info("review_auto_approve_started")
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                logger.exception("review_auto_approve_tick_failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=SCAN_INTERVAL_SECONDS)
                break
            except TimeoutError:
                continue
        logger.info("review_auto_approve_stopped")

    def _config(self) -> tuple[bool, int]:
        runtime = get_runtime_settings()
        enabled = bool(runtime.get("review_auto_approve_enabled", True))
        minutes = int(runtime.get("review_auto_approve_minutes", 10) or 10)
        if minutes < 1:
            minutes = 1
        return enabled, minutes

    async def tick(self) -> int:
        enabled, minutes = self._config()
        if not enabled:
            return 0
        if self._is_paused is not None:
            paused = self._is_paused()
            if asyncio.iscoroutine(paused):
                paused = await paused
            if paused:
                return 0

        cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(ReviewTask)
                        .where(
                            ReviewTask.status.in_(
                                [
                                    ReviewStatus.PENDING.value,
                                    ReviewStatus.EDITING.value,
                                ]
                            ),
                            ReviewTask.created_at <= cutoff,
                        )
                        .order_by(ReviewTask.id.asc())
                        .limit(BATCH_LIMIT)
                    )
                ).scalars()
            )
            items = [(t.id, t.revision, t.status) for t in rows]

        processed = 0
        for task_id, revision, status in items:
            try:
                ok = await self._approve_and_publish(task_id, revision, status)
                if ok:
                    processed += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "review_auto_approve_item_failed",
                    review_task_id=task_id,
                )
        if processed:
            logger.info(
                "review_auto_approve_batch",
                count=processed,
                minutes=minutes,
            )
        return processed

    async def _approve_and_publish(
        self,
        task_id: int,
        revision: int,
        status: str,
    ) -> bool:
        detail = {"reason": "auto_approve_timeout"}
        current_revision = revision
        if status in {ReviewStatus.PENDING.value, ReviewStatus.EDITING.value}:
            try:
                task = await self.review_service.transition(
                    task_id,
                    ReviewStatus.APPROVED,
                    user_id=None,
                    action=ReviewActionType.APPROVED,
                    expected_revision=current_revision,
                    detail=detail,
                )
                current_revision = task.revision
            except (ReviewConflictError, IllegalTransitionError, LookupError) as exc:
                logger.info(
                    "review_auto_approve_skipped",
                    review_task_id=task_id,
                    reason=type(exc).__name__,
                )
                return False

        result = await self.publish_service.publish_task(
            task_id,
            expected_revision=current_revision,
            user_id=None,
        )
        logger.info(
            "review_auto_approve_published",
            review_task_id=task_id,
            status=result.get("status"),
            already_published=result.get("already_published"),
        )
        return result.get("status") == ReviewStatus.PUBLISHED.value
