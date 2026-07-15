"""Telethon helpers for account channel discovery and accessibility checks."""

from __future__ import annotations

from typing import Any

from telethon import TelegramClient
from telethon.tl.types import Channel

from app.logging import get_logger

logger = get_logger(__name__)


def _parse_ref(ref: str) -> str | int:
    value = ref.strip()
    if value.startswith("@"):
        return value
    if value.lstrip("-").isdigit():
        return int(value)
    return value


def to_bot_chat_id(entity: Channel) -> int:
    cid = int(entity.id)
    return int(f"-100{cid}") if cid > 0 else cid


async def list_broadcast_channels(client: TelegramClient) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, Channel) or not getattr(entity, "broadcast", False):
            continue
        chat_id = to_bot_chat_id(entity)
        items.append(
            {
                "chat_id": chat_id,
                "username": getattr(entity, "username", None),
                "title": dialog.name or getattr(entity, "title", None),
                "accessible": True,
            }
        )
    return items


async def check_channel_accessible(
    client: TelegramClient,
    *,
    chat_id: int | None = None,
    username: str | None = None,
) -> dict[str, Any]:
    """Return {accessible, chat_id?, username?, title?, error?}."""
    ref: int | str | None = chat_id
    if ref is None and username:
        ref = _parse_ref(username if str(username).startswith("@") else f"@{username}")
    if ref is None:
        return {"accessible": False, "error": "missing chat_id/username"}
    try:
        entity = await client.get_entity(ref)
        if not isinstance(entity, Channel) or not getattr(entity, "broadcast", False):
            return {"accessible": False, "error": "not_a_broadcast_channel"}
        full_id = to_bot_chat_id(entity)
        # Readability probe
        try:
            await client.get_messages(entity, limit=1)
            readable = True
        except Exception as exc:  # noqa: BLE001
            logger.info("channel_read_probe_failed", error=type(exc).__name__)
            readable = False
        return {
            "accessible": readable,
            "chat_id": full_id,
            "username": getattr(entity, "username", None),
            "title": getattr(entity, "title", None),
            "error": None if readable else "not_readable",
        }
    except Exception as exc:  # noqa: BLE001
        return {"accessible": False, "error": type(exc).__name__}
