"""Route outbound messages to Telegram or SafeW targets."""

from __future__ import annotations

from app.publishers.safew_publisher import SafeWPublisher
from app.publishers.telegram_publisher import TelegramPublisher
from app.schemas.channel import TargetBackend, TargetRoute
from app.schemas.message import NormalizedMessage


class OutboundPublisher:
    def __init__(
        self,
        telegram: TelegramPublisher,
        safew: SafeWPublisher,
    ) -> None:
        self.telegram = telegram
        self.safew = safew
        # Compatibility for existing API/status code that retrieves the bot
        # from the active publisher.
        self.bot = telegram.bot

    async def publish_target(self, message: NormalizedMessage, target: TargetRoute) -> list[int]:
        if target.target_backend == TargetBackend.SAFEW:
            return await self.safew.publish(message, target.chat_id)
        return await self.telegram.publish(message, target.chat_id)

    async def publish(self, message: NormalizedMessage, target_chat_id: int) -> list[int]:
        """Legacy Telegram-only call retained for older integrations and tests."""
        return await self.telegram.publish(message, target_chat_id)

    async def close(self) -> None:
        await self.safew.close()
