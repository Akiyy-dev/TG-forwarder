"""SafeW desktop notification receiver."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from app.config import Settings
from app.entrypoints.common import install_shutdown_handlers
from app.listeners.freedesktop_notifications import serve_notifications
from app.listeners.safew_notifications import (
    DesktopNotification,
    SafeWNotificationNormalizer,
)
from app.logging import get_logger, setup_logging
from app.messaging.redis_streams import RedisStreamBus

logger = get_logger(__name__)


def _safew_client_running(proc_root: Path = Path("/proc")) -> bool:
    """Return whether the supervised SafeW desktop process is actually alive."""
    for cmdline in proc_root.glob("[0-9]*/cmdline"):
        try:
            argv = cmdline.read_bytes().split(b"\0")
        except (OSError, PermissionError):
            continue
        if argv and argv[0] == b"/opt/safew/SafeW":
            return True
    return False


async def run() -> None:
    settings = Settings(app_role="safew-receiver")
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    bus = RedisStreamBus(settings, consumer_name="safew-receiver")
    await bus.ping()
    normalizer = SafeWNotificationNormalizer(
        app_names=settings.safew_app_names,
        allowed_chats=settings.safew_allowed_chats,
        capture_all_apps=settings.safew_capture_all_apps,
    )
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)

    async def handle(notification: DesktopNotification) -> None:
        message = normalizer.normalize(notification)
        if message is None:
            logger.info(
                "desktop_notification_ignored",
                app_name=notification.app_name,
                summary=notification.summary,
            )
            return
        while not stop_event.is_set():
            try:
                await bus.publish_incoming("safew", message)
                return
            except Exception:
                logger.exception("safew_event_publish_failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=2)

    logger.info("safew_receiver_starting")
    heartbeat = asyncio.create_task(
        bus.heartbeat_loop(
            "safew-receiver",
            stop_event,
            health_probe=_safew_client_running,
        ),
        name="heartbeat",
    )
    try:
        await serve_notifications(handle, stop_event)
    finally:
        stop_event.set()
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await bus.close()
        logger.info("safew_receiver_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
