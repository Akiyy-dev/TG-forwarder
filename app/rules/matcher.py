"""Safe text matcher shared by production and rule testing APIs."""

from __future__ import annotations

import re
import signal
from collections.abc import Iterator

from app.rules.types import MatchHit, MatchType, RuleDefinition, RuleType

# Soft timeout for regex on platforms that support SIGALRM (not Windows).
_REGEX_TIMEOUT_SECONDS = 0.05
_MAX_PATTERN_LEN = 500


class RuleValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def normalize_has_media_pattern(pattern: str | None) -> str:
    raw = (pattern or "has").strip().lower()
    if raw in {"", "has", "true", "any", "yes", "1"}:
        return "has"
    if raw in {"none", "false", "no", "0", "empty", "text"}:
        return "none"
    return raw


def validate_rule(rule: RuleDefinition) -> None:
    if not rule.name.strip():
        raise RuleValidationError("name is required")
    if rule.rule_type == RuleType.HAS_MEDIA:
        mode = normalize_has_media_pattern(rule.pattern)
        if mode not in {"has", "none"}:
            raise RuleValidationError("has_media pattern must be 'has' or 'none'")
        return
    if not rule.pattern:
        raise RuleValidationError("pattern is required")
    if len(rule.pattern) > _MAX_PATTERN_LEN:
        raise RuleValidationError("pattern too long")
    if rule.use_regex or rule.match_type == MatchType.REGEX or rule.rule_type.value == "regex":
        try:
            re.compile(rule.pattern)
        except re.error as exc:
            raise RuleValidationError(f"invalid regex: {exc}") from exc


def message_has_media(*, media_type: str | None, media_count: int = 0) -> bool:
    """True when the message carries non-text media (stickers count as media)."""
    if media_count > 0:
        return True
    if not media_type:
        return False
    return media_type not in {"text", "unsupported"}


def find_has_media_matches(
    rule: RuleDefinition,
    *,
    media_type: str | None,
    media_count: int = 0,
) -> list[MatchHit]:
    validate_rule(rule)
    mode = normalize_has_media_pattern(rule.pattern)
    present = message_has_media(media_type=media_type, media_count=media_count)
    matched = present if mode == "has" else not present
    if not matched:
        return []
    label = "has_media" if present else "no_media"
    return [MatchHit(0, 0, label)]


def _whole_word_bounds(text: str, start: int, end: int) -> bool:
    left_ok = start == 0 or not (text[start - 1].isalnum() or text[start - 1] == "_")
    right_ok = end >= len(text) or not (text[end].isalnum() or text[end] == "_")
    return left_ok and right_ok


class _Timeout:
    def __enter__(self) -> _Timeout:
        setitimer = getattr(signal, "setitimer", None)
        itimer_real = getattr(signal, "ITIMER_REAL", None)
        if hasattr(signal, "SIGALRM") and setitimer is not None and itimer_real is not None:
            signal.signal(signal.SIGALRM, self._raise)
            setitimer(itimer_real, _REGEX_TIMEOUT_SECONDS)
        return self

    def __exit__(self, *args: object) -> None:
        setitimer = getattr(signal, "setitimer", None)
        itimer_real = getattr(signal, "ITIMER_REAL", None)
        if setitimer is not None and itimer_real is not None:
            setitimer(itimer_real, 0)

    @staticmethod
    def _raise(_signum: int, _frame: object) -> None:
        raise TimeoutError("regex timed out")


def find_matches(text: str, rule: RuleDefinition) -> list[MatchHit]:
    validate_rule(rule)
    if not text:
        return []

    flags = 0 if rule.case_sensitive else re.IGNORECASE
    hits: list[MatchHit] = []

    use_regex = (
        rule.use_regex or rule.match_type == MatchType.REGEX or rule.rule_type.value == "regex"
    )

    if use_regex:
        try:
            with _Timeout():
                for m in re.finditer(rule.pattern, text, flags=flags):
                    hits.append(MatchHit(m.start(), m.end(), m.group(0)))
        except TimeoutError:
            return []
        except re.error:
            return []
        return hits

    haystack = text if rule.case_sensitive else text.lower()
    needle = rule.pattern if rule.case_sensitive else rule.pattern.lower()

    if rule.match_type == MatchType.EQUALS:
        if haystack == needle and (not rule.whole_word or _whole_word_bounds(text, 0, len(text))):
            return [MatchHit(0, len(text), text)]
        return []

    if rule.match_type == MatchType.STARTS_WITH:
        if haystack.startswith(needle):
            end = len(rule.pattern)
            if not rule.whole_word or _whole_word_bounds(text, 0, end):
                return [MatchHit(0, end, text[:end])]
        return []

    if rule.match_type == MatchType.ENDS_WITH:
        if haystack.endswith(needle):
            start = len(text) - len(rule.pattern)
            if not rule.whole_word or _whole_word_bounds(text, start, len(text)):
                return [MatchHit(start, len(text), text[start:])]
        return []

    # contains / phrase / keyword default
    start_at = 0
    while True:
        idx = haystack.find(needle, start_at)
        if idx < 0:
            break
        end = idx + len(needle)
        if not rule.whole_word or _whole_word_bounds(text, idx, end):
            hits.append(MatchHit(idx, end, text[idx:end]))
        start_at = idx + max(1, len(needle))
    return hits


def apply_replacements(text: str, hits: list[MatchHit], replacement: str) -> str:
    """Apply non-overlapping replacements from right to left."""
    ordered = sorted(hits, key=lambda h: h.start, reverse=True)
    chars = text
    last_start = len(text) + 1
    for hit in ordered:
        if hit.end > last_start:
            continue
        chars = chars[: hit.start] + replacement + chars[hit.end :]
        last_start = hit.start
    return chars


def iter_safe(hits: Iterator[MatchHit]) -> list[MatchHit]:
    return list(hits)
