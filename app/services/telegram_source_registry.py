"""Select Telegram receiver sources from the shared channel registry."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import SourceChannel
from app.source_backends import is_safew_chat_id


@dataclass(frozen=True)
class TelegramSourceSnapshot:
    """Database state relevant to the Telegram receiver subscription."""

    enabled_chat_ids: frozenset[int]


async def load_telegram_source_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> TelegramSourceSnapshot:
    """Return enabled Telegram ids from the Web-managed channel registry."""

    async with session_factory() as session:
        rows = (await session.execute(select(SourceChannel.chat_id, SourceChannel.enabled))).all()

    telegram_rows = [
        (int(chat_id), bool(enabled))
        for chat_id, enabled in rows
        if not is_safew_chat_id(int(chat_id))
    ]
    return TelegramSourceSnapshot(
        enabled_chat_ids=frozenset(chat_id for chat_id, enabled in telegram_rows if enabled),
    )


def telegram_source_selection_changed(
    initial: TelegramSourceSnapshot,
    current: TelegramSourceSnapshot,
) -> bool:
    """Return whether a receiver restart is required for the new DB state."""

    return initial != current
