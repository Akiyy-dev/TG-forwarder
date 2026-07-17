"""Select Telegram receiver sources from the shared channel registry."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import SourceChannel
from app.source_backends import is_safew_chat_id


@dataclass(frozen=True)
class TelegramSourceSnapshot:
    """Database state relevant to the Telegram receiver subscription."""

    has_database_sources: bool
    enabled_chat_ids: frozenset[int]


async def load_telegram_source_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> TelegramSourceSnapshot:
    """Return enabled Telegram ids and whether Telegram rows exist at all.

    Presence is tracked separately from enabled ids.  An empty enabled set with
    ``has_database_sources=True`` means every database-managed Telegram source
    is disabled and must not fall back to legacy file configuration.
    """

    async with session_factory() as session:
        rows = (await session.execute(select(SourceChannel.chat_id, SourceChannel.enabled))).all()

    telegram_rows = [
        (int(chat_id), bool(enabled))
        for chat_id, enabled in rows
        if not is_safew_chat_id(int(chat_id))
    ]
    return TelegramSourceSnapshot(
        has_database_sources=bool(telegram_rows),
        enabled_chat_ids=frozenset(chat_id for chat_id, enabled in telegram_rows if enabled),
    )


def select_effective_source_ids(
    snapshot: TelegramSourceSnapshot,
    fallback_chat_ids: Iterable[int],
) -> set[int]:
    """Choose database-managed ids, or legacy ids before the first DB row exists."""

    if snapshot.has_database_sources:
        return set(snapshot.enabled_chat_ids)
    return {int(chat_id) for chat_id in fallback_chat_ids if not is_safew_chat_id(chat_id)}


def telegram_source_selection_changed(
    initial: TelegramSourceSnapshot,
    current: TelegramSourceSnapshot,
) -> bool:
    """Return whether a receiver restart is required for the new DB state."""

    return initial != current
