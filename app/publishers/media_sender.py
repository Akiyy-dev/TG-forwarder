"""Low-level media send helpers for aiogram."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import (
    FSInputFile,
    InputMediaAnimation,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)

from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.utils.text import TELEGRAM_CAPTION_LIMIT, TELEGRAM_TEXT_LIMIT, truncate_text


def route_media_type(media_type: MediaType) -> str:
    """Return send method name for a media type."""
    mapping = {
        MediaType.TEXT: "send_message",
        MediaType.PHOTO: "send_photo",
        MediaType.VIDEO: "send_video",
        MediaType.DOCUMENT: "send_document",
        MediaType.ANIMATION: "send_animation",
        MediaType.AUDIO: "send_audio",
        MediaType.VOICE: "send_voice",
        MediaType.ALBUM: "send_media_group",
        MediaType.STICKER: "unsupported",
        MediaType.UNSUPPORTED: "unsupported",
    }
    return mapping.get(media_type, "unsupported")


def _input_file(item: MediaItem) -> FSInputFile:
    if not item.local_path or not Path(item.local_path).exists():
        msg = f"media file missing: {item.local_path}"
        raise FileNotFoundError(msg)
    filename = item.original_filename or Path(item.local_path).name
    return FSInputFile(item.local_path, filename=filename)


class MediaSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, message: NormalizedMessage) -> list[int]:
        method = route_media_type(message.media_type)
        if method == "unsupported":
            msg = f"unsupported media type: {message.media_type}"
            raise ValueError(msg)

        text = message.text or ""
        if message.media_type == MediaType.TEXT:
            body = truncate_text(text, TELEGRAM_TEXT_LIMIT)
            text_msg = await self.bot.send_message(chat_id, body)
            return [text_msg.message_id]

        caption = truncate_text(text, TELEGRAM_CAPTION_LIMIT) if text else None

        if message.media_type == MediaType.ALBUM:
            return await self._send_album(chat_id, message, caption)

        item = message.media_items[0] if message.media_items else None
        if item is None:
            msg = "media item missing"
            raise ValueError(msg)
        file = _input_file(item)

        media_msg: Message
        if message.media_type == MediaType.PHOTO:
            media_msg = await self.bot.send_photo(chat_id, file, caption=caption)
        elif message.media_type == MediaType.VIDEO:
            media_msg = await self.bot.send_video(chat_id, file, caption=caption)
        elif message.media_type == MediaType.ANIMATION:
            media_msg = await self.bot.send_animation(chat_id, file, caption=caption)
        elif message.media_type == MediaType.AUDIO:
            media_msg = await self.bot.send_audio(chat_id, file, caption=caption)
        elif message.media_type == MediaType.VOICE:
            media_msg = await self.bot.send_voice(chat_id, file, caption=caption)
        else:
            media_msg = await self.bot.send_document(chat_id, file, caption=caption)
        return [media_msg.message_id]

    async def _send_album(
        self,
        chat_id: int,
        message: NormalizedMessage,
        caption: str | None,
    ) -> list[int]:
        items = sorted(message.media_items, key=lambda m: m.order)
        if not items:
            msg = "album has no media items"
            raise ValueError(msg)

        media: list[Any] = []
        for idx, item in enumerate(items):
            file = _input_file(item)
            cap = caption if idx == 0 else None
            if item.media_type == MediaType.PHOTO:
                media.append(InputMediaPhoto(media=file, caption=cap))
            elif item.media_type == MediaType.VIDEO:
                media.append(InputMediaVideo(media=file, caption=cap))
            elif item.media_type == MediaType.ANIMATION:
                media.append(InputMediaAnimation(media=file, caption=cap))
            else:
                media.append(InputMediaDocument(media=file, caption=cap))

        sent_list = await self.bot.send_media_group(chat_id, media=media)
        return [m.message_id for m in sent_list]
