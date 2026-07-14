"""Processor unit tests."""

from __future__ import annotations

from app.processors.deduplication import DeduplicationProcessor
from app.processors.footer import FooterProcessor
from app.processors.keyword_filter import KeywordFilterProcessor
from app.processors.link_filter import LinkFilterProcessor
from app.processors.text_replace import TextReplaceProcessor
from app.schemas.message import (
    MediaType,
    MessageEntity,
    NormalizedMessage,
    ProcessAction,
    ProcessingContext,
)
from app.utils.text import TELEGRAM_CAPTION_LIMIT


def _msg(text: str = "hello", **kwargs) -> NormalizedMessage:
    return NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=1,
        text=text,
        media_type=kwargs.pop("media_type", MediaType.TEXT),
        **kwargs,
    )


def _ctx() -> ProcessingContext:
    return ProcessingContext(target_chat_id=-1002, source_username="srcchan")


async def test_keyword_block() -> None:
    p = KeywordFilterProcessor(blocked=["spam"], case_sensitive=False)
    result = await p.process(_msg("this is SPAM yes"), _ctx())
    assert result.action == ProcessAction.DROP


async def test_keyword_whitelist() -> None:
    p = KeywordFilterProcessor(allowed=["news"], case_sensitive=False)
    ok = await p.process(_msg("breaking news today"), _ctx())
    bad = await p.process(_msg("random chatter"), _ctx())
    assert ok.action == ProcessAction.CONTINUE
    assert bad.action == ProcessAction.DROP


async def test_text_replace() -> None:
    p = TextReplaceProcessor([("Foo", "Bar")])
    result = await p.process(_msg("Foo and Foo"), _ctx())
    assert result.message is not None
    assert result.message.text == "Bar and Bar"


async def test_link_filter_entities_and_cleanup() -> None:
    text = "See https://t.me/+abcdef and https://example.com/ok @srcchan"
    entities = [
        MessageEntity(
            type="url", offset=4, length=len("https://t.me/+abcdef"), url="https://t.me/+abcdef"
        ),
    ]
    p = LinkFilterProcessor(remove_telegram_invites=True, remove_source_links=True)
    result = await p.process(_msg(text, entities=entities), _ctx())
    assert result.message is not None
    assert "+abcdef" not in result.message.text
    assert "@srcchan" not in result.message.text


async def test_link_remove_all() -> None:
    p = LinkFilterProcessor(remove_all_links=True)
    result = await p.process(_msg("go https://evil.test now"), _ctx())
    assert result.message is not None
    assert "http" not in result.message.text


async def test_footer_length() -> None:
    footer = "FOOTER"
    body = "x" * (TELEGRAM_CAPTION_LIMIT)
    p = FooterProcessor(footer=footer)
    msg = _msg(body, media_type=MediaType.PHOTO)
    result = await p.process(msg, _ctx())
    assert result.message is not None
    assert result.message.text.endswith(footer)
    assert len(result.message.text) <= TELEGRAM_CAPTION_LIMIT


async def test_footer_empty_body() -> None:
    p = FooterProcessor(footer="OnlyFooter")
    result = await p.process(_msg(""), _ctx())
    assert result.message is not None
    assert result.message.text == "OnlyFooter"


async def test_content_hash_and_dedup() -> None:
    seen: set[str] = set()

    async def exists(h: str) -> bool:
        if h in seen:
            return True
        seen.add(h)
        return False

    p = DeduplicationProcessor(exists_fn=exists)
    a = await p.process(_msg("Same"), _ctx())
    b = await p.process(_msg("Same"), _ctx())
    assert a.action == ProcessAction.CONTINUE
    assert b.action == ProcessAction.DROP
    assert a.detail["content_hash"] == DeduplicationProcessor.compute_hash(_msg("Same"))
