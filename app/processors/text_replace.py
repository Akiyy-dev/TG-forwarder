"""Text replacement processor."""

from __future__ import annotations

from app.schemas.message import NormalizedMessage, ProcessingContext, ProcessResult
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, truncate_text


class TextReplaceProcessor:
    name = "text_replace"

    def __init__(
        self,
        replacements: list[tuple[str, str]] | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.replacements = replacements or []
        self.enabled = enabled

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled or not self.replacements:
            return ProcessResult.cont(message, skipped=True)

        text = message.text
        for old, new in self.replacements:
            if old:
                text = text.replace(old, new)

        # Entities become unreliable after arbitrary replaces; clear them.
        if text != message.text:
            message.text = text
            message.entities = []

        limit = (
            TELEGRAM_TEXT_LIMIT if message.media_type.value == "text" else TELEGRAM_CAPTION_LIMIT
        )
        message.text = truncate_text(message.text, limit)
        return ProcessResult.cont(message)
