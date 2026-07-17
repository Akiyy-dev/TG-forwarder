"""Application entrypoint: wire listener, workers, bot polling, and web API."""

from __future__ import annotations

import asyncio
import signal
from typing import Any

import uvicorn
from aiogram import Dispatcher

from app.api.app import create_api_app
from app.auth.service import AuthService
from app.bot.dispatcher import create_bot, create_dispatcher
from app.config import Settings, get_settings
from app.context import AppContext
from app.database.session import dispose_engine, init_db
from app.listeners.telegram_listener import TelegramListener
from app.logging import get_logger, setup_logging
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.auto_approve import ReviewAutoApproveService
from app.review.publish import ReviewPublishService
from app.review.service import ReviewService
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from app.source_backends import is_safew_chat_id
from app.utils.files import ensure_dir

logger = get_logger(__name__)


def _create_bot_dispatcher(
    settings: Settings,
    *,
    message_service: MessageService,
    channel_service: ChannelService,
    listener: TelegramListener,
) -> Dispatcher | None:
    if not settings.bot_polling_enabled:
        logger.info("bot_polling_disabled")
        return None
    return create_dispatcher(
        settings,
        message_service=message_service,
        channel_service=channel_service,
        listener=listener,
    )


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

    from app.services.rules_service import RulesService

    await channel_service.load_from_db()

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
    for chat_id in channel_service.enabled_chat_ids:
        if is_safew_chat_id(chat_id):
            continue
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
    )
    media_service.downloader = listener

    # Protect media still referenced by open review tasks from TTL cleanup.
    retain_paths = await ReviewService(session_factory).active_media_paths()
    media_service.cleanup_expired(retain_paths=retain_paths)

    dp = _create_bot_dispatcher(
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

    review_service = ReviewService(session_factory)
    publish_service = ReviewPublishService(
        session_factory,
        review_service,
        publisher,
        media_service,
        channel_service,
    )
    auto_approve = ReviewAutoApproveService(
        session_factory,
        publish_service,
        is_paused=message_service.refresh_paused,
    )
    auto_approve.start()

    polling_task: asyncio.Task[Any] | None = None
    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(listener.run_until_disconnected(), name="listener"),
        asyncio.create_task(stop_event.wait(), name="stop_waiter"),
    }
    if dp is not None:
        polling_task = asyncio.create_task(dp.start_polling(bot), name="bot_polling")
        tasks.add(polling_task)

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

    logger.info(
        "app_started",
        app_env=settings.app_env,
        web_enabled=settings.web_enabled,
        bot_polling_enabled=settings.bot_polling_enabled,
    )

    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

    logger.info("app_stopping")
    stop_event.set()
    if uvicorn_server is not None:
        uvicorn_server.should_exit = True
    await auto_approve.stop()
    await listener.stop()
    await message_service.stop_workers()
    if dp is not None and polling_task is not None and not polling_task.done():
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
