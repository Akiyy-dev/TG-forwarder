"""Telegram receiver source selection tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.database.models import SourceChannel
from app.entrypoints import telegram_receiver
from app.listeners.safew_notifications import safew_chat_id
from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.services.telegram_source_registry import (
    TelegramSourceSnapshot,
    load_telegram_source_snapshot,
    telegram_source_selection_changed,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_database_snapshot_excludes_safew_and_disabled_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                SourceChannel(chat_id=-1001, title="enabled", enabled=True),
                SourceChannel(chat_id=-1002, title="disabled", enabled=False),
                SourceChannel(chat_id=safew_chat_id("SafeW"), title="SafeW", enabled=True),
            ]
        )
        await session.commit()

    snapshot = await load_telegram_source_snapshot(session_factory)

    assert snapshot.enabled_chat_ids == frozenset({-1001})


async def test_all_disabled_database_sources_select_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(SourceChannel(chat_id=-1002, title="disabled", enabled=False))
        await session.commit()

    snapshot = await load_telegram_source_snapshot(session_factory)

    assert snapshot.enabled_chat_ids == frozenset()


async def test_only_safew_rows_select_no_telegram_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    safe_id = safew_chat_id("SafeW only")
    async with session_factory() as session:
        session.add(SourceChannel(chat_id=safe_id, title="SafeW", enabled=True))
        await session.commit()

    snapshot = await load_telegram_source_snapshot(session_factory)

    assert snapshot.enabled_chat_ids == frozenset()


def test_source_selection_change_tracks_database_registration() -> None:
    database_empty = TelegramSourceSnapshot(frozenset())
    database_enabled = TelegramSourceSnapshot(frozenset({-1001}))

    assert telegram_source_selection_changed(database_empty, database_enabled) is True
    assert telegram_source_selection_changed(database_enabled, database_enabled) is False


async def test_initial_database_failure_is_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = TelegramSourceSnapshot(frozenset({-1001}))
    loader = AsyncMock(side_effect=[RuntimeError("temporary"), expected])
    monkeypatch.setattr(telegram_receiver, "load_telegram_source_snapshot", loader)

    result = await telegram_receiver._wait_for_initial_snapshot(
        MagicMock(), asyncio.Event(), retry_seconds=0
    )

    assert result == expected
    assert loader.await_count == 2


async def test_monitor_ignores_temporary_database_failure_then_detects_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = TelegramSourceSnapshot(frozenset({-1001}))
    changed = TelegramSourceSnapshot(frozenset())
    loader = AsyncMock(side_effect=[RuntimeError("temporary"), changed])
    monkeypatch.setattr(telegram_receiver, "load_telegram_source_snapshot", loader)

    await telegram_receiver._monitor_source_changes(
        MagicMock(), initial, asyncio.Event(), refresh_seconds=0
    )

    assert loader.await_count == 2


async def test_permanent_media_error_retries_only_redis_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=9,
        text="caption",
        media_type=MediaType.VIDEO,
        media_items=[MediaItem(media_type=MediaType.VIDEO, file_size=999)],
    )
    media_service = MagicMock()
    media_service.ensure_materialized = AsyncMock(side_effect=ValueError("file too large"))
    bus = MagicMock()
    bus.publish_incoming = AsyncMock(side_effect=[RuntimeError("redis down"), "1-0"])
    wait = AsyncMock(return_value=False)
    monkeypatch.setattr(telegram_receiver, "_wait_for_stop", wait)

    await telegram_receiver._publish_incoming_message(
        message,
        media_service,
        bus,
        asyncio.Event(),
    )

    media_service.ensure_materialized.assert_awaited_once()
    assert bus.publish_incoming.await_count == 2
    assert message.raw_metadata["media_materialization_error"]["exception_type"] == "ValueError"
    wait.assert_awaited_once()
