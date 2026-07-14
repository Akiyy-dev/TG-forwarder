"""System control, SSE events, and audit log APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, select

from app.api.dependencies import SuperAdminUser, ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.pagination import PageParams, build_page
from app.api.schemas import Envelope
from app.context import AppContext
from app.database.models import ProcessingLog, ReviewAction, ReviewTask, RuleExecutionLog
from app.review.state_machine import ReviewStatus

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=Envelope[dict[str, Any]])
async def system_status(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    paused = await ctx.message_service.refresh_paused()
    stats = await ctx.message_service.stats()
    return Envelope(
        data={
            "started_at": ctx.started_at.isoformat(),
            "publishing_paused": paused,
            "queue_size": ctx.message_service.queue_size,
            "last_error": ctx.message_service.last_error,
            "listener_running": ctx.listener is not None,
            "bot_available": ctx.bot is not None or getattr(ctx.publisher, "bot", None) is not None,
            "message_stats": stats,
        }
    )


@router.post("/system/pause", response_model=Envelope[dict[str, Any]])
async def system_pause(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    await ctx.message_service.set_paused(True)
    return Envelope(data={"publishing_paused": True})


@router.post("/system/resume", response_model=Envelope[dict[str, Any]])
async def system_resume(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    requeued = await ctx.message_service.resume_publishing()
    return Envelope(data={"publishing_paused": False, "requeued": requeued})


@router.post("/system/recover", response_model=Envelope[dict[str, Any]])
async def system_recover(
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    if await ctx.message_service.refresh_paused():
        raise AppError(
            "invalid_state",
            "Publishing is paused; resume before recovering",
            status_code=400,
        )
    requeued = await ctx.message_service.recover_pending()
    return Envelope(data={"requeued": requeued})


@router.get("/events/stream")
async def events_stream(
    request: Request,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> StreamingResponse:
    async def generate() -> AsyncIterator[str]:
        last_pending: int | None = None
        last_queue: int | None = None
        while True:
            if await request.is_disconnected():
                break
            async with ctx.session_factory() as session:
                pending = int(
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
            queue_size = ctx.message_service.queue_size
            paused = ctx.message_service.paused
            if pending != last_pending or queue_size != last_queue:
                payload = {
                    "ts": datetime.now(UTC).isoformat(),
                    "pending_review": pending,
                    "queue_size": queue_size,
                    "publishing_paused": paused,
                }
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
                last_pending = pending
                last_queue = queue_size
            else:
                yield ": keepalive\n\n"
            await asyncio.sleep(5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/logs/review-actions", response_model=Envelope[dict[str, Any]])
async def list_review_actions(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    async with ctx.session_factory() as session:
        total = int(
            (await session.execute(select(func.count()).select_from(ReviewAction))).scalar_one()
        )
        rows = list(
            (
                await session.execute(
                    select(ReviewAction)
                    .order_by(desc(ReviewAction.id))
                    .offset(params.offset)
                    .limit(params.page_size)
                )
            ).scalars()
        )
    items = [
        {
            "id": r.id,
            "review_task_id": r.review_task_id,
            "user_id": r.user_id,
            "action": r.action,
            "old_status": r.old_status,
            "new_status": r.new_status,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.get("/logs/processing", response_model=Envelope[dict[str, Any]])
async def list_processing_logs(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    async with ctx.session_factory() as session:
        total = int(
            (await session.execute(select(func.count()).select_from(ProcessingLog))).scalar_one()
        )
        rows = list(
            (
                await session.execute(
                    select(ProcessingLog)
                    .order_by(desc(ProcessingLog.id))
                    .offset(params.offset)
                    .limit(params.page_size)
                )
            ).scalars()
        )
    items = [
        {
            "id": r.id,
            "message_record_id": r.message_record_id,
            "processor_name": r.processor_name,
            "status": r.status,
            "detail": r.detail,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.get("/logs/rule-executions", response_model=Envelope[dict[str, Any]])
async def list_rule_execution_logs(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    async with ctx.session_factory() as session:
        total = int(
            (await session.execute(select(func.count()).select_from(RuleExecutionLog))).scalar_one()
        )
        rows = list(
            (
                await session.execute(
                    select(RuleExecutionLog)
                    .order_by(desc(RuleExecutionLog.id))
                    .offset(params.offset)
                    .limit(params.page_size)
                )
            ).scalars()
        )
    items = [
        {
            "id": r.id,
            "rule_id": r.rule_id,
            "rule_name": r.rule_name,
            "action": r.action,
            "matched_text": r.matched_text,
            "review_task_id": r.review_task_id,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return Envelope(data=build_page(items=items, total=total, params=params))
