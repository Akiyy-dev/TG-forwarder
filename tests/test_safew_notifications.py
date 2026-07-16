"""SafeW desktop notification normalization tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.listeners.freedesktop_notifications import FreedesktopNotifications
from app.listeners.safew_notifications import (
    DesktopNotification,
    SafeWNotificationNormalizer,
    clean_notification_text,
    safew_chat_id,
)
from app.source_backends import (
    SAFEW_CHAT_ID_BASE,
    is_safew_chat_id,
    source_backend_for_chat_id,
)


def test_clean_notification_markup() -> None:
    assert clean_notification_text("<b>Alice</b><br>hello &amp; welcome") == (
        "Alice\nhello & welcome"
    )


def test_safew_notification_maps_to_stable_source() -> None:
    normalizer = SafeWNotificationNormalizer(
        app_names=["SafeW"],
        allowed_chats=["Private Group"],
    )
    received_at = datetime(2026, 7, 16, 10, 20, 30, tzinfo=UTC)
    message = normalizer.normalize(
        DesktopNotification(
            app_name="org.safew.desktop",
            notification_id=12,
            summary="Private Group",
            body="<b>Alice</b><br>Hello",
            received_at=received_at,
        )
    )

    assert message is not None
    assert message.source_chat_id == safew_chat_id("private group")
    assert message.source_chat_id < -SAFEW_CHAT_ID_BASE
    assert is_safew_chat_id(message.source_chat_id)
    assert source_backend_for_chat_id(message.source_chat_id) == "safew"
    assert source_backend_for_chat_id(-1001234567890) == "telegram"
    assert message.source_chat_title == "Private Group"
    assert message.text == "Alice\nHello"
    assert message.date == received_at
    assert message.raw_metadata["source_backend"] == "safew"


def test_safew_notification_filters_other_apps_and_chats() -> None:
    normalizer = SafeWNotificationNormalizer(
        app_names=["SafeW"],
        allowed_chats=["Allowed"],
    )
    assert (
        normalizer.normalize(
            DesktopNotification(app_name="mail", notification_id=1, summary="Allowed", body="text")
        )
        is None
    )
    assert (
        normalizer.normalize(
            DesktopNotification(app_name="SafeW", notification_id=2, summary="Other", body="text")
        )
        is None
    )


async def test_dbus_interface_forwards_notification_to_handler() -> None:
    received: list[DesktopNotification] = []

    async def handler(notification: DesktopNotification) -> None:
        received.append(notification)

    interface = FreedesktopNotifications(handler)
    interface.Notify("SafeW", 0, "", "Private Group", "hello", [], {}, -1)
    for _ in range(10):
        if received:
            break
        await asyncio.sleep(0)

    assert len(received) == 1
    assert received[0].app_name == "SafeW"
    assert received[0].summary == "Private Group"
