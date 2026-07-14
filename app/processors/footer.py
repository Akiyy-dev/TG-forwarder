"""Footer append processor (once per message/album)."""

from __future__ import annotations

from app.schemas.message import MediaType, NormalizedMessage, ProcessingContext, ProcessResult
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, truncate_text


class FooterProcessor:
    name = "footer"

    def __init__(self, footer: str = "", *, enabled: bool = True) -> None:
        self.footer = (footer or "").strip()
        self.enabled = enabled

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled or not self.footer:
            return ProcessResult.cont(message, skipped=True)

        # Album caption is single; footer applied once here.
        body = message.text.strip()
        limit = (
            TELEGRAM_TEXT_LIMIT if message.media_type == MediaType.TEXT else TELEGRAM_CAPTION_LIMIT
        )
        message.text = truncate_text(body, limit, footer=self.footer)
        return ProcessResult.cont(message)
