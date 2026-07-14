"""Channel configuration schemas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SourceChannelConfig:
    chat_id: int
    username: str | None = None
    title: str | None = None
    enabled: bool = True
    target_channel_id: int | None = None
    processing_profile: str = "default"
    created_at: datetime | None = None
    updated_at: datetime | None = None
