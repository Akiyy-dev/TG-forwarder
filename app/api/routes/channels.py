"""Source and target channel management APIs."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from app.api.dependencies import SuperAdminUser, ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.pagination import PageParams, build_page
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.schemas.channel import PublishMode
from app.services.channel_service import ChannelServiceError

router = APIRouter(tags=["channels"])


class SourceChannelOut(APIModel):
    id: int
    chat_id: int
    username: str | None = None
    title: str | None = None
    enabled: bool
    publish_mode: str
    target_channel_id: int | None = None
    processing_profile: str
    created_at: Any = None
    updated_at: Any = None


class SourceCreateRequest(APIModel):
    chat_id: int
    username: str | None = None
    title: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    publish_mode: PublishMode = PublishMode.REVIEW
    target_channel_id: int | None = None
    processing_profile: str = Field(default="default", max_length=64)


class SourcePatchRequest(APIModel):
    username: str | None = None
    title: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    publish_mode: PublishMode | None = None
    target_channel_id: int | None = None
    processing_profile: str | None = Field(default=None, max_length=64)


class TargetChannelOut(APIModel):
    id: int
    chat_id: int
    username: str | None = None
    title: str | None = None
    enabled: bool
    default_footer: str | None = None
    permission_status: str
    permission_detail: dict[str, Any] | None = None
    last_permission_check_at: Any = None
    created_at: Any = None
    updated_at: Any = None


class TargetCreateRequest(APIModel):
    chat_id: int
    username: str | None = None
    title: str | None = Field(default=None, max_length=512)
    enabled: bool = True
    default_footer: str | None = None


class TargetPatchRequest(APIModel):
    username: str | None = None
    title: str | None = Field(default=None, max_length=512)
    enabled: bool | None = None
    default_footer: str | None = None


class TestMessageRequest(APIModel):
    text: str = Field(default="TG-forwarder test message", min_length=1, max_length=1024)


def _map_err(exc: ChannelServiceError) -> AppError:
    status = {
        "not_found": 404,
        "conflict": 409,
        "validation_error": 422,
        "unavailable": 503,
        "invalid_state": 400,
        "publish_failed": 502,
    }.get(exc.code, 400)
    return AppError(exc.code, exc.message, status_code=status)


@router.get("/channels", response_model=Envelope[dict[str, Any]])
async def list_channels(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    enabled: bool | None = None,
    publish_mode: PublishMode | None = None,
    q: str | None = None,
) -> Envelope[dict[str, Any]]:
    params = PageParams(page=page, page_size=page_size)
    rows, total = await ctx.channel_service.list_sources_paginated(
        page=page,
        page_size=page_size,
        enabled=enabled,
        publish_mode=publish_mode.value if publish_mode else None,
        q=q,
    )
    items = [SourceChannelOut.model_validate(r).model_dump(mode="json") for r in rows]
    return Envelope(data=build_page(items=items, total=total, params=params))


@router.post("/channels", response_model=Envelope[SourceChannelOut])
async def create_channel(
    body: SourceCreateRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[SourceChannelOut]:
    try:
        channel = await ctx.channel_service.create_source(body.model_dump())
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=SourceChannelOut.model_validate(channel))


@router.get("/channels/{source_id}", response_model=Envelope[SourceChannelOut])
async def get_channel(
    source_id: int,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[SourceChannelOut]:
    try:
        channel = await ctx.channel_service.get_source(source_id)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=SourceChannelOut.model_validate(channel))


@router.patch("/channels/{source_id}", response_model=Envelope[SourceChannelOut])
async def patch_channel(
    source_id: int,
    body: SourcePatchRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[SourceChannelOut]:
    try:
        channel = await ctx.channel_service.update_source(
            source_id, body.model_dump(exclude_unset=True)
        )
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=SourceChannelOut.model_validate(channel))


@router.delete("/channels/{source_id}", response_model=Envelope[dict[str, Any]])
async def delete_channel(
    source_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        await ctx.channel_service.delete_source(source_id)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data={"deleted": True, "id": source_id})


@router.get("/targets", response_model=Envelope[dict[str, Any]])
async def list_targets(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    rows = await ctx.channel_service.list_targets()
    items = [TargetChannelOut.model_validate(r).model_dump(mode="json") for r in rows]
    return Envelope(data={"items": items})


@router.post("/targets", response_model=Envelope[TargetChannelOut])
async def create_target(
    body: TargetCreateRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[TargetChannelOut]:
    try:
        target = await ctx.channel_service.create_target(body.model_dump())
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=TargetChannelOut.model_validate(target))


@router.get("/targets/{target_id}", response_model=Envelope[TargetChannelOut])
async def get_target(
    target_id: int,
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[TargetChannelOut]:
    try:
        target = await ctx.channel_service.get_target(target_id)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=TargetChannelOut.model_validate(target))


@router.patch("/targets/{target_id}", response_model=Envelope[TargetChannelOut])
async def patch_target(
    target_id: int,
    body: TargetPatchRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[TargetChannelOut]:
    try:
        target = await ctx.channel_service.update_target(
            target_id, body.model_dump(exclude_unset=True)
        )
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=TargetChannelOut.model_validate(target))


@router.delete("/targets/{target_id}", response_model=Envelope[dict[str, Any]])
async def delete_target(
    target_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    try:
        await ctx.channel_service.delete_target(target_id)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data={"deleted": True, "id": target_id})


@router.post("/targets/{target_id}/check-permissions", response_model=Envelope[dict[str, Any]])
async def check_target_permissions(
    target_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    bot = ctx.bot or getattr(ctx.publisher, "bot", None)
    try:
        result = await ctx.channel_service.check_target_permissions(target_id, bot)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=result)


@router.post("/targets/{target_id}/test-message", response_model=Envelope[dict[str, Any]])
async def send_target_test_message(
    target_id: int,
    body: TestMessageRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    bot = ctx.bot or getattr(ctx.publisher, "bot", None)
    try:
        result = await ctx.channel_service.send_target_test_message(target_id, bot, body.text)
    except ChannelServiceError as exc:
        raise _map_err(exc) from exc
    return Envelope(data=result)
