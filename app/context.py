"""Shared application context for workers, bot, and web API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.rate_limit import SlidingWindowRateLimiter
from app.auth.service import AuthService
from app.config import Settings
from app.listeners.telegram_listener import TelegramListener
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService


@dataclass
class AppContext:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    channel_service: ChannelService
    media_service: MediaService
    message_service: MessageService
    publisher: Any
    auth_service: AuthService
    listener: TelegramListener | None = None
    bot: Bot | None = None
    dispatcher: Dispatcher | None = None
    command_bus: Any | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    login_limiter: SlidingWindowRateLimiter | None = None

    def __post_init__(self) -> None:
        if self.login_limiter is None:
            self.login_limiter = SlidingWindowRateLimiter(
                limit=self.settings.web_login_rate_limit,
                window_seconds=self.settings.web_login_rate_window_seconds,
            )
