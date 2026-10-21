"""Public-safe identity fields shared by captured-message views."""

from __future__ import annotations

from typing import Any

IDENTITY_FIELDS = ("sender", "conversation_id", "conversation_name", "external_message_id")


def message_identity(metadata: Any) -> dict[str, str | None]:
    values = metadata if isinstance(metadata, dict) else {}
    return {
        key: value if isinstance(value := values.get(key), str) else None for key in IDENTITY_FIELDS
    }
