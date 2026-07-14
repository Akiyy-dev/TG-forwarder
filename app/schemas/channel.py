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


@dataclass(slots=True)
class SourceChannelConfig:
    chat_id: int
    username: str | None = None
    title: str | None = None
    enabled: bool = True
    publish_mode: PublishMode = PublishMode.REVIEW
    target_channel_id: int | None = None
    processing_profile: str = "default"
    created_at: datetime | None = None
    updated_at: datetime | None = None
