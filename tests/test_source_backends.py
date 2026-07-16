"""Source backend inference and channel reachability behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import Settings
from app.database.models import SourceChannel
from app.listeners.safew_notifications import safew_chat_id
from app.services.channel_service import ChannelService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_safew_source_can_be_reenabled_without_telegram_probe(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = ChannelService(settings_env, session_factory)
    chat_id = safew_chat_id("Private SafeW Group")
    source = await service.create_source({"chat_id": chat_id, "title": "Private SafeW Group"})
    assert source.access_status == "ok"

    async with session_factory() as session:
        persisted = await session.get(SourceChannel, source.id)
        assert persisted is not None
        persisted.enabled = False
        persisted.access_status = "missing"
        await session.commit()

    telegram_client = MagicMock()
    updated = await service.update_source(source.id, {"enabled": True}, client=telegram_client)

    assert updated.enabled is True
    assert updated.access_status == "ok"
    telegram_client.get_entity.assert_not_called()


async def test_refresh_skips_telegram_reachability_for_safew_sources(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ChannelService(settings_env, session_factory)
    safew = await service.create_source(
        {"chat_id": safew_chat_id("SafeW Channel"), "title": "SafeW Channel"}
    )
    telegram = await service.create_source({"chat_id": -100987654321, "title": "TG Channel"})

    list_channels = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.channel_service.list_broadcast_channels", list_channels)

    await service.refresh_channels(MagicMock())

    refreshed_safew = await service.get_source(safew.id)
    refreshed_telegram = await service.get_source(telegram.id)
    assert refreshed_safew.enabled is True
    assert refreshed_safew.access_status == "ok"
    assert refreshed_telegram.enabled is False
    assert refreshed_telegram.access_status == "missing"
    list_channels.assert_awaited_once()
