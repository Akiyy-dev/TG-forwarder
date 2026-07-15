"""DB-backed rule engine processor."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import KeywordRule, RuleExecutionLog
from app.rules.engine import apply_rules
from app.rules.loader import load_enabled_rules
from app.rules.types import RuleDefinition
from app.schemas.message import NormalizedMessage, ProcessingContext, ProcessResult


class RuleEngineProcessor:
    name = "rule_engine"

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        self.session_factory = session_factory
        self.enabled = enabled

    async def _load_rules(self) -> list[RuleDefinition]:
        if self.session_factory is None:
            return []
        async with self.session_factory() as session:
            return await load_enabled_rules(session)

    async def process(
        self,
        message: NormalizedMessage,
        context: ProcessingContext,
    ) -> ProcessResult:
        if not self.enabled or self.session_factory is None:
            return ProcessResult.cont(message, skipped=True)

        rules = await self._load_rules()
        if not rules:
            return ProcessResult.cont(message, skipped=True)

        applied = apply_rules(
            message.text or "",
            rules,
            source_chat_id=message.source_chat_id,
            target_chat_id=context.target_chat_id,
            media_type=message.media_type.value,
            media_count=len(message.media_items or []),
        )
        message.text = applied.text
        context.extra["matched_rules"] = applied.hits
        context.extra["detected_keywords"] = applied.flagged
        context.extra["tags"] = applied.tags

        if self.session_factory is not None and applied.hits:
            async with self.session_factory() as session:
                for hit in applied.hits:
                    if hit.get("error"):
                        continue
                    rule_id = hit.get("rule_id")
                    match_start = hit.get("match_start")
                    match_end = hit.get("match_end")
                    duration_ms = hit.get("duration_ms")
                    session.add(
                        RuleExecutionLog(
                            rule_id=rule_id if isinstance(rule_id, int) else None,
                            rule_name=str(hit.get("rule_name") or ""),
                            action=str(hit.get("action") or ""),
                            matched_text=str(hit.get("matched_text") or "")[:512] or None,
                            replacement_text=str(hit.get("replacement_text") or "")[:512] or None,
                            match_start=match_start if isinstance(match_start, int) else None,
                            match_end=match_end if isinstance(match_end, int) else None,
                            before_excerpt=str(hit.get("before_excerpt") or "")[:512] or None,
                            after_excerpt=str(hit.get("after_excerpt") or "")[:512] or None,
                            duration_ms=(
                                float(duration_ms) if isinstance(duration_ms, int | float) else None
                            ),
                        )
                    )
                    if isinstance(rule_id, int):
                        rule = await session.get(KeywordRule, rule_id)
                        if rule is not None:
                            rule.hit_count += 1
                            rule.last_hit_at = datetime.now(UTC)
                await session.commit()

        if applied.reject:
            return ProcessResult.drop(
                message,
                applied.reject_reason or "rule_reject",
                matched_rules=applied.hits,
            )
        if applied.require_review:
            return ProcessResult.review(
                message,
                "rule_require_review",
                matched_rules=applied.hits,
                detected_keywords=applied.flagged,
            )
        return ProcessResult.cont(
            message,
            matched_rules=applied.hits,
            detected_keywords=applied.flagged,
        )
