"""Application entrypoint: wire listener, workers, bot polling, and web API."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import uvicorn
from telethon import TelegramClient
from telethon.tl.types import Channel

from app.api.app import create_api_app
from app.auth.service import AuthService
from app.bot.dispatcher import create_bot, create_dispatcher
from app.config import Settings, get_settings
from app.context import AppContext
from app.database.session import dispose_engine, init_db
from app.listeners.telegram_listener import TelegramListener
from app.logging import get_logger, setup_logging
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.service import ReviewService
from app.services.channel_service import ChannelService, parse_channel_ref
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from app.utils.files import ensure_dir

logger = get_logger(__name__)


async def resolve_source_channels(
    settings: Settings,
) -> list[tuple[int, str | None, str | None]]:
    """Resolve SOURCE_CHANNELS refs to chat ids via Telethon."""
    client = TelegramClient(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    resolved: list[tuple[int, str | None, str | None]] = []
    await client.connect()
    try:
        if not await client.is_user_authorized():
            msg = "Session not authorized; run python -m scripts.create_session first"
            raise RuntimeError(msg)
        for ref in settings.source_channels:
            parsed = parse_channel_ref(ref)
            entity = await client.get_entity(parsed)
            chat_id = int(entity.id)
            if isinstance(entity, Channel) and chat_id > 0:
                chat_id = int(f"-100{chat_id}")
            username = getattr(entity, "username", None)
            title = getattr(entity, "title", None)
            resolved.append((chat_id, username, title))
            logger.info(
                "channel_resolved",
                source_chat_id=chat_id,
                username=username,
            )
    finally:
        await client.disconnect()
    return resolved


async def resolve_channel_config_entries(
    settings: Settings,
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve config/channels.yaml entries to chat ids via Telethon when needed."""
    client = TelegramClient(
        settings.telegram_session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )
    resolved: list[dict[str, Any]] = []
    await client.connect()
    try:
        if not await client.is_user_authorized():
            msg = "Session not authorized; run python -m scripts.create_session first"
            raise RuntimeError(msg)
        for entry in entries:
            chat_id = entry.get("chat_id")
            username = entry.get("username")
            title = entry.get("title")
            if chat_id is None:
                ref = username or entry.get("ref")
                if not ref:
                    logger.warning("channel_config_entry_skipped_missing_id")
                    continue
                parsed = parse_channel_ref(str(ref) if str(ref).startswith("@") else f"@{ref}")
                entity = await client.get_entity(parsed)
                chat_id = int(entity.id)
                if isinstance(entity, Channel) and chat_id > 0:
                    chat_id = int(f"-100{chat_id}")
                username = getattr(entity, "username", None) or username
                title = title or getattr(entity, "title", None)
            else:
                chat_id = int(chat_id)
            row = {
                "chat_id": chat_id,
                "username": username,
                "title": title,
                "enabled": entry.get("enabled"),
                "publish_mode": entry.get("publish_mode"),
                "target_chat_id": entry.get("target_chat_id"),
            }
            resolved.append(row)
            logger.info(
                "channel_resolved",
                source_chat_id=chat_id,
                username=username,
            )
    finally:
        await client.disconnect()
    return resolved


async def run_app() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    ensure_dir(settings.download_dir)
    ensure_dir("./data/database")
    ensure_dir("./data/sessions")

    session_factory = await init_db(settings.database_url)
    channel_service = ChannelService(settings, session_factory)
    auth_service = AuthService(settings, session_factory)
    await auth_service.ensure_bootstrap_admin()

    from app.config_files import load_channels_config
    from app.services.rules_service import RulesService

    file_entries = load_channels_config(settings.channels_config_path)
    if file_entries:
        rows = await resolve_channel_config_entries(settings, file_entries)
        await channel_service.sync_from_config_rows(rows)
    else:
        resolved = await resolve_source_channels(settings)
        await channel_service.sync_from_settings(resolved)

    rules_synced = await RulesService(session_factory).sync_from_file(settings.rules_config_path)
    if rules_synced:
        logger.info("rules_seed_applied", count=rules_synced)

    bot = create_bot(settings.bot_token)
    publisher = TelegramPublisher(
        bot,
        max_retries=settings.max_retries,
        base_delay=settings.retry_base_delay_seconds,
    )
    media_service = MediaService(
        settings.download_dir,
        max_size_bytes=settings.max_download_size_bytes,
        ttl_minutes=settings.temp_file_ttl_minutes,
    )

    message_service = MessageService(
        settings,
        session_factory,
        channel_service,
        publisher,
        media_service,
    )

    source_ids: set[int] = set()
    for chat_id, _, _ in resolved:
        source_ids.add(chat_id)
        s = str(chat_id)
        if s.startswith("-100"):
            source_ids.add(int(s[4:]))

    listener = TelegramListener(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_path=settings.telegram_session_path,
        source_chat_ids=source_ids,
        on_message=message_service.enqueue,
        album_wait_seconds=settings.album_wait_seconds,
        album_max_wait_seconds=settings.album_max_wait_seconds,
        target_channel_id=settings.target_channel_id,
    )
    media_service.downloader = listener

    # Protect media still referenced by open review tasks from TTL cleanup.
    retain_paths = await ReviewService(session_factory).active_media_paths()
    media_service.cleanup_expired(retain_paths=retain_paths)

    dp = create_dispatcher(
        settings,
        message_service=message_service,
        channel_service=channel_service,
        listener=listener,
    )

    ctx = AppContext(
        settings=settings,
        session_factory=session_factory,
        channel_service=channel_service,
        media_service=media_service,
        message_service=message_service,
        publisher=publisher,
        auth_service=auth_service,
        listener=listener,
        bot=bot,
        dispatcher=dp,
    )

    stop_event = asyncio.Event()

    def _request_stop(*_args: Any) -> None:
        logger.info("shutdown_signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _request_stop())

    await message_service.start_workers()
    await message_service.recover_pending()
    await listener.start()

    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(dp.start_polling(bot), name="bot_polling"),
        asyncio.create_task(listener.run_until_disconnected(), name="listener"),
        asyncio.create_task(stop_event.wait(), name="stop_waiter"),
    }

    uvicorn_server: uvicorn.Server | None = None
    if settings.web_enabled:
        api_app = create_api_app(ctx)
        config = uvicorn.Config(
            api_app,
            host=settings.web_host,
            port=settings.web_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        uvicorn_server = uvicorn.Server(config)
        tasks.add(asyncio.create_task(uvicorn_server.serve(), name="web_api"))
        logger.info("web_api_starting", host=settings.web_host, port=settings.web_port)

    logger.info("app_started", app_env=settings.app_env, web_enabled=settings.web_enabled)

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    logger.info("app_stopping")
    stop_event.set()
    if uvicorn_server is not None:
        uvicorn_server.should_exit = True
    await listener.stop()
    await message_service.stop_workers()
    await dp.stop_polling()
    for task in pending | done:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await bot.session.close()
    await dispose_engine()
    logger.info("app_stopped")


def main() -> None:
    asyncio.run(run_app())


if __name__ == "__main__":
    main()
