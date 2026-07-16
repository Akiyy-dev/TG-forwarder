"""Identify inbound message backends from reserved source chat-id ranges."""

from __future__ import annotations

from typing import Final, Literal

SourceBackend = Literal["telegram", "safew"]

SOURCE_BACKEND_TELEGRAM: Final[SourceBackend] = "telegram"
SOURCE_BACKEND_SAFEW: Final[SourceBackend] = "safew"

# Telegram channel ids are far smaller in magnitude. SafeW conversations use
# this reserved negative namespace so their backend can be recovered without a
# database column or migration.
SAFEW_CHAT_ID_BASE = 2_000_000_000_000_000


def is_safew_chat_id(chat_id: int) -> bool:
    """Return whether *chat_id* belongs to the reserved SafeW namespace."""
    return int(chat_id) <= -SAFEW_CHAT_ID_BASE


def source_backend_for_chat_id(chat_id: int) -> SourceBackend:
    """Infer the inbound backend from a persisted source chat id."""
    if is_safew_chat_id(chat_id):
        return SOURCE_BACKEND_SAFEW
    return SOURCE_BACKEND_TELEGRAM
