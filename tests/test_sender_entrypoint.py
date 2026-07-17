"""Sender entrypoint lifecycle tests."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.config import Settings
from app.entrypoints import sender
from app.messaging.models import IncomingMessageEvent
from app.schemas.message import MediaType, NormalizedMessage


def _incoming_event(
    backend: str,
    *,
    source_chat_id: int = -100123,
    source_registry_origin: str | None = None,
) -> IncomingMessageEvent:
    message = NormalizedMessage(
        source_chat_id=source_chat_id,
        source_message_id=1,
        text="test",
        media_type=MediaType.TEXT,
    )
    if source_registry_origin is not None:
        message.raw_metadata["source_registry_origin"] = source_registry_origin
    return IncomingMessageEvent.create(cast(Any, backend), message)


@pytest.mark.parametrize("origin", [None, "database"])
async def test_unknown_telegram_source_is_ignored_unless_from_legacy_config(
    settings_env: Settings,
    origin: str | None,
) -> None:
    channel_service = MagicMock(configured_chat_ids=set())
    channel_service.sync_from_config_rows = AsyncMock()

    accepted = await sender._accept_or_register_source(
        _incoming_event("telegram", source_registry_origin=origin),
        settings_env,
        channel_service,
    )

    assert accepted is False
    channel_service.sync_from_config_rows.assert_not_awaited()


async def test_unknown_legacy_telegram_source_is_registered_once(
    settings_env: Settings,
) -> None:
    channel_service = MagicMock(configured_chat_ids=set())
    channel_service.sync_from_config_rows = AsyncMock()

    accepted = await sender._accept_or_register_source(
        _incoming_event("telegram", source_registry_origin="legacy_config"),
        settings_env,
        channel_service,
    )

    assert accepted is True
    channel_service.sync_from_config_rows.assert_awaited_once()
    row = channel_service.sync_from_config_rows.await_args.args[0][0]
    assert row["chat_id"] == -100123
    assert row["enabled"] is True


async def test_safew_auto_registration_setting_is_preserved(settings_env: Settings) -> None:
    channel_service = MagicMock(configured_chat_ids=set())
    channel_service.sync_from_config_rows = AsyncMock()
    event = _incoming_event("safew")

    assert await sender._accept_or_register_source(event, settings_env, channel_service) is True
    channel_service.sync_from_config_rows.assert_awaited_once()

    settings_env.safew_auto_register_sources = False
    channel_service.sync_from_config_rows.reset_mock()
    assert await sender._accept_or_register_source(event, settings_env, channel_service) is False
    channel_service.sync_from_config_rows.assert_not_awaited()


def test_bot_polling_is_not_started_when_disabled(settings_env: Settings) -> None:
    settings_env.bot_polling_enabled = False

    dispatcher, task = sender._start_bot_polling(
        settings_env,
        bot=cast(Any, object()),
        message_service=cast(Any, object()),
        channel_service=cast(Any, object()),
    )

    assert dispatcher is None
    assert task is None


@pytest.mark.asyncio
async def test_bot_polling_is_started_when_enabled(
    settings_env: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = AsyncMock()
    monkeypatch.setattr(sender, "create_dispatcher", lambda *_args, **_kwargs: dispatcher)

    created_dispatcher, task = sender._start_bot_polling(
        settings_env,
        bot=cast(Any, object()),
        message_service=cast(Any, object()),
        channel_service=cast(Any, object()),
    )

    assert created_dispatcher is dispatcher
    assert task is not None
    await task
    dispatcher.start_polling.assert_awaited_once()
