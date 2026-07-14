"""aiogram Dispatcher factory (polling today, webhook-ready)."""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot.handlers import setup_routers
from app.bot.middlewares import AdminOnlyMiddleware
from app.config import Settings


def create_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(
    settings: Settings,
    *,
    message_service: Any,
    channel_service: Any,
    listener: Any = None,
) -> Dispatcher:
    dp = Dispatcher()
    dp["message_service"] = message_service
    dp["channel_service"] = channel_service
    dp["listener"] = listener
    dp.message.middleware(AdminOnlyMiddleware(settings))
    dp.include_router(setup_routers())
    return dp
