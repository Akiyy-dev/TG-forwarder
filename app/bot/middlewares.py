"""Bot middlewares."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.config import Settings


class AdminOnlyMiddleware(BaseMiddleware):
    """Allow admin commands; non-admins get a generic denial for admin intents."""

    def __init__(self, settings: Settings, *, enforce: bool = True) -> None:
        self.settings = settings
        self.enforce = enforce

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["is_admin"] = False
        if isinstance(event, Message) and event.from_user is not None:
            data["is_admin"] = self.settings.is_admin(event.from_user.id)
        return await handler(event, data)


def require_admin(is_admin: bool) -> str | None:
    """Return denial text for non-admins, else None."""
    if is_admin:
        return None
    return "You are not allowed to use this bot."
