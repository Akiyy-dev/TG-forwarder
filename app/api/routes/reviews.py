"""Review task API routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import Field
from sqlalchemy import func, select

from app.api.dependencies import ReviewerUser, ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.pagination import PageParams, build_page
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.database.models import ContentRevision, ReviewAction, ReviewTask
from app.review.publish import ReviewPublishService
from app.review.service import ReviewConflictError, ReviewService
from app.review.state_machine import IllegalTransitionError, ReviewActionType, ReviewStatus
from app.source_backends import source_backend_for_chat_id

router = APIRouter(prefix="/reviews", tags=["reviews"])

BATCH_LIMIT = 50


class ReviewOut(APIModel):
    id: int
    status: str
    source_chat_id: int
    source_message_id: int
    source_backend: str = "telegram"
    source_title: str | None = None
    target_chat_id: int | None
    target_chat_ids: list[int] | None = None
    original_text: str
    processed_text: str
    final_text: str
    media_type: str
    media_count: int
    matched_rules: list[Any] | None = None
    detected_keywords: list[Any] | None = None
    decision_reason: str | None = None
    revision: int
    error_message: str | None = None
    created_at: Any = None
    updated_at: Any = None
    published_at: Any = None


def _enrich_review(ctx: AppContext, row: Any) -> ReviewOut:
    return ReviewOut.model_validate(row).model_copy(
        update={
            "source_title": ctx.channel_service.display_name(int(row.source_chat_id)),
            "target_chat_ids": getattr(row, "target_chat_ids", None),
            "source_backend": source_backend_for_chat_id(int(row.source_chat_id)),
        }
    )


class EditReviewRequest(APIModel):
    content: str = Field(max_length=4096)
    expected_revision: int = Field(ge=1)


class RevisionRequest(APIModel):
    expected_revision: int = Field(ge=1)
    revision_number: int | None = None
    reason: str | None = None


class BatchRequest(APIModel):
    ids: list[int] = Field(min_length=1, max_length=BATCH_LIMIT)
    expected_revisions: dict[str, int] | None = None
    reason: str | None = None


class ReapplyRulesRequest(APIModel):
    expected_revision: int = Field(ge=1)
    source: str = Field(default="original", pattern="^(original|current)$")
    confirm_reject: bool = False


def _review_svc(ctx: AppContext) -> ReviewService:
    return ReviewService(ctx.session_factory)


def _publish_svc(ctx: AppContext) -> ReviewPublishService:
    return ReviewPublishService(
        ctx.session_factory,
        _review_svc(ctx),
        ctx.publisher,
        ctx.media_service,
    )


@router.get("", response_model=Envelope[dict[str, Any]])
async def list_reviews(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    status: str | None = None,
    source_chat_id: int | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    filters = []
    if status:
        filters.append(ReviewTask.status == status)
    if source_chat_id is not None:
        filters.append(ReviewTask.source_chat_id == source_chat_id)
    if q:
        like = f"%{q}%"
        filters.append(ReviewTask.final_text.like(like))

    async with ctx.session_factory() as session:
        count_stmt = select(func.count()).select_from(ReviewTask)
        list_stmt = select(ReviewTask).order_by(ReviewTask.id.desc())
        if filters:
            count_stmt = count_stmt.where(*filters)
            list_stmt = list_stmt.where(*filters)
        total = int((await session.execute(count_stmt)).scalar_one())
        rows = list(
            (
                await session.execute(list_stmt.offset(params.offset).limit(params.page_size))
            ).scalars()
        )
    items = [_enrich_review(ctx, r).model_dump(mode="json") for r in rows]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.get("/{task_id}", response_model=Envelope[dict[str, Any]])
async def get_review(
    task_id: int,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        if task is None:
            raise AppError("not_found", "Review task not found", status_code=404)
        revs = list(
            (
                await session.execute(
                    select(ContentRevision)
                    .where(ContentRevision.review_task_id == task_id)
                    .order_by(ContentRevision.revision_number.asc())
                )
            ).scalars()
        )
        actions = list(
            (
                await session.execute(
                    select(ReviewAction)
                    .where(ReviewAction.review_task_id == task_id)
                    .order_by(ReviewAction.id.desc())
                    .limit(50)
                )
            ).scalars()
        )
    return Envelope(
        data={
            "task": _enrich_review(ctx, task).model_dump(mode="json"),
            "revisions": [
                {
                    "revision_number": r.revision_number,
                    "source": r.source,
                    "content": r.content,
                    "created_by": r.created_by,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in revs
            ],
            "actions": [
                {
                    "action": a.action,
                    "old_status": a.old_status,
                    "new_status": a.new_status,
                    "user_id": a.user_id,
                    "detail": a.detail,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ],
        }
    )


@router.post("/{task_id}/reapply-rules", response_model=Envelope[dict[str, Any]])
async def reapply_rules(
    task_id: int,
    body: ReapplyRulesRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    svc = _review_svc(ctx)
    try:
        task, preview = await svc.reapply_rules(
            task_id,
            user_id=user.id,
            expected_revision=body.expected_revision,
            source=body.source,
            confirm_reject=body.confirm_reject,
        )
    except ReviewConflictError as exc:
        raise AppError("conflict", exc.message, status_code=409) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc), status_code=404) from exc
    except (IllegalTransitionError, ValueError) as exc:
        raise AppError("invalid_state", str(exc), status_code=400) from exc
    data: dict[str, Any] = {"preview": preview}
    if task is not None:
        data["task"] = _enrich_review(ctx, task).model_dump(mode="json")
    return Envelope(data=data)


@router.post("/{task_id}/edit", response_model=Envelope[ReviewOut])
async def edit_review(
    task_id: int,
    body: EditReviewRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ReviewOut]:
    svc = _review_svc(ctx)
    try:
        task = await svc.edit_text(
            task_id,
            body.content,
            user_id=user.id,
            expected_revision=body.expected_revision,
        )
    except ReviewConflictError as exc:
        raise AppError("conflict", exc.message, status_code=409) from exc
    except (LookupError, IllegalTransitionError) as exc:
        raise AppError("invalid_state", str(exc), status_code=400) from exc
    return Envelope(data=_enrich_review(ctx, task))


@router.post("/{task_id}/approve", response_model=Envelope[ReviewOut])
async def approve_review(
    task_id: int,
    body: RevisionRequest,
    user: ReviewerUser,
    request: Request,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ReviewOut]:
    svc = _review_svc(ctx)
    try:
        task = await svc.transition(
            task_id,
            ReviewStatus.APPROVED,
            user_id=user.id,
            action=ReviewActionType.APPROVED,
            expected_revision=body.expected_revision,
            detail={"reason": body.reason},
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ReviewConflictError as exc:
        raise AppError("conflict", exc.message, status_code=409) from exc
    except (LookupError, IllegalTransitionError) as exc:
        raise AppError("invalid_state", str(exc), status_code=400) from exc
    return Envelope(data=_enrich_review(ctx, task))


@router.post("/{task_id}/reject", response_model=Envelope[ReviewOut])
async def reject_review(
    task_id: int,
    body: RevisionRequest,
    user: ReviewerUser,
    request: Request,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ReviewOut]:
    svc = _review_svc(ctx)
    try:
        task = await svc.transition(
            task_id,
            ReviewStatus.REJECTED,
            user_id=user.id,
            action=ReviewActionType.REJECTED,
            expected_revision=body.expected_revision,
            detail={"reason": body.reason},
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except ReviewConflictError as exc:
        raise AppError("conflict", exc.message, status_code=409) from exc
    except (LookupError, IllegalTransitionError) as exc:
        raise AppError("invalid_state", str(exc), status_code=400) from exc
    return Envelope(data=_enrich_review(ctx, task))


@router.post("/{task_id}/publish", response_model=Envelope[dict[str, Any]])
async def publish_review(
    task_id: int,
    body: RevisionRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    # Ensure approved first if still pending/editing
    async with ctx.session_factory() as session:
        task = await session.get(ReviewTask, task_id)
        if task is None:
            raise AppError("not_found", "Review task not found", status_code=404)
        status = task.status
        revision = task.revision

    if status in {ReviewStatus.PENDING.value, ReviewStatus.EDITING.value}:
        if body.expected_revision != revision:
            raise AppError("conflict", "Revision conflict", status_code=409)
        svc = _review_svc(ctx)
        try:
            approved = await svc.transition(
                task_id,
                ReviewStatus.APPROVED,
                user_id=user.id,
                action=ReviewActionType.APPROVED,
                expected_revision=revision,
            )
            revision = approved.revision
        except (ReviewConflictError, IllegalTransitionError) as exc:
            raise AppError("invalid_state", str(exc), status_code=400) from exc
    elif status == ReviewStatus.APPROVED.value:
        if body.expected_revision != revision:
            raise AppError("conflict", "Revision conflict", status_code=409)
    elif status == ReviewStatus.PUBLISHED.value:
        return Envelope(data={"status": "published", "already_published": True})
    elif status == ReviewStatus.FAILED.value:
        if body.expected_revision != revision:
            raise AppError("conflict", "Revision conflict", status_code=409)
    else:
        raise AppError("invalid_state", f"Cannot publish from status {status}", status_code=400)

    if ctx.command_bus is not None:
        command_id = await ctx.command_bus.publish_command(
            "publish_review",
            {
                "task_id": task_id,
                "expected_revision": revision,
                "user_id": user.id,
            },
        )
        return Envelope(
            data={
                "status": "queued",
                "command_id": command_id,
                "review_task_id": task_id,
            }
        )

    result = await _publish_svc(ctx).publish_task(
        task_id, expected_revision=revision, user_id=user.id
    )
    if result.get("status") == "conflict":
        raise AppError("conflict", "Publish race lost or already handled", status_code=409)
    return Envelope(data=result)


@router.post("/{task_id}/restore", response_model=Envelope[ReviewOut])
async def restore_review(
    task_id: int,
    body: RevisionRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ReviewOut]:
    if body.revision_number is None:
        raise AppError("validation_error", "revision_number required", status_code=422)
    svc = _review_svc(ctx)
    try:
        task = await svc.restore_revision(
            task_id,
            body.revision_number,
            user_id=user.id,
            expected_revision=body.expected_revision,
        )
    except ReviewConflictError as exc:
        raise AppError("conflict", exc.message, status_code=409) from exc
    except LookupError as exc:
        raise AppError("not_found", str(exc), status_code=404) from exc
    return Envelope(data=_enrich_review(ctx, task))


@router.post("/batch/reject", response_model=Envelope[dict[str, Any]])
async def batch_reject(
    body: BatchRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    svc = _review_svc(ctx)
    results: list[dict[str, Any]] = []
    for task_id in body.ids:
        rev = (body.expected_revisions or {}).get(str(task_id))
        async with ctx.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                results.append({"id": task_id, "ok": False, "error": "not_found"})
                continue
            expected = rev if rev is not None else task.revision
        try:
            await svc.transition(
                task_id,
                ReviewStatus.REJECTED,
                user_id=user.id,
                action=ReviewActionType.REJECTED,
                expected_revision=expected,
                detail={"reason": body.reason, "batch": True},
            )
            results.append({"id": task_id, "ok": True})
        except Exception as exc:
            results.append({"id": task_id, "ok": False, "error": str(exc)})
    return Envelope(data={"results": results})


@router.post("/batch/publish", response_model=Envelope[dict[str, Any]])
async def batch_publish(
    body: BatchRequest,
    user: ReviewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    pub = _publish_svc(ctx)
    svc = _review_svc(ctx)
    results: list[dict[str, Any]] = []
    for task_id in body.ids:
        async with ctx.session_factory() as session:
            task = await session.get(ReviewTask, task_id)
            if task is None:
                results.append({"id": task_id, "ok": False, "error": "not_found"})
                continue
            revision = (body.expected_revisions or {}).get(str(task_id), task.revision)
            status = task.status
        try:
            if status in {ReviewStatus.PENDING.value, ReviewStatus.EDITING.value}:
                approved = await svc.transition(
                    task_id,
                    ReviewStatus.APPROVED,
                    user_id=user.id,
                    action=ReviewActionType.APPROVED,
                    expected_revision=revision,
                    detail={"batch": True},
                )
                revision = approved.revision
            if ctx.command_bus is not None:
                command_id = await ctx.command_bus.publish_command(
                    "publish_review",
                    {
                        "task_id": task_id,
                        "expected_revision": revision,
                        "user_id": user.id,
                    },
                )
                outcome = {"status": "queued", "command_id": command_id}
            else:
                outcome = await pub.publish_task(
                    task_id, expected_revision=revision, user_id=user.id
                )
            results.append({"id": task_id, "ok": True, "result": outcome})
        except Exception as exc:
            results.append({"id": task_id, "ok": False, "error": str(exc)})
    return Envelope(data={"results": results})
