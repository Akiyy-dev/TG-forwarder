"""Web API and static admin frontend process."""

from __future__ import annotations

import asyncio

import uvicorn

from app.api.app import create_api_app
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.session import dispose_engine, init_db
from app.entrypoints.common import UnavailablePublisher
from app.logging import get_logger, setup_logging
from app.messaging.redis_streams import RedisStreamBus
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from app.utils.files import ensure_dir

logger = get_logger(__name__)


async def run() -> None:
    settings = Settings(app_role="web")
    setup_logging(settings.log_level, json_logs=settings.app_env != "development")
    ensure_dir(settings.download_dir)
    session_factory = await init_db(settings.database_url)
    channel_service = ChannelService(settings, session_factory)
    await channel_service.load_from_db()
    auth_service = AuthService(settings, session_factory)
    await auth_service.ensure_bootstrap_admin()
    media_service = MediaService(
        settings.download_dir,
        max_size_bytes=settings.max_download_size_bytes,
        ttl_minutes=settings.temp_file_ttl_minutes,
    )
    unavailable = UnavailablePublisher()
    message_service = MessageService(
        settings,
        session_factory,
        channel_service,
        unavailable,
        media_service,
    )
    bus = RedisStreamBus(settings, consumer_name="web")
    ctx = AppContext(
        settings=settings,
        session_factory=session_factory,
        channel_service=channel_service,
        media_service=media_service,
        message_service=message_service,
        publisher=unavailable,
        auth_service=auth_service,
        command_bus=bus,
    )
    api_app = create_api_app(ctx)
    server = uvicorn.Server(
        uvicorn.Config(
            api_app,
            host=settings.web_host,
            port=settings.web_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
    )
    logger.info("web_started", host=settings.web_host, port=settings.web_port)
    try:
        await server.serve()
    finally:
        await bus.close()
        await dispose_engine()
        logger.info("web_stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
