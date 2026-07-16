"""Telethon user-account receiver that writes normalized events to Redis."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from app.config import Settings
from app.config_files import load_channels_config
from app.entrypoints.common import install_shutdown_handlers
from app.listeners.telegram_listener import TelegramListener
from app.logging import get_logger, setup_logging
from app.messaging.redis_streams import RedisStreamBus
from app.schemas.message import NormalizedMessage
from app.services.media_service import MediaService
from app.services.source_resolver import (
    resolve_channel_config_entries,
    resolve_source_channels,
)
from app.utils.files import ensure_dir

logger = get_logger(__name__)


async def run() -> None:
    settings = Settings(app_role="telegram-receiver")
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    ensure_dir(settings.download_dir)
    bus = RedisStreamBus(settings, consumer_name="telegram-receiver")
    await bus.ping()

    entries = load_channels_config(settings.channels_config_path)
    if entries:
        rows = await resolve_channel_config_entries(settings, entries)
        source_ids = {int(row["chat_id"]) for row in rows if row.get("enabled") is not False}
    else:
        resolved = await resolve_source_channels(settings)
        source_ids = {row[0] for row in resolved}

    media_service = MediaService(
        settings.download_dir,
        max_size_bytes=settings.max_download_size_bytes,
        ttl_minutes=settings.temp_file_ttl_minutes,
    )
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    listener: TelegramListener

    async def on_message(message: NormalizedMessage) -> None:
        message.raw_metadata["source_backend"] = "telegram"
        while not stop_event.is_set():
            try:
                await media_service.ensure_materialized(message)
                if media_service.media_missing(message):
                    raise FileNotFoundError("Telegram media could not be materialized")
                await bus.publish_incoming("telegram", message)
                return
            except Exception:
                logger.exception("telegram_event_publish_failed")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), timeout=2)

    listener = TelegramListener(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_path=settings.telegram_session_path,
        source_chat_ids=source_ids,
        on_message=on_message,
        album_wait_seconds=settings.album_wait_seconds,
        album_max_wait_seconds=settings.album_max_wait_seconds,
        target_channel_id=None,
    )
    media_service.downloader = listener
    await listener.start()
    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(listener.run_until_disconnected(), name="telegram_listener"),
        asyncio.create_task(bus.heartbeat_loop("telegram-receiver", stop_event), name="heartbeat"),
        asyncio.create_task(stop_event.wait(), name="shutdown"),
    }
    logger.info("telegram_receiver_started", source_count=len(source_ids))
    try:
        _done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        await listener.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bus.close()
        logger.info("telegram_receiver_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
