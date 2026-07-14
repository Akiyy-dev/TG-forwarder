"""Unified internal message model and processing result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class MediaType(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"
    ANIMATION = "animation"
    AUDIO = "audio"
    VOICE = "voice"
    STICKER = "sticker"
    ALBUM = "album"
    UNSUPPORTED = "unsupported"


class ProcessAction(StrEnum):
    CONTINUE = "continue"
    DROP = "drop"
    REVIEW = "review"
    FAIL = "fail"


class MessageStatus(StrEnum):
    RECEIVED = "received"
    COLLECTING_ALBUM = "collecting_album"
    PROCESSING = "processing"
    FILTERED = "filtered"
    PENDING_REVIEW = "pending_review"
    PENDING_PUBLISH = "pending_publish"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    RETRYING = "retrying"
    FAILED = "failed"


@dataclass(slots=True)
class MessageEntity:
    type: str
    offset: int
    length: int
    url: str | None = None
    user_id: int | None = None
    language: str | None = None
    custom_emoji_id: str | None = None


@dataclass(slots=True)
class MediaItem:
    media_type: MediaType
    local_path: str | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    original_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    source_message_id: int | None = None
    order: int = 0


@dataclass(slots=True)
class ForwardInfo:
    from_chat_id: int | None = None
    from_message_id: int | None = None
    from_name: str | None = None
    date: datetime | None = None


@dataclass(slots=True)
class NormalizedMessage:
    source_chat_id: int
    source_message_id: int
    source_chat_username: str | None = None
    source_chat_title: str | None = None
    grouped_id: int | None = None
    date: datetime | None = None
    edit_date: datetime | None = None
    text: str = ""
    entities: list[MessageEntity] = field(default_factory=list)
    media_type: MediaType = MediaType.TEXT
    media_items: list[MediaItem] = field(default_factory=list)
    original_filename: str | None = None
    mime_type: str | None = None
    file_size: int | None = None
    reply_to_message_id: int | None = None
    forward_info: ForwardInfo | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    target_chat_id: int | None = None
    album_message_ids: list[int] = field(default_factory=list)

    @property
    def display_text(self) -> str:
        return self.text or ""


@dataclass(slots=True)
class ProcessingContext:
    target_chat_id: int
    source_username: str | None = None
    paused: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessResult:
    action: ProcessAction = ProcessAction.CONTINUE
    message: NormalizedMessage | None = None
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def cont(cls, message: NormalizedMessage, **detail: Any) -> ProcessResult:
        return cls(action=ProcessAction.CONTINUE, message=message, detail=detail)

    @classmethod
    def drop(cls, message: NormalizedMessage, reason: str, **detail: Any) -> ProcessResult:
        return cls(action=ProcessAction.DROP, message=message, reason=reason, detail=detail)

    @classmethod
    def fail(cls, message: NormalizedMessage, reason: str, **detail: Any) -> ProcessResult:
        return cls(action=ProcessAction.FAIL, message=message, reason=reason, detail=detail)

    @classmethod
    def review(cls, message: NormalizedMessage, reason: str, **detail: Any) -> ProcessResult:
        return cls(action=ProcessAction.REVIEW, message=message, reason=reason, detail=detail)
