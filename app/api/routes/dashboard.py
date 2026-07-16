"""Read-only dashboard summary for the web admin."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api.dependencies import ViewerUser, get_ctx
from app.api.schemas import Envelope
from app.context import AppContext
from app.database.models import (
    KeywordRule,
    ProcessedMessage,
    ReviewTask,
    SourceChannel,
    TargetChannel,
)
from app.review.state_machine import ReviewStatus
from app.schemas.message import MessageStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=Envelope[dict[str, Any]])
async def dashboard_summary(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    # Sender and Web have separate in-memory caches in Compose mode.
    await ctx.channel_service.load_from_db()
    bus = ctx.command_bus
    distributed = bus is not None
    telegram_receiver_running = ctx.listener is not None
    safew_receiver_running = False
    sender_running = ctx.bot is not None or getattr(ctx.publisher, "bot", None) is not None
    if bus is not None:
        telegram_receiver_running, safew_receiver_running, sender_running = await asyncio.gather(
            bus.role_alive("telegram-receiver"),
            bus.role_alive("safew-receiver"),
            bus.role_alive("sender"),
        )
    message_stats = await ctx.message_service.stats()
    recent_errors = await ctx.message_service.recent_errors()
    paused = await ctx.message_service.refresh_paused()
    since = datetime.now(UTC) - timedelta(days=1)

    async with ctx.session_factory() as session:
        pending_review = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ReviewTask)
                    .where(
                        ReviewTask.status.in_(
                            [
                                ReviewStatus.PENDING.value,
                                ReviewStatus.EDITING.value,
                                ReviewStatus.APPROVED.value,
                                ReviewStatus.FAILED.value,
                            ]
                        )
                    )
                )
            ).scalar_one()
        )
        source_count = int(
            (await session.execute(select(func.count()).select_from(SourceChannel))).scalar_one()
        )
        target_count = int(
            (await session.execute(select(func.count()).select_from(TargetChannel))).scalar_one()
        )
        rule_count = int(
            (await session.execute(select(func.count()).select_from(KeywordRule))).scalar_one()
        )
        today_received = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ProcessedMessage)
                    .where(ProcessedMessage.received_at >= since)
                )
            ).scalar_one()
        )
        today_published = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ProcessedMessage)
                    .where(
                        ProcessedMessage.status == MessageStatus.PUBLISHED.value,
                        ProcessedMessage.published_at.is_not(None),
                        ProcessedMessage.published_at >= since,
                    )
                )
            ).scalar_one()
        )
        today_failed = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ProcessedMessage)
                    .where(
                        ProcessedMessage.status == MessageStatus.FAILED.value,
                        ProcessedMessage.updated_at >= since,
                    )
                )
            ).scalar_one()
        )
        today_rejected = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ReviewTask)
                    .where(
                        ReviewTask.status == ReviewStatus.REJECTED.value,
                        ReviewTask.rejected_at.is_not(None),
                        ReviewTask.rejected_at >= since,
                    )
                )
            ).scalar_one()
        )
        recent_reviews = list(
            (
                await session.execute(
                    select(ReviewTask).order_by(ReviewTask.updated_at.desc()).limit(10)
                )
            ).scalars()
        )

    return Envelope(
        data={
            "service": {
                "web_enabled": ctx.settings.web_enabled,
                "distributed": distributed,
                "started_at": ctx.started_at.isoformat(),
                "publishing_paused": paused,
                "listener_running": telegram_receiver_running or safew_receiver_running,
                "telegram_receiver_running": telegram_receiver_running,
                "safew_receiver_running": safew_receiver_running,
                "sender_running": sender_running,
                "bot_available": sender_running,
                "queue_size": ctx.message_service.queue_size,
            },
            "counts": {
                "pending_review": pending_review,
                "source_channels": source_count,
                "target_channels": target_count,
                "rules": rule_count,
                "today_received": today_received,
                "today_published": today_published,
                "today_failed": today_failed,
                "today_rejected": today_rejected,
                "by_status": message_stats,
            },
            "recent_errors": recent_errors[:10],
            "recent_reviews": [
                {
                    "id": t.id,
                    "status": t.status,
                    "source_chat_id": t.source_chat_id,
                    "source_message_id": t.source_message_id,
                    "source_title": ctx.channel_service.display_name(int(t.source_chat_id)),
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                }
                for t in recent_reviews
            ],
        }
    )
