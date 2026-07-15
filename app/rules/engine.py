"""Rule application engine."""

from __future__ import annotations

import time
from typing import Any

from app.rules.matcher import (
    RuleValidationError,
    apply_replacements,
    find_has_media_matches,
    find_matches,
    validate_rule,
)
from app.rules.types import RuleAction, RuleApplyResult, RuleDefinition, RuleType


def rule_applies(
    rule: RuleDefinition,
    *,
    source_chat_id: int | None,
    target_chat_id: int | None,
    media_type: str | None,
) -> bool:
    if not rule.enabled:
        return False
    if rule.source_channel_ids and source_chat_id not in rule.source_channel_ids:
        return False
    if rule.target_channel_ids and target_chat_id not in rule.target_channel_ids:
        return False
    return not (rule.message_types and media_type and media_type not in rule.message_types)


def apply_rules(
    text: str,
    rules: list[RuleDefinition],
    *,
    source_chat_id: int | None = None,
    target_chat_id: int | None = None,
    media_type: str | None = None,
    media_count: int = 0,
) -> RuleApplyResult:
    ordered = sorted(rules, key=lambda r: (r.priority, r.id or 0))
    current = text
    result = RuleApplyResult(text=current)

    for rule in ordered:
        if not rule_applies(
            rule,
            source_chat_id=source_chat_id,
            target_chat_id=target_chat_id,
            media_type=media_type,
        ):
            continue
        started = time.perf_counter()
        try:
            validate_rule(rule)
            if rule.rule_type == RuleType.HAS_MEDIA:
                hits = find_has_media_matches(
                    rule,
                    media_type=media_type,
                    media_count=media_count,
                )
            else:
                hits = find_matches(current, rule)
        except RuleValidationError as exc:
            result.hits.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "action": rule.action.value,
                    "error": exc.message,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                }
            )
            continue
        if not hits:
            continue

        before = current
        replacement_text = ""
        if rule.action == RuleAction.REPLACE:
            current = apply_replacements(current, hits, rule.replacement)
            replacement_text = rule.replacement
        elif rule.action == RuleAction.REMOVE:
            current = apply_replacements(current, hits, "")
            replacement_text = ""
        elif rule.action == RuleAction.ADD_TAG:
            result.tags.append(rule.replacement or rule.name)
        elif rule.action == RuleAction.FLAG:
            result.flagged.append(rule.name)
        elif rule.action == RuleAction.REQUIRE_REVIEW:
            result.require_review = True
        elif rule.action == RuleAction.REJECT:
            result.reject = True
            result.reject_reason = f"rule:{rule.name}"

        for hit in hits:
            result.hits.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "action": rule.action.value,
                    "matched_text": hit.matched_text,
                    "replacement_text": replacement_text,
                    "match_start": hit.start,
                    "match_end": hit.end,
                    "before_excerpt": before[max(0, hit.start - 20) : hit.end + 20],
                    "after_excerpt": current[max(0, hit.start - 20) : hit.start + 20],
                    "duration_ms": (time.perf_counter() - started) * 1000,
                }
            )

        if rule.stop_processing or result.reject:
            break

    result.text = current
    return result


def preview_rule(
    rule: RuleDefinition,
    sample_text: str,
    *,
    sample_media_type: str | None = None,
    sample_media_count: int = 0,
) -> dict[str, Any]:
    validate_rule(rule)
    if rule.rule_type == RuleType.HAS_MEDIA:
        hits = find_has_media_matches(
            rule,
            media_type=sample_media_type or "text",
            media_count=sample_media_count,
        )
        return {
            "matched": bool(hits),
            "hits": [{"start": h.start, "end": h.end, "text": h.matched_text} for h in hits],
            "final_text": sample_text,
        }
    hits = find_matches(sample_text, rule)
    after = sample_text
    if rule.action == RuleAction.REPLACE:
        after = apply_replacements(sample_text, hits, rule.replacement)
    elif rule.action == RuleAction.REMOVE:
        after = apply_replacements(sample_text, hits, "")
    return {
        "matched": bool(hits),
        "hits": [{"start": h.start, "end": h.end, "text": h.matched_text} for h in hits],
        "final_text": after,
    }
