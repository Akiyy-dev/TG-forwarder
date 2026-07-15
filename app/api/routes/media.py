"""Authenticated media streaming with path confinement."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

from app.api.dependencies import ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.schemas import Envelope
from app.context import AppContext
from app.database.models import ReviewTask
from app.logging import get_logger
from app.review.preview import build_publish_preview
from app.review.publish import message_from_task
from app.review.service import ReviewService
from app.utils.files import safe_join

router = APIRouter(tags=["media"])
logger = get_logger(__name__)


def _resolve_media_path(ctx: AppContext, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    root = Path(ctx.settings.download_dir).resolve()
    candidate = Path(raw_path)
    # Only allow files under download_dir
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise AppError("invalid_media", "Invalid media path", status_code=400) from exc
    if not str(resolved).startswith(str(root)):
        # Try treating as basename within download dir
        try:
            resolved = safe_join(root, candidate.name)
        except ValueError as exc:
            raise AppError("forbidden_path", "Media path rejected", status_code=403) from exc
    if not str(resolved).startswith(str(root)):
        raise AppError("forbidden_path", "Media path rejected", status_code=403)
    if not resolved.is_file():
        return None
    return resolved


async def _ensure_review_media(ctx: AppContext, task: ReviewTask) -> ReviewTask:
    """Re-download missing snapshot media for preview/stream."""
    message = message_from_task(task)
    if not ctx.media_service.media_missing(message):
        return task
    try:
        message = await ctx.media_service.ensure_materialized(message)
    except Exception:
        logger.exception("review_media_rematerialize_failed", review_task_id=task.id)
        return task
    if ctx.media_service.media_missing(message):
        return task
    svc = ReviewService(ctx.session_factory)
    return await svc.update_media_snapshot(task.id, message)


@router.get("/reviews/{task_id}/preview", response_model=Envelope[dict[str, Any]])
async def review_preview(
    task_id: int,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        if task is None:
            raise AppError("not_found", "Review task not found", status_code=404)
        _ = task.media_snapshot  # eager load before detach
        session.expunge(task)
    task = await _ensure_review_media(ctx, task)

    preview = build_publish_preview(task)
    items = []
    for idx, item in enumerate(preview.get("media_items") or []):
        local = item.get("local_path")
        path = _resolve_media_path(ctx, local)
        items.append(
            {
                "index": idx,
                "media_type": item.get("media_type"),
                "original_filename": item.get("original_filename"),
                "mime_type": item.get("mime_type"),
                "file_size": item.get("file_size"),
                "available": path is not None,
                "url": f"/api/v1/media/reviews/{task_id}/files/{idx}" if path is not None else None,
            }
        )
    preview["media_items"] = items
    return Envelope(data=preview)


@router.get("/media/reviews/{task_id}/files/{index}")
async def stream_review_media(
    task_id: int,
    index: int,
    request: Request,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Response:
    if index < 0:
        raise AppError("validation_error", "Invalid media index", status_code=422)
    async with ctx.session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        if task is None:
            raise AppError("not_found", "Review task not found", status_code=404)
        _ = task.media_snapshot
        session.expunge(task)
    task = await _ensure_review_media(ctx, task)
    snap = task.media_snapshot if isinstance(task.media_snapshot, dict) else {}
    items = list(snap.get("media_items") or [])
    if index >= len(items):
        raise AppError("not_found", "Media item not found", status_code=404)
    item = items[index]
    path = _resolve_media_path(ctx, item.get("local_path"))
    if path is None:
        return JSONResponse(
            status_code=410,
            content={
                "ok": False,
                "error": {
                    "code": "media_cleaned",
                    "message": "Media file has been cleaned up",
                    "details": {},
                    "request_id": getattr(request.state, "request_id", None),
                },
            },
        )
    mime = item.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    filename = item.get("original_filename") or path.name
    return FileResponse(
        path,
        media_type=mime,
        filename=filename,
        content_disposition_type="inline",
    )
