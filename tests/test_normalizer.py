"""Normalizer mapping tests with mock Telethon-like objects."""

from __future__ import annotations

from types import SimpleNamespace

from app.listeners.normalizer import detect_media_type, normalize_telethon_message
from app.schemas.message import MediaType


def test_normalize_text_message() -> None:
    msg = SimpleNamespace(
        id=10,
        chat_id=-100123,
        message="hello",
        text="hello",
        entities=[],
        photo=None,
        document=None,
        grouped_id=None,
        date=None,
        edit_date=None,
        reply_to=None,
        fwd_from=None,
        media=None,
        chat=SimpleNamespace(id=-100123, username="demo", title="Demo"),
    )
    normalized = normalize_telethon_message(msg)
    assert normalized.source_message_id == 10
    assert normalized.text == "hello"
    assert normalized.media_type == MediaType.TEXT
    assert normalized.source_chat_username == "demo"


def test_detect_photo() -> None:
    msg = SimpleNamespace(
        photo=object(),
        document=None,
        message="",
        sticker=None,
        video=None,
        voice=None,
        audio=None,
        animation=None,
        grouped_id=None,
    )
    assert detect_media_type(msg) == MediaType.PHOTO
