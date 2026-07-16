"""Versioned JSON contracts used on Redis Streams."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.schemas.message import (
    ForwardInfo,
    MediaItem,
    MediaType,
    MessageEntity,
    NormalizedMessage,
)

EVENT_SCHEMA_VERSION = 1
SourceBackend = Literal["telegram", "safew"]


def _datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def message_to_dict(message: NormalizedMessage) -> dict[str, Any]:
    """Convert the internal dataclass to a JSON-safe dictionary."""
    data = asdict(message)
    data["media_type"] = message.media_type.value
    for index, item in enumerate(message.media_items):
        data["media_items"][index]["media_type"] = item.media_type.value
    for key in ("date", "edit_date"):
        value = data.get(key)
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    forward = data.get("forward_info")
    if isinstance(forward, dict) and isinstance(forward.get("date"), datetime):
        forward["date"] = forward["date"].isoformat()
    return data


def message_from_dict(data: dict[str, Any]) -> NormalizedMessage:
    """Rebuild a NormalizedMessage from a stream payload."""
    entities = [MessageEntity(**item) for item in data.get("entities") or []]
    media_items = [
        MediaItem(
            **{
                **item,
                "media_type": MediaType(item.get("media_type", MediaType.UNSUPPORTED.value)),
            }
        )
        for item in data.get("media_items") or []
    ]
    forward_data = data.get("forward_info")
    forward = None
    if isinstance(forward_data, dict):
        forward = ForwardInfo(
            **{
                **forward_data,
                "date": _datetime(forward_data.get("date")),
            }
        )
    return NormalizedMessage(
        source_chat_id=int(data["source_chat_id"]),
        source_message_id=int(data["source_message_id"]),
        source_chat_username=data.get("source_chat_username"),
        source_chat_title=data.get("source_chat_title"),
        grouped_id=data.get("grouped_id"),
        date=_datetime(data.get("date")),
        edit_date=_datetime(data.get("edit_date")),
        text=str(data.get("text") or ""),
        entities=entities,
        media_type=MediaType(data.get("media_type", MediaType.TEXT.value)),
        media_items=media_items,
        original_filename=data.get("original_filename"),
        mime_type=data.get("mime_type"),
        file_size=data.get("file_size"),
        reply_to_message_id=data.get("reply_to_message_id"),
        forward_info=forward,
        raw_metadata=dict(data.get("raw_metadata") or {}),
        target_chat_id=data.get("target_chat_id"),
        target_chat_ids=[int(item) for item in data.get("target_chat_ids") or []],
        album_message_ids=[int(item) for item in data.get("album_message_ids") or []],
    )


@dataclass(slots=True)
class IncomingMessageEvent:
    event_id: str
    backend: SourceBackend
    created_at: datetime
    message: NormalizedMessage
    schema_version: int = EVENT_SCHEMA_VERSION

    @classmethod
    def create(cls, backend: SourceBackend, message: NormalizedMessage) -> IncomingMessageEvent:
        return cls(
            event_id=uuid.uuid4().hex,
            backend=backend,
            created_at=datetime.now(UTC),
            message=message,
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "event_id": self.event_id,
                "backend": self.backend,
                "created_at": self.created_at.isoformat(),
                "message": message_to_dict(self.message),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def from_json(cls, value: str) -> IncomingMessageEvent:
        data = json.loads(value)
        if int(data.get("schema_version", 0)) != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported incoming event schema version")
        return cls(
            schema_version=EVENT_SCHEMA_VERSION,
            event_id=str(data["event_id"]),
            backend=data["backend"],
            created_at=_datetime(data["created_at"]) or datetime.now(UTC),
            message=message_from_dict(data["message"]),
        )


@dataclass(slots=True)
class CommandEvent:
    event_id: str
    kind: str
    created_at: datetime
    payload: dict[str, Any]
    schema_version: int = EVENT_SCHEMA_VERSION

    @classmethod
    def create(cls, kind: str, payload: dict[str, Any] | None = None) -> CommandEvent:
        return cls(
            event_id=uuid.uuid4().hex,
            kind=kind,
            created_at=datetime.now(UTC),
            payload=payload or {},
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "event_id": self.event_id,
                "kind": self.kind,
                "created_at": self.created_at.isoformat(),
                "payload": self.payload,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def from_json(cls, value: str) -> CommandEvent:
        data = json.loads(value)
        if int(data.get("schema_version", 0)) != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported command event schema version")
        return cls(
            schema_version=EVENT_SCHEMA_VERSION,
            event_id=str(data["event_id"]),
            kind=str(data["kind"]),
            created_at=_datetime(data["created_at"]) or datetime.now(UTC),
            payload=dict(data.get("payload") or {}),
        )
