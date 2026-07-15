"""has_media rule type tests."""

from __future__ import annotations

import pytest
from app.rules.engine import apply_rules, preview_rule
from app.rules.matcher import RuleValidationError, message_has_media, validate_rule
from app.rules.types import RuleAction, RuleDefinition, RuleType


def _rule(pattern: str = "has", action: RuleAction = RuleAction.REQUIRE_REVIEW) -> RuleDefinition:
    return RuleDefinition(
        id=1,
        name="media-gate",
        pattern=pattern,
        rule_type=RuleType.HAS_MEDIA,
        action=action,
        priority=10,
        enabled=True,
    )


def test_message_has_media_predicate() -> None:
    assert message_has_media(media_type="photo") is True
    assert message_has_media(media_type="sticker") is True
    assert message_has_media(media_type="album") is True
    assert message_has_media(media_type="text") is False
    assert message_has_media(media_type="unsupported") is False
    assert message_has_media(media_type="text", media_count=1) is True


def test_has_media_validation() -> None:
    validate_rule(_rule("has"))
    validate_rule(_rule("none"))
    validate_rule(_rule(""))
    with pytest.raises(RuleValidationError):
        validate_rule(_rule("maybe"))


def test_apply_has_media_require_review() -> None:
    result = apply_rules(
        "caption",
        [_rule("has")],
        media_type="photo",
        media_count=1,
    )
    assert result.require_review is True
    assert result.hits

    empty = apply_rules(
        "plain",
        [_rule("has")],
        media_type="text",
        media_count=0,
    )
    assert empty.require_review is False
    assert not empty.hits


def test_apply_no_media_pattern() -> None:
    result = apply_rules(
        "plain",
        [_rule("none", action=RuleAction.FLAG)],
        media_type="text",
    )
    assert result.flagged == ["media-gate"]

    skip = apply_rules(
        "with pic",
        [_rule("none", action=RuleAction.FLAG)],
        media_type="photo",
    )
    assert not skip.flagged


def test_preview_has_media() -> None:
    ok = preview_rule(_rule("has"), "", sample_media_type="photo")
    assert ok["matched"] is True
    miss = preview_rule(_rule("has"), "", sample_media_type="text")
    assert miss["matched"] is False
