from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import app.listeners.telegram_listener as telegram_listener_module
from app.listeners.telegram_listener import TelegramListener


class _FakeTelegramClient:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.connected = False
        self.registered_events: list[tuple[str, list[int]]] = []

    async def connect(self) -> None:
        self.connected = True

    async def is_user_authorized(self) -> bool:
        return True

    def is_connected(self) -> bool:
        return self.connected

    def on(
        self, event: tuple[str, list[int]]
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        self.registered_events.append(event)

        def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
            return handler

        return decorator


def _listener(monkeypatch: Any, source_chat_ids: set[int]) -> TelegramListener:
    monkeypatch.setattr(telegram_listener_module, "TelegramClient", _FakeTelegramClient)
    monkeypatch.setattr(
        telegram_listener_module.events,
        "Album",
        lambda *, chats: ("album", chats),
    )
    monkeypatch.setattr(
        telegram_listener_module.events,
        "NewMessage",
        lambda *, chats: ("new_message", chats),
    )

    async def on_message(_message: Any) -> None:
        return None

    return TelegramListener(
        api_id=12345,
        api_hash="hash",
        session_path="test-session",
        source_chat_ids=source_chat_ids,
        on_message=on_message,
    )


async def test_start_with_no_sources_registers_no_handlers(monkeypatch: Any) -> None:
    listener = _listener(monkeypatch, set())

    await listener.start()

    assert listener.client.registered_events == []
    allowed, _, _ = listener._chat_allowed(SimpleNamespace(id=123))
    assert allowed is False


async def test_start_with_sources_keeps_filtered_handlers(monkeypatch: Any) -> None:
    listener = _listener(monkeypatch, {-100123, -100456})

    await listener.start()

    assert [event_type for event_type, _ in listener.client.registered_events] == [
        "album",
        "new_message",
    ]
    for _, chats in listener.client.registered_events:
        assert set(chats) == {-100123, -100456}

    allowed, _, full_id = listener._chat_allowed(SimpleNamespace(id=123))
    assert full_id == -100123
    assert allowed is True
