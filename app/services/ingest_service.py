"""Durable inbound receipts and retryable enqueue with independent credentials."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import AppError
from app.database.models import IngestReceipt, IngestSource, SourceChannel
from app.messaging.models import message_from_dict, message_to_dict
from app.schemas.message import NormalizedMessage

Enqueue = Callable[[NormalizedMessage], Awaitable[None]]


def generate_ingest_token() -> str:
    return f"tgfi_{secrets.token_urlsafe(32)}"


def hash_ingest_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class IngestService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def authenticate(self, token: str) -> tuple[IngestSource, SourceChannel] | None:
        now = datetime.now(UTC)
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(IngestSource, SourceChannel)
                    .join(SourceChannel, SourceChannel.id == IngestSource.source_id)
                    .where(
                        IngestSource.token_hash == hash_ingest_token(token),
                        IngestSource.enabled.is_(True),
                        SourceChannel.enabled.is_(True),
                        or_(IngestSource.expires_at.is_(None), IngestSource.expires_at > now),
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            credential, source = row
            credential.last_access_at = now
            await session.commit()
            return credential, source

    async def _receipt(
        self, source: SourceChannel, submitted: dict[str, Any]
    ) -> tuple[IngestReceipt, bool]:
        # Server receipt time never enters this fingerprint. An omitted timestamp
        # remains null on every retry; equivalent supplied offsets normalize to UTC.
        timestamp = submitted.get("timestamp")
        canonical = {
            **submitted,
            "timestamp": timestamp.astimezone(UTC).isoformat() if timestamp else None,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode()
        ).hexdigest()
        key = (
            IngestReceipt.source_id == source.id,
            IngestReceipt.conversation_id == submitted["conversation_id"],
            IngestReceipt.external_message_id == submitted["message_id"],
        )
        async with self.session_factory() as session:
            receipt = (
                await session.execute(select(IngestReceipt).where(*key))
            ).scalar_one_or_none()
            duplicate = receipt is not None
            if receipt is None:
                receipt = IngestReceipt(
                    source_id=source.id,
                    conversation_id=submitted["conversation_id"],
                    external_message_id=submitted["message_id"],
                    fingerprint=fingerprint,
                    payload={},
                    status="pending",
                )
                session.add(receipt)
                try:
                    await session.flush()
                    message = NormalizedMessage(
                        source_chat_id=source.chat_id,
                        source_message_id=receipt.id,
                        source_chat_title=source.title,
                        text=submitted["text"],
                        date=timestamp or datetime.now(UTC),
                        raw_metadata={
                            "source_backend": "api",
                            "sender": submitted.get("sender"),
                            "conversation_id": submitted["conversation_id"],
                            "conversation_name": submitted.get("conversation_name"),
                            "external_message_id": submitted["message_id"],
                        },
                    )
                    receipt.payload = message_to_dict(message)
                    await session.commit()
                except IntegrityError:
                    # A competing worker inserted this same key. Its immutable
                    # receipt, rather than the incoming content, wins the race.
                    await session.rollback()
                    receipt = (
                        await session.execute(select(IngestReceipt).where(*key))
                    ).scalar_one()
                    duplicate = True
            if receipt.fingerprint != fingerprint:
                raise AppError(
                    "ingest_conflict",
                    "This message key already has different content",
                    status_code=409,
                )
            return receipt, duplicate

    async def accept(
        self, source: SourceChannel, submitted: dict[str, Any], enqueue: Enqueue
    ) -> tuple[IngestReceipt, bool]:
        receipt, duplicate = await self._receipt(source, submitted)
        # Database leases serialize publication across web workers. Publication is
        # bounded below the lease duration. A crashed worker can be retried after
        # expiry, including when Redis accepted an event but its ack was lost.
        lease = secrets.token_hex(16)
        for _attempt in range(21):
            async with self.session_factory() as session:
                current = await session.get(IngestReceipt, receipt.id)
                assert current is not None
                if current.status == "queued":
                    return current, duplicate
                now = datetime.now(UTC)
                claimed = (
                    await session.execute(
                        update(IngestReceipt)
                        .where(
                            IngestReceipt.id == receipt.id,
                            IngestReceipt.status == "pending",
                            or_(
                                IngestReceipt.lease_expires_at.is_(None),
                                IngestReceipt.lease_expires_at <= now,
                            ),
                        )
                        .values(lease_token=lease, lease_expires_at=now + timedelta(seconds=30))
                        .returning(IngestReceipt.id)
                        .execution_options(synchronize_session=False)
                    )
                ).scalar_one_or_none()
                await session.commit()
            if claimed is not None:
                break
            await asyncio.sleep(0.05)
        else:
            raise AppError(
                "ingest_busy", "Message is being queued; retry this key", status_code=503
            )

        try:
            await asyncio.wait_for(enqueue(message_from_dict(receipt.payload)), timeout=10)
            async with self.session_factory() as session:
                await session.execute(
                    update(IngestReceipt)
                    .where(IngestReceipt.id == receipt.id, IngestReceipt.lease_token == lease)
                    .values(
                        status="queued",
                        queued_at=datetime.now(UTC),
                        lease_token=None,
                        lease_expires_at=None,
                    )
                )
                await session.commit()
        except Exception as exc:
            async with self.session_factory() as session:
                await session.execute(
                    update(IngestReceipt)
                    .where(IngestReceipt.id == receipt.id, IngestReceipt.lease_token == lease)
                    .values(lease_token=None, lease_expires_at=None)
                )
                await session.commit()
            raise AppError(
                "ingest_unavailable",
                "Delivery queue unavailable; retry this message key",
                status_code=503,
            ) from exc
        receipt.status = "queued"
        return receipt, duplicate
