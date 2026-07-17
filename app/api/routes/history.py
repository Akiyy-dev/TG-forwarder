"""Read-only processed-message history for the Web interface."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.dependencies import ViewerUser, get_ctx
from app.api.pagination import PageParams, build_page
from app.api.schemas import Envelope
from app.context import AppContext
from app.database.models import ApiDelivery, ProcessedMessage, SourceChannel
from app.source_backends import source_backend_for_chat_id

router = APIRouter(tags=["history"])


def _item(
    row: ProcessedMessage, source: SourceChannel | None, api_delivery_count: int
) -> dict[str, Any]:
    payload = row.processing_result if isinstance(row.processing_result, dict) else {}
    return {
        "id": row.id,
        "source_chat_id": row.source_chat_id,
        "source_message_id": row.source_message_id,
        "source_backend": source_backend_for_chat_id(int(row.source_chat_id)),
        "source_title": source.title if source else None,
        "status": row.status,
        "text": payload.get("text"),
        "media_type": payload.get("media_type", "text"),
        "publish_mode": payload.get("publish_mode"),
        "target_chat_id": row.target_chat_id,
        "target_chat_ids": payload.get("target_chat_ids") or [],
        "target_message_ids": row.target_message_ids or [],
        "api_delivery_count": api_delivery_count,
        "skip_reason": row.skip_reason,
        "error_message": row.error_message,
        "retry_count": row.retry_count,
        "received_at": row.received_at,
        "processed_at": row.processed_at,
        "published_at": row.published_at,
        "updated_at": row.updated_at,
    }


@router.get("/history", response_model=Envelope[dict[str, Any]])
async def list_history(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: int | None = Query(None, ge=1),
    status: str | None = None,
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    delivery_count = (
        select(func.count(ApiDelivery.id))
        .where(ApiDelivery.processed_message_id == ProcessedMessage.id)
        .correlate(ProcessedMessage)
        .scalar_subquery()
    )
    count_stmt = select(func.count()).select_from(ProcessedMessage)
    list_stmt = (
        select(ProcessedMessage, SourceChannel, delivery_count)
        .outerjoin(SourceChannel, SourceChannel.chat_id == ProcessedMessage.source_chat_id)
        .order_by(ProcessedMessage.id.desc())
    )
    if source_id is not None:
        count_stmt = count_stmt.join(
            SourceChannel, SourceChannel.chat_id == ProcessedMessage.source_chat_id
        ).where(SourceChannel.id == source_id)
        list_stmt = list_stmt.where(SourceChannel.id == source_id)
    if status:
        count_stmt = count_stmt.where(ProcessedMessage.status == status)
        list_stmt = list_stmt.where(ProcessedMessage.status == status)
    async with ctx.session_factory() as session:
        total = int((await session.execute(count_stmt)).scalar_one())
        rows = (
            await session.execute(list_stmt.offset(params.offset).limit(params.page_size))
        ).all()
    items = [_item(message, source, int(api_count or 0)) for message, source, api_count in rows]
    return Envelope(data=build_page(items=items, total=total, params=params))
