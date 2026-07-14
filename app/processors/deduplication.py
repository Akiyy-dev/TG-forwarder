"""Content-hash based deduplication processor."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.schemas.message import NormalizedMessage, ProcessingContext, ProcessResult
from app.utils.text import content_fingerprint

LookupFn = Callable[[str], Awaitable[bool]]


class DeduplicationProcessor:
    name = "deduplication"

    def __init__(
        self,
        *,
        exists_fn: LookupFn | None = None,
        enabled: bool = True,
    ) -> None:
        self._exists_fn = exists_fn
        self.enabled = enabled

    @staticmethod
    def compute_hash(message: NormalizedMessage) -> str:
        media_keys: list[str] = []
        for item in message.media_items:
            key = item.file_unique_id or item.file_id
            if not key and item.original_filename:
                key = f"{item.original_filename}:{item.file_size or 0}"
            if key:
                media_keys.append(key)
        if not media_keys and message.file_size and message.original_filename:
            media_keys.append(f"{message.original_filename}:{message.file_size}")
        return content_fingerprint(message.text, media_keys=media_keys)

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled:
            return ProcessResult.cont(message, skipped=True)

        digest = self.compute_hash(message)
        context.extra["content_hash"] = digest

        if self._exists_fn is not None and await self._exists_fn(digest):
            return ProcessResult.drop(message, "duplicate_content", content_hash=digest)

        return ProcessResult.cont(message, content_hash=digest)
