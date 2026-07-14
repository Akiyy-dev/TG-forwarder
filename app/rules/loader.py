"""Load KeywordRule rows into RuleDefinition objects."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KeywordRule, RuleGroup
from app.rules.types import MatchType, RuleAction, RuleDefinition, RuleType


def rule_row_to_definition(row: KeywordRule) -> RuleDefinition:
    return RuleDefinition(
        id=row.id,
        name=row.name,
        pattern=row.pattern,
        rule_type=RuleType(row.rule_type),
        match_type=MatchType(row.match_type),
        action=RuleAction(row.action),
        replacement=row.replacement or "",
        case_sensitive=row.case_sensitive,
        whole_word=row.whole_word,
        use_regex=row.use_regex,
        priority=row.priority,
        enabled=row.enabled,
        stop_processing=row.stop_processing,
        source_channel_ids=list(row.source_channel_ids or []),
        target_channel_ids=list(row.target_channel_ids or []),
        message_types=list(row.message_types or []),
    )


async def load_enabled_rules(session: AsyncSession) -> list[RuleDefinition]:
    group_rows = (
        await session.execute(select(RuleGroup).where(RuleGroup.enabled.is_(True)))
    ).scalars()
    groups = {g.id: g for g in group_rows}
    rows = list(
        (
            await session.execute(
                select(KeywordRule)
                .where(KeywordRule.enabled.is_(True))
                .order_by(KeywordRule.priority.asc(), KeywordRule.id.asc())
            )
        ).scalars()
    )
    rules: list[RuleDefinition] = []
    for row in rows:
        if row.group_id is not None and row.group_id not in groups:
            continue
        rules.append(rule_row_to_definition(row))
    return rules
