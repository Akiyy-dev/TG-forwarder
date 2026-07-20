"""Processing workers, review publisher, Telegram publisher, and admin bot."""

from __future__ import annotations

import asyncio
from typing import Any

from aiogram import Bot, Dispatcher

from app.bot.dispatcher import create_bot, create_dispatcher
from app.config import Settings
from app.database.session import dispose_engine, init_db
from app.entrypoints.common import install_shutdown_handlers
from app.logging import get_logger, setup_logging
from app.messaging.models import CommandEvent, IncomingMessageEvent
from app.messaging.redis_streams import RedisStreamBus
from app.publishers.outbound_publisher import OutboundPublisher
from app.publishers.safew_publisher import SafeWPublisher
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.auto_approve import ReviewAutoApproveService
from app.review.publish import ReviewPublishService
from app.review.service import ReviewService
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from app.services.rules_service import RulesService
from app.utils.files import ensure_dir

logger = get_logger(__name__)


async def _accept_or_register_source(
    event: IncomingMessageEvent,
    settings: Settings,
    channel_service: ChannelService,
) -> bool:
    """Accept Web-managed Telegram sources and auto-register SafeW conversations."""

    message = event.message
    if message.source_chat_id in channel_service.configured_chat_ids:
        return True

    if event.backend != "safew":
        logger.warning(
            "unknown_telegram_source_ignored",
            source_chat_id=message.source_chat_id,
        )
        return False
    if not settings.safew_auto_register_sources:
        logger.warning("unknown_safew_source_ignored", source_chat_id=message.source_chat_id)
        return False

    await channel_service.sync_from_config_rows(
        [
            {
                "chat_id": message.source_chat_id,
                "username": message.source_chat_username,
                "title": message.source_chat_title,
                "enabled": True,
                "publish_mode": "review",
            }
        ]
    )
    return True


def _start_bot_polling(
    settings: Settings,
    *,
    bot: Bot,
    message_service: MessageService,
    channel_service: ChannelService,
) -> tuple[Dispatcher | None, asyncio.Task[Any] | None]:
    if not settings.bot_polling_enabled:
        logger.info("bot_polling_disabled")
        return None, None

    dispatcher = create_dispatcher(
        settings,
        message_service=message_service,
        channel_service=channel_service,
    )
    task = asyncio.create_task(dispatcher.start_polling(bot), name="bot_polling")
    return dispatcher, task


async def run() -> None:
    settings = Settings(app_role="sender")
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    ensure_dir(settings.download_dir)
    session_factory = await init_db(settings.database_url)
    channel_service = ChannelService(settings, session_factory)
    await channel_service.load_from_db()

    rules_synced = await RulesService(session_factory).sync_from_file(settings.rules_config_path)
    if rules_synced:
        logger.info("rules_seed_applied", count=rules_synced)

    bot = create_bot(settings.bot_token)
    telegram_publisher = TelegramPublisher(
        bot,
        max_retries=settings.max_retries,
        base_delay=settings.retry_base_delay_seconds,
    )
    safew_publisher = SafeWPublisher(
        settings.safew_bot_token,
        api_base_url=settings.safew_bot_api_base_url,
        timeout_seconds=settings.safew_bot_timeout_seconds,
        max_retries=settings.max_retries,
        base_delay=settings.retry_base_delay_seconds,
    )
    publisher = OutboundPublisher(telegram_publisher, safew_publisher)
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
    review_service = ReviewService(session_factory)
    retain_paths = await review_service.active_media_paths()
    media_service.cleanup_expired(retain_paths=retain_paths)

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
    bus = RedisStreamBus(settings)
    await bus.ping()
    stop_event = asyncio.Event()
    install_shutdown_handlers(stop_event)
    last_channel_refresh = 0.0

    async def handle_incoming(event: IncomingMessageEvent) -> None:
        nonlocal last_channel_refresh
        now = asyncio.get_running_loop().time()
        if now - last_channel_refresh >= 5:
            await channel_service.load_from_db()
            last_channel_refresh = now
        await message_service.refresh_paused()
        message = event.message
        message.raw_metadata["source_backend"] = event.backend
        if not await _accept_or_register_source(event, settings, channel_service):
            return
        if not channel_service.is_enabled(message.source_chat_id):
            logger.info("disabled_source_ignored", source_chat_id=message.source_chat_id)
            return
        await message_service.process_durable(message)

    async def handle_command(event: CommandEvent) -> None:
        if event.kind == "publish_review":
            payload = event.payload
            result = await publish_service.publish_task(
                int(payload["task_id"]),
                expected_revision=int(payload["expected_revision"]),
                user_id=int(payload["user_id"]) if payload.get("user_id") is not None else None,
            )
            logger.info(
                "publish_review_command_complete",
                command_id=event.event_id,
                result=result,
            )
            return
        if event.kind == "recover_pending":
            await message_service.refresh_paused()
            await message_service.recover_pending()
            return
        if event.kind == "retry_failed":
            await message_service.retry_failed(limit=int(event.payload.get("limit", 50)))
            return
        if event.kind == "check_target_permissions":
            result = await channel_service.check_target_permissions(
                int(event.payload["target_id"]), bot, safew_publisher
            )
            logger.info(
                "target_permission_command_complete",
                command_id=event.event_id,
                result=result,
            )
            return
        if event.kind == "send_target_test_message":
            result = await channel_service.send_target_test_message(
                int(event.payload["target_id"]),
                bot,
                str(event.payload.get("text") or "TG-forwarder test message"),
                safew_publisher,
            )
            logger.info(
                "target_test_command_complete",
                command_id=event.event_id,
                result=result,
            )
            return
        logger.warning("unknown_command_ignored", kind=event.kind)

    await message_service.start_workers()
    await message_service.recover_pending()
    auto_approve.start()
    dispatcher, polling_task = _start_bot_polling(
        settings,
        bot=bot,
        message_service=message_service,
        channel_service=channel_service,
    )
    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(bus.consume_incoming(handle_incoming, stop_event), name="incoming"),
        asyncio.create_task(bus.consume_commands(handle_command, stop_event), name="commands"),
        asyncio.create_task(bus.heartbeat_loop("sender", stop_event), name="heartbeat"),
        asyncio.create_task(stop_event.wait(), name="shutdown"),
    }
    if polling_task is not None:
        tasks.add(polling_task)
    logger.info("sender_started", bot_polling_enabled=settings.bot_polling_enabled)
    try:
        _done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop_event.set()
        await auto_approve.stop()
        await message_service.stop_workers()
        await publisher.close()
        if dispatcher is not None and polling_task is not None and not polling_task.done():
            await dispatcher.stop_polling()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await bot.session.close()
        await bus.close()
        await dispose_engine()
        logger.info("sender_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
