"""Token-authenticated API destinations and their durable delivery queue."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    ApiDelivery,
    ApiEndpoint,
    SourceApiEndpointLink,
    SourceChannel,
)
from app.schemas.message import NormalizedMessage
from app.source_backends import source_backend_for_chat_id


def generate_api_token() -> str:
    return f"tgf_{secrets.token_urlsafe(32)}"


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_prefix(token: str) -> str:
    return token[:12]


class ApiDeliveryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _active_endpoint_clause(now: datetime) -> Any:
        return (
            ApiEndpoint.enabled.is_(True),
            or_(ApiEndpoint.expires_at.is_(None), ApiEndpoint.expires_at > now),
        )

    async def active_endpoint_ids(
        self,
        source_chat_id: int,
        candidates: list[int] | None = None,
    ) -> list[int]:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            stmt = (
                select(ApiEndpoint.id)
                .join(
                    SourceApiEndpointLink,
                    SourceApiEndpointLink.api_endpoint_id == ApiEndpoint.id,
                )
                .join(SourceChannel, SourceChannel.id == SourceApiEndpointLink.source_id)
                .where(
                    SourceChannel.chat_id == source_chat_id,
                    SourceChannel.enabled.is_(True),
                    *self._active_endpoint_clause(now),
                )
                .order_by(SourceApiEndpointLink.id)
            )
            if candidates is not None:
                if not candidates:
                    return []
                stmt = stmt.where(ApiEndpoint.id.in_(list(dict.fromkeys(candidates))))
            return [int(value) for value in (await session.execute(stmt)).scalars().all()]

    async def linked_endpoint_ids(self, source_id: int) -> list[int]:
        async with self.session_factory() as session:
            return [
                int(value)
                for value in (
                    await session.execute(
                        select(SourceApiEndpointLink.api_endpoint_id)
                        .where(SourceApiEndpointLink.source_id == source_id)
                        .order_by(SourceApiEndpointLink.id)
                    )
                )
                .scalars()
                .all()
            ]

    async def set_source_endpoints(self, source_id: int, endpoint_ids: list[int]) -> list[int]:
        unique_ids = list(dict.fromkeys(int(value) for value in endpoint_ids))
        async with self.session_factory() as session:
            if await session.get(SourceChannel, source_id) is None:
                raise ValueError("source channel not found")
            if unique_ids:
                found = set(
                    int(value)
                    for value in (
                        await session.execute(
                            select(ApiEndpoint.id).where(ApiEndpoint.id.in_(unique_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                if found != set(unique_ids):
                    raise ValueError("one or more API endpoints do not exist")
            await session.execute(
                delete(SourceApiEndpointLink).where(SourceApiEndpointLink.source_id == source_id)
            )
            session.add_all(
                [
                    SourceApiEndpointLink(source_id=source_id, api_endpoint_id=endpoint_id)
                    for endpoint_id in unique_ids
                ]
            )
            await session.commit()
        return unique_ids

    @staticmethod
    def public_payload(message: NormalizedMessage) -> dict[str, Any]:
        """Expose processed content while deliberately omitting local filesystem paths."""
        return {
            "source_backend": source_backend_for_chat_id(message.source_chat_id),
            "source_chat_id": message.source_chat_id,
            "source_message_id": message.source_message_id,
            "source_chat_username": message.source_chat_username,
            "grouped_id": message.grouped_id,
            "text": message.text,
            "media_type": message.media_type.value,
            "media_items": [
                {
                    "media_type": item.media_type.value,
                    "original_filename": item.original_filename,
                    "mime_type": item.mime_type,
                    "file_size": item.file_size,
                    "source_message_id": item.source_message_id,
                    "order": item.order,
                    "file_unique_id": item.file_unique_id,
                }
                for item in message.media_items
            ],
            "processed_at": datetime.now(UTC).isoformat(),
        }

    async def enqueue(
        self,
        *,
        source_chat_id: int,
        processed_message_id: int,
        message: NormalizedMessage,
        endpoint_ids: list[int] | None = None,
        review_task_id: int | None = None,
    ) -> list[int]:
        active_ids = await self.active_endpoint_ids(source_chat_id, endpoint_ids)
        if not active_ids:
            return []
        payload = self.public_payload(message)
        async with self.session_factory() as session:
            delivered: list[int] = []
            for endpoint_id in active_ids:
                existing = await session.execute(
                    select(ApiDelivery.id).where(
                        ApiDelivery.api_endpoint_id == endpoint_id,
                        ApiDelivery.processed_message_id == processed_message_id,
                    )
                )
                if existing.scalar_one_or_none() is None:
                    try:
                        async with session.begin_nested():
                            session.add(
                                ApiDelivery(
                                    api_endpoint_id=endpoint_id,
                                    processed_message_id=processed_message_id,
                                    review_task_id=review_task_id,
                                    payload=payload,
                                )
                            )
                            await session.flush()
                    except IntegrityError:
                        pass
                delivered.append(endpoint_id)
            await session.commit()
        return delivered

    async def authenticate(self, token: str) -> ApiEndpoint | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            endpoint = (
                await session.execute(
                    select(ApiEndpoint).where(
                        ApiEndpoint.token_hash == hash_api_token(token),
                        *self._active_endpoint_clause(now),
                    )
                )
            ).scalar_one_or_none()
            if endpoint is None:
                return None
            endpoint.last_access_at = now
            await session.commit()
            await session.refresh(endpoint)
            return endpoint

    async def pull(
        self,
        endpoint_id: int,
        *,
        cursor: int,
        limit: int,
    ) -> tuple[list[ApiDelivery], bool]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(ApiDelivery)
                        .where(
                            ApiDelivery.api_endpoint_id == endpoint_id,
                            ApiDelivery.id > cursor,
                        )
                        .order_by(ApiDelivery.id.asc())
                        .limit(limit + 1)
                    )
                )
                .scalars()
                .all()
            )
            return rows[:limit], len(rows) > limit
