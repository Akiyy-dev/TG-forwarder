"""Administration and public pull API for processed-message destinations."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import SuperAdminUser, ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.database.models import (
    ApiDelivery,
    ApiEndpoint,
    SourceApiEndpointLink,
    SourceChannel,
)
from app.services.api_delivery_service import (
    ApiDeliveryService,
    generate_api_token,
    hash_api_token,
    token_prefix,
)

router = APIRouter(tags=["api-destinations"])
public_router = APIRouter(tags=["public-api"])


class ApiEndpointOut(APIModel):
    id: int
    name: str
    token_prefix: str
    enabled: bool
    expires_at: datetime | None = None
    last_access_at: datetime | None = None
    source_ids: list[int] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ApiEndpointSecretOut(ApiEndpointOut):
    token: str


class ApiEndpointCreate(APIModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    expires_at: datetime | None = None
    source_ids: list[int] = Field(default_factory=list)
    token: str | None = Field(default=None, min_length=24, max_length=256)


class ApiEndpointPatch(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    expires_at: datetime | None = None


class RotateTokenRequest(APIModel):
    token: str | None = Field(default=None, min_length=24, max_length=256)


class LinkSourcesRequest(APIModel):
    source_ids: list[int] = Field(default_factory=list)


async def _source_ids(ctx: AppContext, endpoint_id: int) -> list[int]:
    async with ctx.session_factory() as session:
        return [
            int(value)
            for value in (
                await session.execute(
                    select(SourceApiEndpointLink.source_id)
                    .where(SourceApiEndpointLink.api_endpoint_id == endpoint_id)
                    .order_by(SourceApiEndpointLink.id)
                )
            )
            .scalars()
            .all()
        ]


async def _out(ctx: AppContext, endpoint: ApiEndpoint) -> ApiEndpointOut:
    data = ApiEndpointOut.model_validate(endpoint).model_dump()
    data["source_ids"] = await _source_ids(ctx, endpoint.id)
    return ApiEndpointOut.model_validate(data)


async def _replace_sources(ctx: AppContext, endpoint_id: int, source_ids: list[int]) -> list[int]:
    unique_ids = list(dict.fromkeys(int(value) for value in source_ids))
    async with ctx.session_factory() as session:
        endpoint = await session.get(ApiEndpoint, endpoint_id)
        if endpoint is None:
            raise AppError("not_found", "API endpoint not found", status_code=404)
        if unique_ids:
            found = set(
                int(value)
                for value in (
                    await session.execute(
                        select(SourceChannel.id).where(SourceChannel.id.in_(unique_ids))
                    )
                )
                .scalars()
                .all()
            )
            missing = [value for value in unique_ids if value not in found]
            if missing:
                raise AppError(
                    "validation_error",
                    "One or more source channels do not exist",
                    status_code=422,
                    details={"missing_source_ids": missing},
                )
        await session.execute(
            delete(SourceApiEndpointLink).where(
                SourceApiEndpointLink.api_endpoint_id == endpoint_id
            )
        )
        session.add_all(
            [
                SourceApiEndpointLink(source_id=source_id, api_endpoint_id=endpoint_id)
                for source_id in unique_ids
            ]
        )
        await session.commit()
    return unique_ids


@router.get("/api-endpoints", response_model=Envelope[dict[str, Any]])
async def list_api_endpoints(
    _user: ViewerUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        rows = list(
            (await session.execute(select(ApiEndpoint).order_by(ApiEndpoint.id))).scalars().all()
        )
    return Envelope(data={"items": [await _out(ctx, row) for row in rows]})


@router.post("/api-endpoints", response_model=Envelope[ApiEndpointSecretOut])
async def create_api_endpoint(
    body: ApiEndpointCreate,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ApiEndpointSecretOut]:
    secret = body.token or generate_api_token()
    source_ids = list(dict.fromkeys(int(value) for value in body.source_ids))
    async with ctx.session_factory() as session:
        if source_ids:
            found = set(
                int(value)
                for value in (
                    await session.execute(
                        select(SourceChannel.id).where(SourceChannel.id.in_(source_ids))
                    )
                )
                .scalars()
                .all()
            )
            missing = [value for value in source_ids if value not in found]
            if missing:
                raise AppError(
                    "validation_error",
                    "One or more source channels do not exist",
                    status_code=422,
                    details={"missing_source_ids": missing},
                )
        endpoint = ApiEndpoint(
            name=body.name,
            token_hash=hash_api_token(secret),
            token_prefix=token_prefix(secret),
            enabled=body.enabled,
            expires_at=body.expires_at,
        )
        session.add(endpoint)
        try:
            await session.flush()
            session.add_all(
                [
                    SourceApiEndpointLink(
                        source_id=source_id,
                        api_endpoint_id=endpoint.id,
                    )
                    for source_id in source_ids
                ]
            )
            await session.commit()
        except IntegrityError as exc:
            raise AppError(
                "token_conflict", "This API token is already in use", status_code=409
            ) from exc
        await session.refresh(endpoint)
    data = (await _out(ctx, endpoint)).model_dump()
    data["token"] = secret
    return Envelope(data=ApiEndpointSecretOut.model_validate(data))


@router.patch("/api-endpoints/{endpoint_id}", response_model=Envelope[ApiEndpointOut])
async def patch_api_endpoint(
    endpoint_id: int,
    body: ApiEndpointPatch,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ApiEndpointOut]:
    changes = body.model_dump(exclude_unset=True)
    if ("name" in changes and changes["name"] is None) or (
        "enabled" in changes and changes["enabled"] is None
    ):
        raise AppError(
            "validation_error",
            "name and enabled cannot be null",
            status_code=422,
        )
    async with ctx.session_factory() as session:
        endpoint = await session.get(ApiEndpoint, endpoint_id)
        if endpoint is None:
            raise AppError("not_found", "API endpoint not found", status_code=404)
        for key, value in changes.items():
            setattr(endpoint, key, value)
        await session.commit()
        await session.refresh(endpoint)
    return Envelope(data=await _out(ctx, endpoint))


@router.post(
    "/api-endpoints/{endpoint_id}/rotate-token",
    response_model=Envelope[ApiEndpointSecretOut],
)
async def rotate_api_endpoint_token(
    endpoint_id: int,
    body: RotateTokenRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[ApiEndpointSecretOut]:
    secret = body.token or generate_api_token()
    async with ctx.session_factory() as session:
        endpoint = await session.get(ApiEndpoint, endpoint_id)
        if endpoint is None:
            raise AppError("not_found", "API endpoint not found", status_code=404)
        endpoint.token_hash = hash_api_token(secret)
        endpoint.token_prefix = token_prefix(secret)
        try:
            await session.commit()
        except IntegrityError as exc:
            raise AppError(
                "token_conflict", "This API token is already in use", status_code=409
            ) from exc
        await session.refresh(endpoint)
    data = (await _out(ctx, endpoint)).model_dump()
    data["token"] = secret
    return Envelope(data=ApiEndpointSecretOut.model_validate(data))


@router.put("/api-endpoints/{endpoint_id}/sources", response_model=Envelope[dict[str, Any]])
async def put_api_endpoint_sources(
    endpoint_id: int,
    body: LinkSourcesRequest,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    source_ids = await _replace_sources(ctx, endpoint_id, body.source_ids)
    return Envelope(data={"source_ids": source_ids})


@router.delete("/api-endpoints/{endpoint_id}", response_model=Envelope[dict[str, Any]])
async def delete_api_endpoint(
    endpoint_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        endpoint = await session.get(ApiEndpoint, endpoint_id)
        if endpoint is None:
            raise AppError("not_found", "API endpoint not found", status_code=404)
        await session.execute(
            delete(SourceApiEndpointLink).where(
                SourceApiEndpointLink.api_endpoint_id == endpoint_id
            )
        )
        await session.execute(delete(ApiDelivery).where(ApiDelivery.api_endpoint_id == endpoint_id))
        await session.delete(endpoint)
        await session.commit()
    return Envelope(data={"deleted": True, "id": endpoint_id})


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


@public_router.get("/api/public/v1/messages", response_model=Envelope[dict[str, Any]])
async def pull_processed_messages(
    ctx: Annotated[AppContext, Depends(get_ctx)],
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Envelope[dict[str, Any]]:
    token = _bearer_token(authorization)
    if token is None:
        raise AppError("unauthorized", "A valid API token is required", status_code=401)
    delivery_service = ApiDeliveryService(ctx.session_factory)
    endpoint = await delivery_service.authenticate(token)
    if endpoint is None:
        raise AppError("unauthorized", "A valid API token is required", status_code=401)
    rows, has_more = await delivery_service.pull(endpoint.id, cursor=cursor, limit=limit)
    items = [
        {
            "delivery_id": row.id,
            "created_at": row.created_at,
            **row.payload,
        }
        for row in rows
    ]
    next_cursor = rows[-1].id if rows else cursor
    response.headers["Cache-Control"] = "no-store"
    return Envelope(
        data={
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }
    )
