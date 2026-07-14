"""Keyword allow/block filter processor."""

from __future__ import annotations

from app.schemas.message import NormalizedMessage, ProcessingContext, ProcessResult


class KeywordFilterProcessor:
    name = "keyword_filter"

    def __init__(
        self,
        *,
        blocked: list[str] | None = None,
        allowed: list[str] | None = None,
        case_sensitive: bool = False,
        allow_empty_text: bool = True,
        enabled: bool = True,
    ) -> None:
        self.blocked = blocked or []
        self.allowed = allowed or []
        self.case_sensitive = case_sensitive
        self.allow_empty_text = allow_empty_text
        self.enabled = enabled

    def _prepare(self, text: str) -> str:
        return text if self.case_sensitive else text.lower()

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled:
            return ProcessResult.cont(message, skipped=True)

        text = message.display_text
        if not text.strip():
            if self.allow_empty_text:
                return ProcessResult.cont(message, empty_text=True)
            return ProcessResult.drop(message, "empty_text_not_allowed")

        haystack = self._prepare(text)

        for keyword in self.blocked:
            needle = keyword if self.case_sensitive else keyword.lower()
            if needle and needle in haystack:
                return ProcessResult.drop(
                    message,
                    "blocked_keyword",
                    keyword=keyword,
                )

        if self.allowed:
            matched = False
            for keyword in self.allowed:
                needle = keyword if self.case_sensitive else keyword.lower()
                if needle and needle in haystack:
                    matched = True
                    break
            if not matched:
                return ProcessResult.drop(message, "not_in_whitelist")

        return ProcessResult.cont(message)
