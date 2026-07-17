"""Telethon user-account receiver that writes normalized events to Redis."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.session import dispose_engine, init_engine
from app.entrypoints.common import install_shutdown_handlers
from app.listeners.telegram_listener import TelegramListener
from app.logging import get_logger, setup_logging
from app.messaging.redis_streams import RedisStreamBus
from app.schemas.message import NormalizedMessage
from app.services.media_service import MediaService
from app.services.telegram_source_registry import (
    TelegramSourceSnapshot,
    load_telegram_source_snapshot,
    telegram_source_selection_changed,
)
from app.utils.files import ensure_dir

logger = get_logger(__name__)

_DATABASE_RETRY_SECONDS = 5.0
_SOURCE_REFRESH_SECONDS = 5.0


async def _wait_for_stop(stop_event: asyncio.Event, delay_seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay_seconds)
    except TimeoutError:
        return False
    return True


async def _wait_for_initial_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    stop_event: asyncio.Event,
    *,
    retry_seconds: float = _DATABASE_RETRY_SECONDS,
) -> TelegramSourceSnapshot | None:
    """Wait through temporary database failures instead of crash-looping."""

    while not stop_event.is_set():
        try:
            return await load_telegram_source_snapshot(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "telegram_source_db_unavailable",
                exception_type=type(exc).__name__,
                retry_seconds=retry_seconds,
            )
            if await _wait_for_stop(stop_event, retry_seconds):
                return None
    return None


async def _monitor_source_changes(
    session_factory: async_sessionmaker[AsyncSession],
    initial: TelegramSourceSnapshot,
    stop_event: asyncio.Event,
    *,
    refresh_seconds: float = _SOURCE_REFRESH_SECONDS,
) -> None:
    """Return when the receiver's DB subscription changes and needs a restart."""

    while not stop_event.is_set():
        if await _wait_for_stop(stop_event, refresh_seconds):
            return
        try:
            current = await load_telegram_source_snapshot(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "telegram_source_db_poll_failed",
                exception_type=type(exc).__name__,
            )
            continue
        if telegram_source_selection_changed(initial, current):
            logger.info(
                "telegram_source_selection_changed",
                old_source_count=len(initial.enabled_chat_ids),
                new_source_count=len(current.enabled_chat_ids),
            )
            return


async def _publish_incoming_message(
    message: NormalizedMessage,
    media_service: MediaService,
    bus: RedisStreamBus,
    stop_event: asyncio.Event,
) -> None:
    """Materialize once, then retry transport without looping on permanent media errors."""
    materialization_complete = False
    while not stop_event.is_set():
        if not materialization_complete:
            try:
                await media_service.ensure_materialized(message)
                if media_service.media_missing(message):
                    raise FileNotFoundError("Telegram media could not be materialized")
            except (FileNotFoundError, ValueError) as exc:
                message.raw_metadata["media_materialization_error"] = {
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
                logger.error(
                    "telegram_media_materialization_failed_permanently",
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    exception_type=type(exc).__name__,
                )
            except Exception:
                logger.exception("telegram_media_materialization_failed")
                await _wait_for_stop(stop_event, 2)
                continue
            materialization_complete = True

        try:
            await bus.publish_incoming("telegram", message)
            return
        except Exception:
            logger.exception("telegram_event_publish_failed")
            await _wait_for_stop(stop_event, 2)


async def run() -> None:
    settings = Settings(app_role="telegram-receiver")
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    ensure_dir(settings.download_dir)
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    session_factory = init_engine(settings.database_url)
    bus = RedisStreamBus(settings, consumer_name="telegram-receiver")
    listener: TelegramListener | None = None
    tasks: set[asyncio.Task[Any]] = set()
    try:
        snapshot = await _wait_for_initial_snapshot(session_factory, stop_event)
        if snapshot is None:
            return

        source_ids = set(snapshot.enabled_chat_ids)
        source_origin = "database"
        await bus.ping()

        media_service = MediaService(
            settings.download_dir,
            max_size_bytes=settings.max_download_size_bytes,
            ttl_minutes=settings.temp_file_ttl_minutes,
        )

        async def on_message(message: NormalizedMessage) -> None:
            message.raw_metadata["source_backend"] = "telegram"
            message.raw_metadata["source_registry_origin"] = source_origin
            await _publish_incoming_message(message, media_service, bus, stop_event)

        if source_ids:
            listener = TelegramListener(
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash,
                session_path=settings.telegram_session_path,
                source_chat_ids=source_ids,
                on_message=on_message,
                album_wait_seconds=settings.album_wait_seconds,
                album_max_wait_seconds=settings.album_max_wait_seconds,
            )
            media_service.downloader = listener
            await listener.start()
            tasks.add(
                asyncio.create_task(listener.run_until_disconnected(), name="telegram_listener")
            )
        else:
            logger.info("telegram_receiver_idle_no_sources", source_origin=source_origin)

        tasks.update(
            {
                asyncio.create_task(
                    bus.heartbeat_loop("telegram-receiver", stop_event), name="heartbeat"
                ),
                asyncio.create_task(
                    _monitor_source_changes(session_factory, snapshot, stop_event),
                    name="source_selection_monitor",
                ),
                asyncio.create_task(stop_event.wait(), name="shutdown"),
            }
        )
        logger.info(
            "telegram_receiver_started",
            source_count=len(source_ids),
            source_origin=source_origin,
        )
        _done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        if listener is not None:
            await listener.stop()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bus.close()
        await dispose_engine()
        logger.info("telegram_receiver_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
