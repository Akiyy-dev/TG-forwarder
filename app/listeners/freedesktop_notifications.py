"""Minimal org.freedesktop.Notifications server used inside the SafeW container."""

# D-Bus signatures intentionally use string annotations understood by dbus-next.
# ruff: noqa: F722, F821

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from dbus_next.aio import MessageBus
from dbus_next.constants import RequestNameReply
from dbus_next.service import ServiceInterface, method, signal

from app.listeners.safew_notifications import DesktopNotification
from app.logging import get_logger

logger = get_logger(__name__)
NotificationHandler = Callable[[DesktopNotification], Coroutine[Any, Any, None]]


class FreedesktopNotifications(ServiceInterface):
    def __init__(self, handler: NotificationHandler) -> None:
        super().__init__("org.freedesktop.Notifications")
        self.handler = handler
        self._next_id = 1
        self._tasks: set[asyncio.Task[None]] = set()

    def _schedule(self, notification: DesktopNotification) -> None:
        task: asyncio.Task[None] = asyncio.create_task(self.handler(notification))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    @method()
    def GetCapabilities(self) -> "as":  # type: ignore[valid-type]
        return ["body", "body-markup"]

    @method()
    def Notify(  # type: ignore[valid-type]
        self,
        app_name: "s",
        replaces_id: "u",
        app_icon: "s",
        summary: "s",
        body: "s",
        actions: "as",
        hints: "a{sv}",
        expire_timeout: "i",
    ) -> "u":
        notification_id = int(replaces_id) if replaces_id else self._next_id
        if not replaces_id:
            self._next_id += 1
        self._schedule(
            DesktopNotification(
                app_name=str(app_name),
                notification_id=notification_id,
                summary=str(summary),
                body=str(body),
                app_icon=str(app_icon),
                actions=list(actions),
                hints=dict(hints),
                expire_timeout=int(expire_timeout),
            )
        )
        return notification_id

    @method()
    def CloseNotification(self, notification_id: "u") -> None:  # type: ignore[valid-type]
        self.NotificationClosed(int(notification_id), 3)

    @method()
    def GetServerInformation(self) -> "ssss":  # type: ignore[valid-type]
        return ["TG-forwarder SafeW bridge", "TG-forwarder", "1.0", "1.2"]

    @signal()
    def NotificationClosed(  # type: ignore[valid-type]
        self, notification_id: "u", reason: "u"
    ) -> "uu":
        return [notification_id, reason]

    @signal()
    def ActionInvoked(self, notification_id: "u", action_key: "s") -> "us":  # type: ignore[valid-type]
        return [notification_id, action_key]


async def serve_notifications(handler: NotificationHandler, stop_event: asyncio.Event) -> None:
    """Own the desktop notification bus name until shutdown."""
    bus = await MessageBus().connect()
    interface = FreedesktopNotifications(handler)
    bus.export("/org/freedesktop/Notifications", interface)
    reply = await bus.request_name("org.freedesktop.Notifications")
    if reply not in {RequestNameReply.PRIMARY_OWNER, RequestNameReply.ALREADY_OWNER}:
        bus.disconnect()
        raise RuntimeError("another desktop notification service already owns the D-Bus name")
    logger.info("desktop_notification_service_ready")
    try:
        await stop_event.wait()
    finally:
        bus.disconnect()
        await interface.drain()
