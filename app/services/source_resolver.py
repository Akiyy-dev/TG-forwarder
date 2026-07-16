"""Resolve configured Telegram channel references with an authorized user session."""

from __future__ import annotations

from typing import Any

from telethon import TelegramClient
from telethon.tl.types import Channel

from app.config import Settings
from app.logging import get_logger
from app.services.channel_service import parse_channel_ref

logger = get_logger(__name__)


def _full_channel_id(entity: Any) -> int:
    chat_id = int(entity.id)
    if isinstance(entity, Channel) and chat_id > 0:
        return int(f"-100{chat_id}")
    return chat_id


async def _authorized_client(settings: Settings) -> TelegramClient:
    client = TelegramClient(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError("Telegram session is not authorized; create the session first")
    return client


async def resolve_source_channels(
    settings: Settings,
) -> list[tuple[int, str | None, str | None]]:
    client = await _authorized_client(settings)
    resolved: list[tuple[int, str | None, str | None]] = []
    try:
        for ref in settings.source_channels:
            entity = await client.get_entity(parse_channel_ref(ref))
            resolved.append(
                (
                    _full_channel_id(entity),
                    getattr(entity, "username", None),
                    getattr(entity, "title", None),
                )
            )
    finally:
        await client.disconnect()
    return resolved


async def resolve_channel_config_entries(
    settings: Settings, entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    client = await _authorized_client(settings)
    resolved: list[dict[str, Any]] = []
    try:
        for entry in entries:
            chat_id = entry.get("chat_id")
            username = entry.get("username")
            title = entry.get("title")
            if chat_id is None:
                ref = username or entry.get("ref")
                if not ref:
                    continue
                entity = await client.get_entity(parse_channel_ref(str(ref)))
                chat_id = _full_channel_id(entity)
                username = getattr(entity, "username", None) or username
                title = title or getattr(entity, "title", None)
            resolved.append(
                {
                    "chat_id": int(chat_id),
                    "username": username,
                    "title": title,
                    "enabled": entry.get("enabled"),
                    "publish_mode": entry.get("publish_mode"),
                    "target_chat_id": entry.get("target_chat_id"),
                }
            )
    finally:
        await client.disconnect()
    logger.info("telegram_sources_resolved", count=len(resolved))
    return resolved
