"""Bot publisher with idempotent publish semantics."""

from __future__ import annotations

from aiogram import Bot

from app.logging import get_logger
from app.publishers.media_sender import MediaSender, route_media_type
from app.schemas.message import MediaType, NormalizedMessage
from app.services.retry_service import (
    classify_exception,
    exception_summary,
    should_retry,
    sleep_for_retry,
)

logger = get_logger(__name__)


class TelegramPublisher:
    def __init__(
        self,
        bot: Bot,
        *,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ) -> None:
        self.bot = bot
        self.sender = MediaSender(bot)
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def publish(self, message: NormalizedMessage, target_chat_id: int) -> list[int]:
        if message.media_type in {MediaType.STICKER, MediaType.UNSUPPORTED}:
            msg = f"unsupported media type: {message.media_type.value}"
            raise ValueError(msg)

        method = route_media_type(message.media_type)
        logger.info(
            "publish_start",
            source_chat_id=message.source_chat_id,
            source_message_id=message.source_message_id,
            grouped_id=message.grouped_id,
            target_chat_id=target_chat_id,
            method=method,
        )

        attempt = 0
        last_exc: BaseException | None = None
        while attempt < self.max_retries:
            attempt += 1
            try:
                ids = await self.sender.send(target_chat_id, message)
                logger.info(
                    "publish_success",
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                    target_chat_id=target_chat_id,
                    target_message_ids=ids,
                    retry_count=attempt - 1,
                )
                return ids
            except Exception as exc:
                last_exc = exc
                summary = exception_summary(exc)
                logger.warning(
                    "publish_error",
                    exception_type=summary["exception_type"],
                    retry_count=attempt,
                    status=summary["retry_class"],
                    target_chat_id=target_chat_id,
                    source_chat_id=message.source_chat_id,
                    source_message_id=message.source_message_id,
                )
                if not should_retry(exc, attempt, self.max_retries):
                    raise
                await sleep_for_retry(exc, attempt, self.base_delay)
                if classify_exception(exc).value == "fatal":
                    raise

        assert last_exc is not None
        raise last_exc
