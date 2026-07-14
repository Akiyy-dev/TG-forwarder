"""Convert Telethon-like message objects into NormalizedMessage."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.schemas.message import (
    ForwardInfo,
    MediaItem,
    MediaType,
    MessageEntity,
    NormalizedMessage,
)


def _entity_type_name(entity: Any) -> str:
    name = type(entity).__name__
    mapping = {
        "MessageEntityBold": "bold",
        "MessageEntityItalic": "italic",
        "MessageEntityCode": "code",
        "MessageEntityPre": "pre",
        "MessageEntityTextUrl": "text_url",
        "MessageEntityUrl": "url",
        "MessageEntityMention": "mention",
        "MessageEntityMentionName": "text_mention",
        "MessageEntityEmail": "email",
        "MessageEntityHashtag": "hashtag",
        "MessageEntityStrike": "strikethrough",
        "MessageEntityUnderline": "underline",
        "MessageEntitySpoiler": "spoiler",
        "MessageEntityCustomEmoji": "custom_emoji",
        "MessageEntityBlockquote": "blockquote",
    }
    return mapping.get(name, name)


def extract_entities(raw_entities: list[Any] | None) -> list[MessageEntity]:
    if not raw_entities:
        return []
    result: list[MessageEntity] = []
    for ent in raw_entities:
        result.append(
            MessageEntity(
                type=_entity_type_name(ent),
                offset=int(getattr(ent, "offset", 0)),
                length=int(getattr(ent, "length", 0)),
                url=getattr(ent, "url", None),
                user_id=getattr(getattr(ent, "user_id", None), "user_id", None)
                if hasattr(ent, "user_id")
                else getattr(ent, "user_id", None),
                language=getattr(ent, "language", None),
                custom_emoji_id=str(getattr(ent, "document_id", "")) or None,
            )
        )
    return result


def detect_media_type(message: Any) -> MediaType:
    if getattr(message, "grouped_id", None):
        # Individual album parts still carry concrete media; album merge sets ALBUM.
        pass
    if getattr(message, "photo", None):
        return MediaType.PHOTO
    doc = getattr(message, "document", None)
    if doc is not None:
        mime = (getattr(doc, "mime_type", None) or "").lower()
        attrs = list(getattr(doc, "attributes", []) or [])
        attr_names = {type(a).__name__ for a in attrs}
        if "DocumentAttributeSticker" in attr_names:
            return MediaType.STICKER
        if "DocumentAttributeAnimated" in attr_names or mime == "image/gif":
            return MediaType.ANIMATION
        if "DocumentAttributeVideo" in attr_names or mime.startswith("video/"):
            # Round video / gif-like
            if "DocumentAttributeAnimated" in attr_names:
                return MediaType.ANIMATION
            return MediaType.VIDEO
        if "DocumentAttributeAudio" in attr_names:
            for attr in attrs:
                if type(attr).__name__ == "DocumentAttributeAudio" and getattr(
                    attr, "voice", False
                ):
                    return MediaType.VOICE
            return MediaType.AUDIO
        return MediaType.DOCUMENT
    if getattr(message, "sticker", None):
        return MediaType.STICKER
    if getattr(message, "video", None):
        return MediaType.VIDEO
    if getattr(message, "voice", None):
        return MediaType.VOICE
    if getattr(message, "audio", None):
        return MediaType.AUDIO
    if getattr(message, "animation", None):
        return MediaType.ANIMATION
    text = getattr(message, "message", None) or getattr(message, "text", None) or ""
    if text:
        return MediaType.TEXT
    return MediaType.UNSUPPORTED


def _filename_from_document(doc: Any) -> str | None:
    for attr in getattr(doc, "attributes", []) or []:
        if type(attr).__name__ == "DocumentAttributeFilename":
            return getattr(attr, "file_name", None)
    return None


def normalize_telethon_message(
    message: Any,
    *,
    chat_username: str | None = None,
    chat_title: str | None = None,
    target_chat_id: int | None = None,
) -> NormalizedMessage:
    chat_id = int(getattr(message, "chat_id", 0) or getattr(message.peer_id, "channel_id", 0))
    # Telethon channel ids are often without -100 prefix on peer; prefer message.chat_id
    if hasattr(message, "chat") and message.chat is not None:
        chat_id = int(message.chat.id)
        chat_username = chat_username or getattr(message.chat, "username", None)
        chat_title = chat_title or getattr(message.chat, "title", None)

    text = getattr(message, "message", None) or getattr(message, "text", None) or ""
    media_type = detect_media_type(message)
    media_items: list[MediaItem] = []
    original_filename = None
    mime_type = None
    file_size = None
    file_unique_id = None

    if media_type == MediaType.PHOTO and getattr(message, "photo", None):
        photo = message.photo
        file_size = getattr(photo, "sizes", None)
        sizes = getattr(photo, "sizes", []) or []
        if sizes:
            largest = sizes[-1]
            file_size = getattr(largest, "size", None)
        file_unique_id = str(getattr(photo, "id", ""))
        media_items.append(
            MediaItem(
                media_type=MediaType.PHOTO,
                file_unique_id=file_unique_id,
                file_size=file_size,
                source_message_id=int(message.id),
            )
        )
    elif getattr(message, "document", None):
        doc = message.document
        original_filename = _filename_from_document(doc)
        mime_type = getattr(doc, "mime_type", None)
        file_size = getattr(doc, "size", None)
        file_unique_id = str(getattr(doc, "id", ""))
        media_items.append(
            MediaItem(
                media_type=media_type,
                file_unique_id=file_unique_id,
                original_filename=original_filename,
                mime_type=mime_type,
                file_size=file_size,
                source_message_id=int(message.id),
            )
        )

    forward_info = None
    fwd = getattr(message, "fwd_from", None)
    if fwd is not None:
        forward_info = ForwardInfo(
            from_name=getattr(fwd, "from_name", None),
            from_message_id=getattr(fwd, "channel_post", None),
            date=getattr(fwd, "date", None),
        )

    date = getattr(message, "date", None)
    if date is not None and date.tzinfo is None:
        date = date.replace(tzinfo=UTC)

    edit_date = getattr(message, "edit_date", None)
    if edit_date is not None and edit_date.tzinfo is None:
        edit_date = edit_date.replace(tzinfo=UTC)

    reply_to = getattr(message, "reply_to", None)
    reply_id = getattr(reply_to, "reply_to_msg_id", None) if reply_to else None

    return NormalizedMessage(
        source_chat_id=chat_id,
        source_message_id=int(message.id),
        source_chat_username=chat_username,
        source_chat_title=chat_title,
        grouped_id=getattr(message, "grouped_id", None),
        date=date or datetime.now(UTC),
        edit_date=edit_date,
        text=text,
        entities=extract_entities(getattr(message, "entities", None)),
        media_type=media_type,
        media_items=media_items,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size=file_size,
        reply_to_message_id=reply_id,
        forward_info=forward_info,
        raw_metadata={
            "file_unique_id": file_unique_id,
            "has_media": bool(getattr(message, "media", None)),
        },
        target_chat_id=target_chat_id,
    )
