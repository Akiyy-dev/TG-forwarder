"""Rule matcher and RuleEngineProcessor tests."""

from __future__ import annotations

import pytest
from app.database.models import KeywordRule
from app.processors.rule_engine import RuleEngineProcessor
from app.rules.engine import apply_rules, preview_rule
from app.rules.matcher import RuleValidationError, find_matches, validate_rule
from app.rules.types import MatchType, RuleAction, RuleDefinition, RuleType
from app.schemas.message import MediaType, NormalizedMessage, ProcessAction, ProcessingContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _rule(**kwargs) -> RuleDefinition:
    data = {
        "id": 1,
        "name": "r1",
        "pattern": "spam",
        "rule_type": RuleType.KEYWORD,
        "match_type": MatchType.CONTAINS,
        "action": RuleAction.FLAG,
    }
    data.update(kwargs)
    return RuleDefinition(**data)  # type: ignore[arg-type]


def test_contains_and_whole_word() -> None:
    text = "spam and spammer"
    hits = find_matches(text, _rule(whole_word=False))
    assert len(hits) == 2
    hits_ww = find_matches(text, _rule(whole_word=True))
    assert len(hits_ww) == 1
    assert hits_ww[0].matched_text == "spam"


def test_replace_and_reject() -> None:
    rules = [
        _rule(
            id=1,
            name="clean",
            pattern="bad",
            action=RuleAction.REPLACE,
            replacement="***",
            priority=10,
        ),
        _rule(
            id=2,
            name="block",
            pattern="toxic",
            action=RuleAction.REJECT,
            priority=20,
        ),
    ]
    result = apply_rules("bad and toxic word", rules)
    assert result.text == "*** and toxic word"
    assert result.reject is True
    assert result.reject_reason == "rule:block"


def test_require_review_and_stop() -> None:
    rules = [
        _rule(
            id=1,
            name="rev",
            pattern="check",
            action=RuleAction.REQUIRE_REVIEW,
            stop_processing=True,
            priority=1,
        ),
        _rule(
            id=2,
            name="later",
            pattern="check",
            action=RuleAction.REJECT,
            priority=2,
        ),
    ]
    result = apply_rules("please check this", rules)
    assert result.require_review is True
    assert result.reject is False
    assert len(result.hits) == 1


def test_channel_scope() -> None:
    rule = _rule(source_channel_ids=[-1001], action=RuleAction.REJECT)
    miss = apply_rules("spam", [rule], source_chat_id=-999)
    hit = apply_rules("spam", [rule], source_chat_id=-1001)
    assert miss.reject is False
    assert hit.reject is True


def test_invalid_regex() -> None:
    with pytest.raises(RuleValidationError):
        validate_rule(_rule(pattern="(", use_regex=True, match_type=MatchType.REGEX))


def test_preview_rule() -> None:
    out = preview_rule(
        _rule(action=RuleAction.REPLACE, replacement="X", pattern="a"),
        "a b a",
    )
    assert out["matched"] is True
    assert out["final_text"] == "X b X"


def _msg(text: str = "hello spam") -> NormalizedMessage:
    return NormalizedMessage(
        source_chat_id=-1001,
        source_message_id=1,
        text=text,
        media_type=MediaType.TEXT,
    )


def _ctx() -> ProcessingContext:
    return ProcessingContext(target_chat_id=-1002)


async def test_processor_skipped_without_factory() -> None:
    p = RuleEngineProcessor(None)
    result = await p.process(_msg(), _ctx())
    assert result.action == ProcessAction.CONTINUE
    assert result.detail.get("skipped") is True


async def test_processor_replace_and_log(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(
            KeywordRule(
                name="replace-spam",
                pattern="spam",
                rule_type="keyword",
                match_type="contains",
                action="replace",
                replacement="[x]",
                enabled=True,
                priority=10,
                case_sensitive=False,
                whole_word=False,
                use_regex=False,
                stop_processing=False,
                hit_count=0,
            )
        )
        await session.commit()

    p = RuleEngineProcessor(session_factory)
    result = await p.process(_msg("buy spam now"), _ctx())
    assert result.action == ProcessAction.CONTINUE
    assert result.message is not None
    assert result.message.text == "buy [x] now"

    async with session_factory() as session:
        rule = (await session.execute(select(KeywordRule))).scalar_one()
        assert rule.hit_count == 1
        assert rule.last_hit_at is not None


async def test_processor_reject(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(
            KeywordRule(
                name="block",
                pattern="banme",
                rule_type="keyword",
                match_type="contains",
                action="reject",
                enabled=True,
                priority=1,
                case_sensitive=False,
                whole_word=False,
                use_regex=False,
                stop_processing=False,
                hit_count=0,
            )
        )
        await session.commit()

    p = RuleEngineProcessor(session_factory)
    result = await p.process(_msg("please banme"), _ctx())
    assert result.action == ProcessAction.DROP
    assert result.reason == "rule:block"


async def test_processor_require_review(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(
            KeywordRule(
                name="manual",
                pattern="sensitive",
                rule_type="keyword",
                match_type="contains",
                action="require_review",
                enabled=True,
                priority=1,
                case_sensitive=False,
                whole_word=False,
                use_regex=False,
                stop_processing=False,
                hit_count=0,
            )
        )
        await session.commit()

    p = RuleEngineProcessor(session_factory)
    result = await p.process(_msg("sensitive topic"), _ctx())
    assert result.action == ProcessAction.REVIEW
    assert result.reason == "rule_require_review"
