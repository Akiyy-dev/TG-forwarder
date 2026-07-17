"""Telethon-based source channel listener."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Channel, Message

from app.listeners.album_collector import AlbumCollector
from app.listeners.normalizer import normalize_telethon_message
from app.logging import get_logger
from app.schemas.message import NormalizedMessage

logger = get_logger(__name__)

MessageHandler = Callable[[NormalizedMessage], Awaitable[object]]


class TelegramListener:
    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_path: str,
        source_chat_ids: Iterable[int],
        on_message: MessageHandler,
        album_wait_seconds: float = 2.5,
        album_max_wait_seconds: float = 20.0,
        target_channel_id: int | None = None,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_path = session_path
        self.source_chat_ids = set(source_chat_ids)
        self.on_message = on_message
        self.target_channel_id = target_channel_id
        self.client = TelegramClient(session_path, api_id, api_hash)
        self.album_collector = AlbumCollector(
            wait_seconds=album_wait_seconds,
            max_wait_seconds=album_max_wait_seconds,
            on_complete=self._emit,
        )
        self._running = False
        self._connected = False
        self._last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self.client.is_connected()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def _emit(self, message: NormalizedMessage) -> None:
        await self.on_message(message)

    async def start(self) -> None:
        await self.client.connect()
        if not await self.client.is_user_authorized():
            msg = "Telethon session is not authorized; run scripts/create_session.py first"
            raise RuntimeError(msg)

        self._running = True
        self._connected = True

        if not self.source_chat_ids:
            logger.warning("listener_idle_no_sources")
            return

        chats = list(self.source_chat_ids)

        @self.client.on(events.Album(chats=chats))
        async def _album_handler(event: events.Album.Event) -> None:
            await self._handle_album(event)

        @self.client.on(events.NewMessage(chats=chats))
        async def _message_handler(event: events.NewMessage.Event) -> None:
            await self._handle_event(event)

        logger.info(
            "listener_started",
            source_count=len(self.source_chat_ids),
        )

    async def run_until_disconnected(self) -> None:
        try:
            await self.client.run_until_disconnected()
        except Exception as exc:
            self._last_error = type(exc).__name__
            logger.exception("listener_disconnected")
            raise
        finally:
            self._connected = False

    async def stop(self) -> None:
        self._running = False
        try:
            await self.album_collector.flush_all()
        except Exception:
            logger.exception("album_flush_on_stop_failed")
        if self.client.is_connected():
            await self.client.disconnect()
        self._connected = False
        logger.info("listener_stopped")

    def _chat_allowed(self, chat: Channel) -> tuple[bool, int, int]:
        chat_id = int(chat.id)
        full_id = int(f"-100{chat_id}") if chat_id > 0 else chat_id
        allowed = self.source_chat_ids
        ok = chat_id in allowed or full_id in allowed
        return ok, chat_id, full_id

    async def _normalize_message(
        self,
        message: Message,
        chat: Channel,
        *,
        full_id: int,
    ) -> NormalizedMessage:
        normalized = normalize_telethon_message(
            message,
            chat_username=getattr(chat, "username", None),
            chat_title=getattr(chat, "title", None),
            target_chat_id=self.target_channel_id,
        )
        if full_id < 0:
            normalized.source_chat_id = full_id
        return normalized

    async def _handle_album(self, event: events.Album.Event) -> None:
        """Telethon delivers the full media group once — preferred album path."""
        try:
            chat = await event.get_chat()
            if not isinstance(chat, Channel) or not getattr(chat, "broadcast", False):
                return
            ok, _chat_id, full_id = self._chat_allowed(chat)
            if not ok:
                return

            parts: list[NormalizedMessage] = []
            for message in event.messages:
                if not isinstance(message, Message):
                    continue
                parts.append(await self._normalize_message(message, chat, full_id=full_id))
            if not parts:
                return

            album = AlbumCollector.merge(parts)
            logger.info(
                "album_event_received",
                source_chat_id=album.source_chat_id,
                grouped_id=album.grouped_id,
                count=len(album.media_items),
            )
            await self._emit(album)
        except FloodWaitError as exc:
            self._last_error = "FloodWaitError"
            logger.warning(
                "listener_flood_wait",
                exception_type="FloodWaitError",
                seconds=exc.seconds,
            )
            await asyncio.sleep(exc.seconds + 1)
        except RPCError as exc:
            self._last_error = type(exc).__name__
            logger.exception(
                "listener_rpc_error",
                exception_type=type(exc).__name__,
            )
        except Exception as exc:
            self._last_error = type(exc).__name__
            logger.exception(
                "listener_album_error",
                exception_type=type(exc).__name__,
            )

    async def _handle_event(self, event: events.NewMessage.Event) -> None:
        try:
            message = event.message
            if not isinstance(message, Message):
                return
            # Media-group parts are owned by events.Album to avoid incomplete flushes.
            if getattr(message, "grouped_id", None) is not None:
                return

            chat = await event.get_chat()
            if not isinstance(chat, Channel) or not getattr(chat, "broadcast", False):
                return
            ok, _chat_id, full_id = self._chat_allowed(chat)
            if not ok:
                return

            normalized = await self._normalize_message(message, chat, full_id=full_id)
            ready = await self.album_collector.add(normalized)
            if ready is not None:
                await self._emit(ready)
        except FloodWaitError as exc:
            self._last_error = "FloodWaitError"
            logger.warning(
                "listener_flood_wait",
                exception_type="FloodWaitError",
                seconds=exc.seconds,
            )
            await asyncio.sleep(exc.seconds + 1)
        except RPCError as exc:
            self._last_error = type(exc).__name__
            logger.exception(
                "listener_rpc_error",
                exception_type=type(exc).__name__,
            )
        except Exception as exc:
            self._last_error = type(exc).__name__
            logger.exception(
                "listener_message_error",
                exception_type=type(exc).__name__,
            )

    async def fetch_messages(self, chat_id: int, message_ids: list[int]) -> list[Any]:
        """Re-fetch source messages by id for media download."""
        if not message_ids:
            return []
        result = await self.client.get_messages(chat_id, ids=message_ids)
        if result is None:
            return []
        if isinstance(result, list):
            return [m for m in result if m is not None]
        return [result]

    async def download_media(self, message_ref: Any, file_path: str) -> str | None:
        try:
            path = await self.client.download_media(message_ref, file=file_path)
            return str(path) if path else None
        except FloodWaitError as exc:
            logger.warning(
                "download_flood_wait",
                seconds=exc.seconds,
            )
            await asyncio.sleep(exc.seconds + 1)
            path = await self.client.download_media(message_ref, file=file_path)
            return str(path) if path else None
