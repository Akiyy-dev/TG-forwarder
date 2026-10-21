"""Administrator-managed, independently authenticated text ingestion."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import AwareDatetime, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import SuperAdminUser, ViewerUser, get_ctx
from app.api.errors import AppError
from app.api.schemas import APIModel, Envelope
from app.context import AppContext
from app.database.models import IngestSource, ProcessedMessage, ReviewTask, SourceChannel
from app.schemas.message import MessageStatus, NormalizedMessage
from app.services.ingest_service import IngestService, generate_ingest_token, hash_ingest_token
from app.source_backends import API_CHAT_ID_BASE

router = APIRouter(tags=["ingest-sources"])
public_router = APIRouter(tags=["ingest"])


class StrictInput(APIModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ExpiringInput(StrictInput):
    expires_at: AwareDatetime | None = None

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime | None) -> datetime | None:
        # SQLite drops timezone information, so persist the UTC instant.
        return value.astimezone(UTC) if value is not None else None


class IngestSourceCreate(ExpiringInput):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class IngestSourcePatch(ExpiringInput):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None

    @field_validator("name", "enabled")
    @classmethod
    def nonnull(cls, value: str | bool | None) -> str | bool:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError("name and enabled must not be null or blank")
        return value


class IngestSourceOut(APIModel):
    id: int
    name: str
    source_id: int
    source_chat_id: int
    token_prefix: str
    enabled: bool
    expires_at: datetime | None = None
    last_access_at: datetime | None = None
    created_at: datetime

    @field_validator("expires_at", "last_access_at", "created_at")
    @classmethod
    def explicit_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        # SQLite returns naive values for stored UTC instants. Always expose
        # their offset so browser date parsing preserves the same instant.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class IngestSourceSecretOut(IngestSourceOut):
    token: str


class IngestMessageIn(StrictInput):
    message_id: str = Field(min_length=1, max_length=128)
    conversation_id: str = Field(default="default", min_length=1, max_length=128)
    conversation_name: str | None = Field(default=None, max_length=256)
    sender: str | None = Field(default=None, max_length=256)
    text: str = Field(min_length=1, max_length=65536)
    timestamp: AwareDatetime | None = None

    @field_validator("message_id", "conversation_id", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value

    @field_validator("timestamp", mode="before")
    @classmethod
    def iso_timestamp(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("timestamp must be an ISO 8601 string")
        # Pydantic also accepts Unix epochs encoded as strings. Parse explicitly
        # so only ISO input reaches AwareDatetime's timezone requirement.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _out(row: IngestSource, chat_id: int) -> IngestSourceOut:
    return IngestSourceOut(
        id=row.id,
        name=row.name,
        source_id=row.source_id,
        source_chat_id=chat_id,
        token_prefix=row.token_prefix,
        enabled=row.enabled,
        expires_at=row.expires_at,
        last_access_at=row.last_access_at,
        created_at=row.created_at,
    )


@router.get("/ingest-sources", response_model=Envelope[dict[str, Any]])
async def list_ingest_sources(
    _user: ViewerUser, ctx: Annotated[AppContext, Depends(get_ctx)]
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        rows = (
            await session.execute(
                select(IngestSource, SourceChannel.chat_id)
                .join(SourceChannel, SourceChannel.id == IngestSource.source_id)
                .order_by(IngestSource.id)
            )
        ).all()
    return Envelope(data={"items": [_out(row, chat_id) for row, chat_id in rows]})


@router.post("/ingest-sources", response_model=Envelope[IngestSourceSecretOut])
async def create_ingest_source(
    body: IngestSourceCreate,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[IngestSourceSecretOut]:
    token = generate_ingest_token()
    # A cryptographic 48-bit offset stays entirely inside the disjoint API range.
    # Retry the database uniqueness check rather than assuming random means unique.
    for _attempt in range(5):
        async with ctx.session_factory() as session:
            source = SourceChannel(
                chat_id=-(API_CHAT_ID_BASE + secrets.randbits(48)),
                title=body.name,
                enabled=True,
                publish_mode="review",
                access_status="ok",
            )
            session.add(source)
            try:
                await session.flush()
                row = IngestSource(
                    source_id=source.id,
                    name=body.name,
                    enabled=body.enabled,
                    expires_at=body.expires_at,
                    token_hash=hash_ingest_token(token),
                    token_prefix=token[:12],
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                data = _out(row, source.chat_id).model_dump()
                break
            except IntegrityError:
                await session.rollback()
    else:
        raise AppError("ingest_unavailable", "Unable to allocate API source", status_code=503)
    await ctx.channel_service.load_from_db()
    return Envelope(data=IngestSourceSecretOut(**data, token=token))


@router.patch("/ingest-sources/{ingest_id}", response_model=Envelope[IngestSourceOut])
async def patch_ingest_source(
    ingest_id: int,
    body: IngestSourcePatch,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[IngestSourceOut]:
    async with ctx.session_factory() as session:
        row = await session.get(IngestSource, ingest_id)
        if row is None:
            raise AppError("not_found", "Ingress registration not found", status_code=404)
        source = await session.get(SourceChannel, row.source_id)
        assert source is not None
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
            if key == "name":
                source.title = value
        await session.commit()
        await session.refresh(row)
        out = _out(row, source.chat_id)
    await ctx.channel_service.load_from_db()
    return Envelope(data=out)


@router.post(
    "/ingest-sources/{ingest_id}/rotate-token", response_model=Envelope[IngestSourceSecretOut]
)
async def rotate_ingest_token(
    ingest_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[IngestSourceSecretOut]:
    token = generate_ingest_token()
    async with ctx.session_factory() as session:
        row = await session.get(IngestSource, ingest_id)
        if row is None:
            raise AppError("not_found", "Ingress registration not found", status_code=404)
        source = await session.get(SourceChannel, row.source_id)
        assert source is not None
        row.token_hash = hash_ingest_token(token)
        row.token_prefix = token[:12]
        await session.commit()
        await session.refresh(row)
        data = _out(row, source.chat_id).model_dump()
    return Envelope(data=IngestSourceSecretOut(**data, token=token))


@router.delete("/ingest-sources/{ingest_id}", response_model=Envelope[dict[str, Any]])
async def revoke_ingest_source(
    ingest_id: int,
    _admin: SuperAdminUser,
    ctx: Annotated[AppContext, Depends(get_ctx)],
) -> Envelope[dict[str, Any]]:
    async with ctx.session_factory() as session:
        row = await session.get(IngestSource, ingest_id)
        if row is None:
            raise AppError("not_found", "Ingress registration not found", status_code=404)
        await session.delete(row)
        await session.commit()
    return Envelope(data={"deleted": True, "id": ingest_id})


@public_router.post("/api/ingest/v1/messages", response_model=Envelope[dict[str, Any]])
async def ingest_message(
    body: IngestMessageIn,
    ctx: Annotated[AppContext, Depends(get_ctx)],
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
) -> Envelope[dict[str, Any]]:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AppError("unauthorized", "A valid ingress token is required", status_code=401)
    service = IngestService(ctx.session_factory)
    authenticated = await service.authenticate(token.strip())
    if authenticated is None:
        raise AppError("unauthorized", "A valid ingress token is required", status_code=401)
    _credential, source = authenticated

    async def enqueue(message: NormalizedMessage) -> None:
        if ctx.command_bus is not None:
            await ctx.command_bus.publish_incoming("api", message)
        else:
            accepted = await ctx.message_service.enqueue(message)
            if not accepted:
                # Local registration reports False for completed work as well as
                # QueueFull. Only already-processing/finished records prove that
                # this receipt has previously reached the worker.
                async with ctx.session_factory() as session:
                    existing = (
                        await session.execute(
                            select(ProcessedMessage.status, ReviewTask.id)
                            .outerjoin(
                                ReviewTask, ReviewTask.processed_message_id == ProcessedMessage.id
                            )
                            .where(
                                ProcessedMessage.source_chat_id == message.source_chat_id,
                                ProcessedMessage.source_message_id == message.source_message_id,
                            )
                        )
                    ).one_or_none()
                if existing is None or (
                    existing[1] is None
                    and existing[0]
                    not in {
                        MessageStatus.PROCESSING.value,
                        MessageStatus.FILTERED.value,
                        MessageStatus.PENDING_PUBLISH.value,
                        MessageStatus.PUBLISHING.value,
                        MessageStatus.PUBLISHED.value,
                    }
                ):
                    raise RuntimeError("local delivery queue did not accept message")

    receipt, duplicate = await service.accept(source, body.model_dump(), enqueue)
    response.status_code = 200 if duplicate and receipt.queued_at is not None else 202
    response.headers["Cache-Control"] = "no-store"
    return Envelope(
        data={
            "receipt_id": receipt.id,
            "source_id": source.id,
            "message_id": receipt.external_message_id,
            "conversation_id": receipt.conversation_id,
            "status": receipt.status,
            "duplicate": duplicate,
        }
    )
