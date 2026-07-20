"""Channel configuration schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PublishMode(StrEnum):
    AUTO = "auto"
    REVIEW = "review"
    RULE_BASED = "rule_based"
    PAUSED = "paused"


class TargetBackend(StrEnum):
    TELEGRAM = "telegram"
    SAFEW = "safew"


@dataclass(frozen=True, slots=True)
class TargetRoute:
    id: int
    target_backend: TargetBackend
    chat_id: int
    title: str | None = None


@dataclass(slots=True)
class SourceChannelConfig:
    chat_id: int
    username: str | None = None
    title: str | None = None
    enabled: bool = True
    publish_mode: PublishMode = PublishMode.REVIEW
    target_channel_id: int | None = None
    target_chat_ids: list[int] | None = None
    target_ids: list[int] | None = None
    access_status: str = "unknown"
    processing_profile: str = "default"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None
