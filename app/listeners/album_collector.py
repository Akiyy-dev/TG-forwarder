"""Debounced album (media group) collector.

Primary live path should prefer Telethon ``events.Album``. This collector remains
as a safety net for any grouped NewMessage events and unit tests.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.logging import get_logger
from app.schemas.message import MediaItem, MediaType, NormalizedMessage

logger = get_logger(__name__)

AlbumCallback = Callable[[NormalizedMessage], Awaitable[None]]


@dataclass
class _AlbumBucket:
    messages: list[NormalizedMessage] = field(default_factory=list)
    first_seen: float = field(default_factory=lambda: asyncio.get_running_loop().time())
    task: asyncio.Task[None] | None = None


@dataclass
class _RecentAlbum:
    album: NormalizedMessage
    deadline: float


class AlbumCollector:
    """Aggregate messages sharing (source_chat_id, grouped_id) within a debounce window."""

    def __init__(
        self,
        *,
        wait_seconds: float = 2.5,
        max_wait_seconds: float = 20.0,
        late_grace_seconds: float = 5.0,
        on_complete: AlbumCallback | None = None,
    ) -> None:
        self.wait_seconds = wait_seconds
        self.max_wait_seconds = max_wait_seconds
        self.late_grace_seconds = late_grace_seconds
        self.on_complete = on_complete
        self._buckets: dict[tuple[int, int], _AlbumBucket] = {}
        self._recent: dict[tuple[int, int], _RecentAlbum] = {}
        self._lock = asyncio.Lock()

    async def add(self, message: NormalizedMessage) -> NormalizedMessage | None:
        """Add a message. Returns immediately-ready message or None if buffered."""
        if message.grouped_id is None:
            return message

        key = (message.source_chat_id, message.grouped_id)
        cancel_task: asyncio.Task[None] | None = None
        schedule_delay: float | None = None

        async with self._lock:
            self._purge_recent_locked()
            recent = self._recent.get(key)
            if recent is not None:
                existing_ids = set(recent.album.album_message_ids)
                if message.source_message_id not in existing_ids:
                    merged = self.merge([*self._parts_from_album(recent.album), message])
                    recent.album = merged
                    recent.deadline = asyncio.get_running_loop().time() + self.late_grace_seconds
                    logger.warning(
                        "album_late_part_after_flush",
                        source_chat_id=message.source_chat_id,
                        grouped_id=message.grouped_id,
                        count=len(merged.media_items),
                        source_message_id=message.source_message_id,
                    )
                # Already flushed — never open a second incomplete bucket.
                return None

            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _AlbumBucket()
                self._buckets[key] = bucket
            existing_ids = {m.source_message_id for m in bucket.messages}
            if message.source_message_id not in existing_ids:
                bucket.messages.append(message)

            if bucket.task and not bucket.task.done():
                cancel_task = bucket.task
                bucket.task = None

            elapsed = asyncio.get_running_loop().time() - bucket.first_seen
            schedule_delay = min(
                self.wait_seconds,
                max(0.05, self.max_wait_seconds - elapsed),
            )
            if elapsed >= self.max_wait_seconds:
                schedule_delay = 0.0

        if cancel_task is not None:
            cancel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cancel_task

        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or schedule_delay is None:
                return None
            bucket.task = asyncio.create_task(self._flush_after(key, schedule_delay))
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
            album = self.merge(bucket.messages)
            self._recent[key] = _RecentAlbum(
                album=album,
                deadline=asyncio.get_running_loop().time() + self.late_grace_seconds,
            )
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

    def _purge_recent_locked(self) -> None:
        now = asyncio.get_running_loop().time()
        expired = [k for k, v in self._recent.items() if v.deadline <= now]
        for k in expired:
            self._recent.pop(k, None)

    @staticmethod
    def _parts_from_album(album: NormalizedMessage) -> list[NormalizedMessage]:
        """Rebuild pseudo-parts so late merges can re-merge cleanly."""
        parts: list[NormalizedMessage] = []
        for item in album.media_items:
            mid = item.source_message_id or album.source_message_id
            parts.append(
                NormalizedMessage(
                    source_chat_id=album.source_chat_id,
                    source_message_id=mid,
                    source_chat_username=album.source_chat_username,
                    source_chat_title=album.source_chat_title,
                    grouped_id=album.grouped_id,
                    date=album.date,
                    text="",
                    entities=[],
                    media_type=item.media_type,
                    media_items=[
                        MediaItem(
                            media_type=item.media_type,
                            local_path=item.local_path,
                            file_unique_id=item.file_unique_id,
                            original_filename=item.original_filename,
                            mime_type=item.mime_type,
                            file_size=item.file_size,
                            width=item.width,
                            height=item.height,
                            duration=item.duration,
                            source_message_id=mid,
                            order=item.order,
                        )
                    ],
                    target_chat_id=album.target_chat_id,
                )
            )
        if parts and album.text:
            parts = sorted(parts, key=lambda p: p.source_message_id)
            parts[0].text = album.text
            parts[0].entities = list(album.entities)
        return parts

    @staticmethod
    def merge(messages: list[NormalizedMessage]) -> NormalizedMessage:
        ordered = sorted(messages, key=lambda m: m.source_message_id)
        primary = ordered[0]
        media_items: list[MediaItem] = []
        album_ids: list[int] = []
        caption = ""
        entities: list[Any] = []
        for idx, msg in enumerate(ordered):
            album_ids.append(msg.source_message_id)
            if msg.text and not caption:
                caption = msg.text
                entities = list(msg.entities)
            if msg.media_items:
                for item in msg.media_items:
                    media_items.append(
                        MediaItem(
                            media_type=item.media_type,
                            local_path=item.local_path,
                            file_unique_id=item.file_unique_id,
                            original_filename=item.original_filename,
                            mime_type=item.mime_type,
                            file_size=item.file_size,
                            width=item.width,
                            height=item.height,
                            duration=item.duration,
                            source_message_id=msg.source_message_id,
                            order=idx,
                        )
                    )
            elif msg.media_type not in {MediaType.TEXT, MediaType.UNSUPPORTED}:
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
