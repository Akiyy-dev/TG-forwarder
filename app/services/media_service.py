"""Media download and cleanup service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.logging import get_logger
from app.schemas.message import MediaType, NormalizedMessage
from app.utils.files import (
    cleanup_expired_files,
    ensure_dir,
    remove_file,
    safe_join,
    sanitize_filename,
)

logger = get_logger(__name__)


class MediaService:
    def __init__(
        self,
        download_dir: str,
        *,
        max_size_bytes: int,
        ttl_minutes: int,
        downloader: Any | None = None,
    ) -> None:
        self.download_dir = ensure_dir(download_dir)
        self.max_size_bytes = max_size_bytes
        self.ttl_minutes = ttl_minutes
        self.downloader = downloader

    def cleanup_expired(self, *, retain_paths: set[str] | None = None) -> int:
        deleted = cleanup_expired_files(
            self.download_dir,
            self.ttl_minutes,
            retain_paths=retain_paths,
        )
        if deleted:
            logger.info("temp_files_cleaned", count=deleted, retained=len(retain_paths or ()))
        return deleted

    def cleanup_message_files(self, message: NormalizedMessage) -> None:
        for item in message.media_items:
            remove_file(item.local_path)
            item.local_path = None

    @staticmethod
    def _path_ok(path: str | None) -> bool:
        if not path:
            return False
        return Path(path).is_file()

    def media_missing(self, message: NormalizedMessage) -> bool:
        if message.media_type in {MediaType.TEXT, MediaType.UNSUPPORTED, MediaType.STICKER}:
            return False
        items = message.media_items or []
        if not items:
            return True
        return any(not self._path_ok(item.local_path) for item in items)

    async def ensure_materialized(
        self,
        message: NormalizedMessage,
        raw_messages: list[Any] | None = None,
    ) -> NormalizedMessage:
        """Re-download any media items whose local files are missing."""
        if not self.media_missing(message):
            return message
        for item in message.media_items or []:
            if not self._path_ok(item.local_path):
                item.local_path = None
        return await self.materialize(message, raw_messages)

    async def materialize(
        self,
        message: NormalizedMessage,
        raw_messages: list[Any] | None = None,
    ) -> NormalizedMessage:
        """Download media for a normalized message using Telethon downloader."""
        if message.media_type in {MediaType.TEXT, MediaType.UNSUPPORTED, MediaType.STICKER}:
            return message
        if self.downloader is None:
            return message

        if not raw_messages and hasattr(self.downloader, "fetch_messages"):
            ids = message.album_message_ids or [message.source_message_id]
            raw_messages = await self.downloader.fetch_messages(message.source_chat_id, ids)

        raw_by_id: dict[int, Any] = {}
        if raw_messages:
            for raw in raw_messages:
                raw_by_id[int(raw.id)] = raw

        items = list(message.media_items or [])
        if not items and message.media_type not in {
            MediaType.TEXT,
            MediaType.UNSUPPORTED,
            MediaType.STICKER,
            MediaType.ALBUM,
        }:
            from app.schemas.message import MediaItem

            items = [
                MediaItem(
                    media_type=message.media_type,
                    original_filename=message.original_filename,
                    mime_type=message.mime_type,
                    file_size=message.file_size,
                    source_message_id=message.source_message_id,
                )
            ]
            message.media_items = items

        for item in items:
            if self._path_ok(item.local_path):
                continue
            if item.file_size and item.file_size > self.max_size_bytes:
                msg = f"file too large: {item.file_size}"
                raise ValueError(msg)

            mid = item.source_message_id or message.source_message_id
            fallback_name = f"{message.source_chat_id}_{mid}_{item.order}"
            filename = sanitize_filename(item.original_filename or fallback_name)
            dest = safe_join(self.download_dir, filename)
            # Avoid collisions
            if dest.exists():
                dest = safe_join(
                    self.download_dir,
                    f"{message.source_chat_id}_{message.source_message_id}_{item.order}_{filename}",
                )

            raw = raw_by_id.get(item.source_message_id or message.source_message_id)
            target = raw if raw is not None else None
            if target is None:
                logger.warning(
                    "media_raw_missing",
                    source_message_id=item.source_message_id,
                )
                continue

            path = await self.downloader.download_media(target, str(dest))
            if path:
                # Verify size after download
                size = Path(path).stat().st_size
                if size > self.max_size_bytes:
                    remove_file(path)
                    msg = f"downloaded file exceeds limit: {size}"
                    raise ValueError(msg)
                item.local_path = path
                item.file_size = size

        # Single-media convenience: also store on top-level fields
        if len(message.media_items) == 1:
            only = message.media_items[0]
            message.original_filename = only.original_filename or message.original_filename
            message.file_size = only.file_size
            message.mime_type = only.mime_type or message.mime_type

        return message
