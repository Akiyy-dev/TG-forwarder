"""Rule enums and match result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RuleType(StrEnum):
    KEYWORD = "keyword"
    PHRASE = "phrase"
    USERNAME = "username"
    LINK = "link"
    DOMAIN = "domain"
    REGEX = "regex"
    HAS_MEDIA = "has_media"


class MatchType(StrEnum):
    CONTAINS = "contains"
    EQUALS = "equals"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    REGEX = "regex"


class RuleAction(StrEnum):
    FLAG = "flag"
    REJECT = "reject"
    REQUIRE_REVIEW = "require_review"
    REPLACE = "replace"
    REMOVE = "remove"
    ADD_TAG = "add_tag"


@dataclass(slots=True)
class MatchHit:
    start: int
    end: int
    matched_text: str


@dataclass
class RuleDefinition:
    id: int | None
    name: str
    pattern: str
    rule_type: RuleType = RuleType.KEYWORD
    match_type: MatchType = MatchType.CONTAINS
    action: RuleAction = RuleAction.FLAG
    replacement: str = ""
    case_sensitive: bool = False
    whole_word: bool = False
    use_regex: bool = False
    priority: int = 100
    enabled: bool = True
    stop_processing: bool = False
    source_channel_ids: list[int] = field(default_factory=list)
    target_channel_ids: list[int] = field(default_factory=list)
    message_types: list[str] = field(default_factory=list)


@dataclass
class RuleApplyResult:
    text: str
    hits: list[dict[str, object]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    require_review: bool = False
    reject: bool = False
    reject_reason: str | None = None
    flagged: list[str] = field(default_factory=list)
