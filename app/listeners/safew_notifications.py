"""Normalize SafeW desktop notifications into the internal message model."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.schemas.message import MediaType, NormalizedMessage

_TAG_RE = re.compile(r"<[^>]*>")
_BREAK_RE = re.compile(r"<\s*br\s*/?\s*>", flags=re.IGNORECASE)


def clean_notification_text(value: str) -> str:
    """Remove the small HTML subset allowed by desktop notifications."""
    with_breaks = _BREAK_RE.sub("\n", value or "")
    plain = _TAG_RE.sub("", with_breaks)
    lines = [line.strip() for line in html.unescape(plain).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def safew_chat_id(title: str) -> int:
    """Map a SafeW conversation title into a reserved signed 64-bit range."""
    digest = hashlib.blake2b(title.casefold().encode("utf-8"), digest_size=7).digest()
    return -(2_000_000_000_000_000 + int.from_bytes(digest, "big"))


def safew_message_id(received_at: datetime, notification_id: int, text: str) -> int:
    """Create a sortable, process-independent id for a notification event."""
    epoch_us = int(received_at.timestamp() * 1_000_000)
    salt = hashlib.blake2b(f"{notification_id}:{text}".encode(), digest_size=1).digest()[0]
    return epoch_us * 256 + salt


@dataclass(slots=True)
class DesktopNotification:
    app_name: str
    notification_id: int
    summary: str
    body: str
    app_icon: str = ""
    actions: list[str] | None = None
    hints: dict[str, Any] | None = None
    expire_timeout: int = -1
    received_at: datetime | None = None


class SafeWNotificationNormalizer:
    def __init__(
        self,
        *,
        app_names: list[str],
        allowed_chats: list[str] | None = None,
        capture_all_apps: bool = False,
    ) -> None:
        self.app_names = [item.casefold() for item in app_names if item.strip()]
        self.allowed_chats = {
            item.strip().casefold() for item in (allowed_chats or []) if item.strip()
        }
        self.capture_all_apps = capture_all_apps

    def accepts_app(self, app_name: str) -> bool:
        if self.capture_all_apps:
            return True
        candidate = app_name.casefold()
        if not candidate:
            return False
        return any(name in candidate or candidate in name for name in self.app_names)

    def normalize(self, notification: DesktopNotification) -> NormalizedMessage | None:
        if not self.accepts_app(notification.app_name):
            return None
        title = clean_notification_text(notification.summary) or "SafeW"
        if self.allowed_chats and title.casefold() not in self.allowed_chats:
            return None
        body = clean_notification_text(notification.body)
        received_at = notification.received_at or datetime.now(UTC)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        raw_hints = {}
        for key, value in (notification.hints or {}).items():
            raw_hints[str(key)] = getattr(value, "value", value)
        message_id = safew_message_id(
            received_at,
            notification.notification_id,
            f"{title}\n{body}",
        )
        return NormalizedMessage(
            source_chat_id=safew_chat_id(title),
            source_message_id=message_id,
            source_chat_title=title,
            date=received_at,
            text=body,
            media_type=MediaType.TEXT,
            raw_metadata={
                "source_backend": "safew",
                "notification_app": notification.app_name,
                "notification_id": notification.notification_id,
                "app_icon": notification.app_icon,
                "actions": notification.actions or [],
                "hints": raw_hints,
                "expire_timeout": notification.expire_timeout,
            },
        )
