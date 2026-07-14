"""Async processor pipeline runner."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.logging import get_logger
from app.processors.base import MessageProcessor
from app.processors.deduplication import DeduplicationProcessor
from app.processors.footer import FooterProcessor
from app.processors.keyword_filter import KeywordFilterProcessor
from app.processors.link_filter import LinkFilterProcessor
from app.processors.rule_engine import RuleEngineProcessor
from app.processors.text_replace import TextReplaceProcessor
from app.schemas.message import (
    NormalizedMessage,
    ProcessAction,
    ProcessingContext,
    ProcessResult,
)

logger = get_logger(__name__)

DuplicateExistsFn = Callable[[str], Awaitable[bool]]


class ProcessorPipeline:
    def __init__(self, processors: list[MessageProcessor]) -> None:
        self.processors = processors

    async def run(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> tuple[ProcessResult, list[dict[str, Any]]]:
        logs: list[dict[str, Any]] = []
        current = message
        final = ProcessResult.cont(current)

        for processor in self.processors:
            started = time.perf_counter()
            result = await processor.process(current, context)
            duration_ms = (time.perf_counter() - started) * 1000
            logs.append(
                {
                    "processor": processor.name,
                    "status": result.action.value,
                    "reason": result.reason,
                    "detail": result.detail,
                    "duration_ms": duration_ms,
                }
            )
            logger.info(
                "processor_finished",
                processor=processor.name,
                status=result.action.value,
                source_chat_id=current.source_chat_id,
                source_message_id=current.source_message_id,
                grouped_id=current.grouped_id,
                duration=duration_ms,
            )
            if result.message is not None:
                current = result.message
            final = result
            if result.action != ProcessAction.CONTINUE:
                break

        if final.message is None:
            final.message = current
        return final, logs


def build_default_pipeline(
    settings: Settings,
    *,
    duplicate_exists_fn: DuplicateExistsFn | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> ProcessorPipeline:
    processors: list[MessageProcessor] = [
        KeywordFilterProcessor(
            blocked=settings.blocked_keywords,
            allowed=settings.allowed_keywords,
            case_sensitive=settings.keyword_case_sensitive,
            allow_empty_text=settings.allow_empty_text,
            enabled=settings.enable_keyword_filter,
        ),
        TextReplaceProcessor(
            settings.text_replacements,
            enabled=settings.enable_text_replace,
        ),
        LinkFilterProcessor(
            remove_all_links=settings.remove_all_links,
            remove_telegram_invites=settings.remove_telegram_invites,
            remove_source_links=settings.remove_source_links,
            blocked_domains=settings.blocked_link_domains,
            allowed_domains=settings.allowed_link_domains,
            enabled=settings.enable_link_filter,
        ),
        RuleEngineProcessor(session_factory, enabled=session_factory is not None),
        FooterProcessor(settings.message_footer, enabled=settings.enable_footer),
        DeduplicationProcessor(
            exists_fn=duplicate_exists_fn,
            enabled=settings.enable_duplicate_filter,
        ),
    ]
    return ProcessorPipeline(processors)
