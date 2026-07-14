"""Debounced album (media group) collector."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.logging import get_logger
from app.schemas.message import MediaType, NormalizedMessage

logger = get_logger(__name__)

AlbumCallback = Callable[[NormalizedMessage], Awaitable[None]]


@dataclass
class _AlbumBucket:
    messages: list[NormalizedMessage] = field(default_factory=list)
    first_seen: float = field(default_factory=lambda: asyncio.get_running_loop().time())
    task: asyncio.Task[None] | None = None


class AlbumCollector:
    """Aggregate messages sharing (source_chat_id, grouped_id) within a debounce window."""

    def __init__(
        self,
        *,
        wait_seconds: float = 1.5,
        max_wait_seconds: float = 8.0,
        on_complete: AlbumCallback | None = None,
    ) -> None:
        self.wait_seconds = wait_seconds
        self.max_wait_seconds = max_wait_seconds
        self.on_complete = on_complete
        self._buckets: dict[tuple[int, int], _AlbumBucket] = {}
        self._lock = asyncio.Lock()

    async def add(self, message: NormalizedMessage) -> NormalizedMessage | None:
        """Add a message. Returns immediately-ready message or None if buffered."""
        if message.grouped_id is None:
            return message

        key = (message.source_chat_id, message.grouped_id)
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _AlbumBucket()
                self._buckets[key] = bucket
            # Deduplicate by source_message_id
            existing_ids = {m.source_message_id for m in bucket.messages}
            if message.source_message_id not in existing_ids:
                bucket.messages.append(message)

            if bucket.task and not bucket.task.done():
                bucket.task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await bucket.task

            elapsed = asyncio.get_running_loop().time() - bucket.first_seen
            delay = min(self.wait_seconds, max(0.05, self.max_wait_seconds - elapsed))
            if elapsed >= self.max_wait_seconds:
                delay = 0.0
            bucket.task = asyncio.create_task(self._flush_after(key, delay))
        return None

    async def _flush_after(self, key: tuple[int, int], delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self.flush_key(key)
        except asyncio.CancelledError:
            raise

    async def flush_key(self, key: tuple[int, int]) -> NormalizedMessage | None:
        async with self._lock:
            bucket = self._buckets.pop(key, None)
        if bucket is None or not bucket.messages:
            return None
        album = self._merge(bucket.messages)
        logger.info(
            "album_flushed",
            source_chat_id=album.source_chat_id,
            grouped_id=album.grouped_id,
            count=len(album.media_items),
        )
        if self.on_complete is not None:
            await self.on_complete(album)
        return album

    async def flush_all(self) -> list[NormalizedMessage]:
        async with self._lock:
            keys = list(self._buckets.keys())
        results: list[NormalizedMessage] = []
        for key in keys:
            album = await self.flush_key(key)
            if album is not None:
                results.append(album)
        return results

    @staticmethod
    def _merge(messages: list[NormalizedMessage]) -> NormalizedMessage:
        ordered = sorted(messages, key=lambda m: m.source_message_id)
        primary = ordered[0]
        media_items = []
        album_ids: list[int] = []
        caption = ""
        entities = []
        for idx, msg in enumerate(ordered):
            album_ids.append(msg.source_message_id)
            if msg.text and not caption:
                caption = msg.text
                entities = list(msg.entities)
            if msg.media_items:
                for item in msg.media_items:
                    item.order = idx
                    item.source_message_id = msg.source_message_id
                    media_items.append(item)
            elif msg.media_type not in {MediaType.TEXT, MediaType.UNSUPPORTED}:
                from app.schemas.message import MediaItem

                media_items.append(
                    MediaItem(
                        media_type=msg.media_type,
                        local_path=None,
                        file_unique_id=(msg.raw_metadata or {}).get("file_unique_id"),
                        original_filename=msg.original_filename,
                        mime_type=msg.mime_type,
                        file_size=msg.file_size,
                        source_message_id=msg.source_message_id,
                        order=idx,
                    )
                )

        return NormalizedMessage(
            source_chat_id=primary.source_chat_id,
            source_message_id=primary.source_message_id,
            source_chat_username=primary.source_chat_username,
            source_chat_title=primary.source_chat_title,
            grouped_id=primary.grouped_id,
            date=primary.date or datetime.now(UTC),
            edit_date=primary.edit_date,
            text=caption,
            entities=entities,
            media_type=MediaType.ALBUM,
            media_items=media_items,
            reply_to_message_id=primary.reply_to_message_id,
            forward_info=primary.forward_info,
            raw_metadata={"album_size": len(ordered)},
            target_chat_id=primary.target_chat_id,
            album_message_ids=album_ids,
        )
