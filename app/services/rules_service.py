"""Keyword rule and rule-group management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config_files import load_rules_config
from app.database.models import KeywordRule, RuleExecutionLog, RuleGroup
from app.logging import get_logger
from app.rules.engine import apply_rules, preview_rule
from app.rules.loader import load_enabled_rules, rule_row_to_definition
from app.rules.matcher import RuleValidationError, normalize_has_media_pattern, validate_rule
from app.rules.types import MatchType, RuleAction, RuleApplyResult, RuleDefinition, RuleType

logger = get_logger(__name__)


class RulesServiceError(Exception):
    def __init__(self, message: str, *, code: str = "rules_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class RulesService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    @staticmethod
    def _definition_from_payload(
        data: dict[str, Any], *, rule_id: int | None = None
    ) -> RuleDefinition:
        try:
            rule_type = RuleType(data.get("rule_type", RuleType.KEYWORD))
            pattern = str(data.get("pattern") or "")
            if rule_type == RuleType.HAS_MEDIA:
                pattern = normalize_has_media_pattern(pattern)
            definition = RuleDefinition(
                id=rule_id,
                name=str(data["name"]),
                pattern=pattern,
                rule_type=rule_type,
                match_type=MatchType(data.get("match_type", MatchType.CONTAINS)),
                action=RuleAction(data.get("action", RuleAction.FLAG)),
                replacement=str(data.get("replacement") or ""),
                case_sensitive=bool(data.get("case_sensitive", False)),
                whole_word=bool(data.get("whole_word", False)),
                use_regex=bool(data.get("use_regex", False)),
                priority=int(data.get("priority", 100)),
                enabled=bool(data.get("enabled", True)),
                stop_processing=bool(data.get("stop_processing", False)),
                source_channel_ids=list(data.get("source_channel_ids") or []),
                target_channel_ids=list(data.get("target_channel_ids") or []),
                message_types=list(data.get("message_types") or []),
            )
            validate_rule(definition)
            return definition
        except (KeyError, ValueError, TypeError, RuleValidationError) as exc:
            msg = getattr(exc, "message", None) or str(exc)
            raise RulesServiceError(msg, code="validation_error") from exc

    async def list_rules(
        self,
        *,
        page: int,
        page_size: int,
        enabled: bool | None = None,
        group_id: int | None = None,
        q: str | None = None,
    ) -> tuple[list[KeywordRule], int]:
        async with self.session_factory() as session:
            count_stmt = select(func.count()).select_from(KeywordRule)
            list_stmt = select(KeywordRule).order_by(
                KeywordRule.priority.asc(), KeywordRule.id.asc()
            )
            if enabled is not None:
                count_stmt = count_stmt.where(KeywordRule.enabled.is_(enabled))
                list_stmt = list_stmt.where(KeywordRule.enabled.is_(enabled))
            if group_id is not None:
                count_stmt = count_stmt.where(KeywordRule.group_id == group_id)
                list_stmt = list_stmt.where(KeywordRule.group_id == group_id)
            if q:
                like = f"%{q}%"
                clause = or_(KeywordRule.name.like(like), KeywordRule.pattern.like(like))
                count_stmt = count_stmt.where(clause)
                list_stmt = list_stmt.where(clause)
            total = int((await session.execute(count_stmt)).scalar_one())
            rows = list(
                (
                    await session.execute(list_stmt.offset((page - 1) * page_size).limit(page_size))
                ).scalars()
            )
            return rows, total

    async def get_rule(self, rule_id: int) -> KeywordRule:
        async with self.session_factory() as session:
            rule = await session.get(KeywordRule, rule_id)
            if rule is None:
                raise RulesServiceError("rule not found", code="not_found")
            return rule

    async def create_rule(self, data: dict[str, Any], *, created_by: int | None) -> KeywordRule:
        definition = self._definition_from_payload(data)
        async with self.session_factory() as session:
            if data.get("group_id") is not None:
                group = await session.get(RuleGroup, int(data["group_id"]))
                if group is None:
                    raise RulesServiceError("rule group not found", code="not_found")
            rule = KeywordRule(
                name=definition.name,
                description=data.get("description"),
                enabled=definition.enabled,
                priority=definition.priority,
                rule_type=definition.rule_type.value,
                match_type=definition.match_type.value,
                pattern=definition.pattern,
                replacement=definition.replacement or None,
                case_sensitive=definition.case_sensitive,
                whole_word=definition.whole_word,
                use_regex=definition.use_regex,
                source_channel_ids=definition.source_channel_ids or None,
                target_channel_ids=definition.target_channel_ids or None,
                message_types=definition.message_types or None,
                action=definition.action.value,
                stop_processing=definition.stop_processing,
                group_id=data.get("group_id"),
                hit_count=0,
                created_by=created_by,
            )
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def update_rule(self, rule_id: int, data: dict[str, Any]) -> KeywordRule:
        async with self.session_factory() as session:
            rule = await session.get(KeywordRule, rule_id)
            if rule is None:
                raise RulesServiceError("rule not found", code="not_found")
            merged = {
                "name": data.get("name", rule.name),
                "pattern": data.get("pattern", rule.pattern),
                "rule_type": data.get("rule_type", rule.rule_type),
                "match_type": data.get("match_type", rule.match_type),
                "action": data.get("action", rule.action),
                "replacement": data.get("replacement", rule.replacement),
                "case_sensitive": data.get("case_sensitive", rule.case_sensitive),
                "whole_word": data.get("whole_word", rule.whole_word),
                "use_regex": data.get("use_regex", rule.use_regex),
                "priority": data.get("priority", rule.priority),
                "enabled": data.get("enabled", rule.enabled),
                "stop_processing": data.get("stop_processing", rule.stop_processing),
                "source_channel_ids": data.get("source_channel_ids", rule.source_channel_ids),
                "target_channel_ids": data.get("target_channel_ids", rule.target_channel_ids),
                "message_types": data.get("message_types", rule.message_types),
            }
            definition = self._definition_from_payload(merged, rule_id=rule_id)
            if "group_id" in data:
                group_id = data["group_id"]
                if group_id is not None:
                    group = await session.get(RuleGroup, int(group_id))
                    if group is None:
                        raise RulesServiceError("rule group not found", code="not_found")
                rule.group_id = group_id
            if "description" in data:
                rule.description = data["description"]
            rule.name = definition.name
            rule.pattern = definition.pattern
            rule.rule_type = definition.rule_type.value
            rule.match_type = definition.match_type.value
            rule.action = definition.action.value
            rule.replacement = definition.replacement or None
            rule.case_sensitive = definition.case_sensitive
            rule.whole_word = definition.whole_word
            rule.use_regex = definition.use_regex
            rule.priority = definition.priority
            rule.enabled = definition.enabled
            rule.stop_processing = definition.stop_processing
            rule.source_channel_ids = definition.source_channel_ids or None
            rule.target_channel_ids = definition.target_channel_ids or None
            rule.message_types = definition.message_types or None
            await session.commit()
            await session.refresh(rule)
            return rule

    async def delete_rule(self, rule_id: int) -> None:
        async with self.session_factory() as session:
            rule = await session.get(KeywordRule, rule_id)
            if rule is None:
                raise RulesServiceError("rule not found", code="not_found")
            await session.delete(rule)
            await session.commit()

    async def duplicate_rule(self, rule_id: int, *, created_by: int | None) -> KeywordRule:
        async with self.session_factory() as session:
            rule = await session.get(KeywordRule, rule_id)
            if rule is None:
                raise RulesServiceError("rule not found", code="not_found")
            copy = KeywordRule(
                name=f"{rule.name} (copy)",
                description=rule.description,
                enabled=False,
                priority=rule.priority,
                rule_type=rule.rule_type,
                match_type=rule.match_type,
                pattern=rule.pattern,
                replacement=rule.replacement,
                case_sensitive=rule.case_sensitive,
                whole_word=rule.whole_word,
                use_regex=rule.use_regex,
                source_channel_ids=rule.source_channel_ids,
                target_channel_ids=rule.target_channel_ids,
                message_types=rule.message_types,
                action=rule.action,
                stop_processing=rule.stop_processing,
                group_id=rule.group_id,
                hit_count=0,
                created_by=created_by,
            )
            session.add(copy)
            await session.commit()
            await session.refresh(copy)
            return copy

    async def test_payload(
        self,
        data: dict[str, Any],
        sample_text: str,
        *,
        sample_media_type: str | None = None,
        sample_media_count: int = 0,
    ) -> dict[str, Any]:
        definition = self._definition_from_payload(data)
        return preview_rule(
            definition,
            sample_text,
            sample_media_type=sample_media_type,
            sample_media_count=sample_media_count,
        )

    async def test_existing(
        self,
        rule_id: int,
        sample_text: str,
        *,
        sample_media_type: str | None = None,
        sample_media_count: int = 0,
    ) -> dict[str, Any]:
        async with self.session_factory() as session:
            rule = await session.get(KeywordRule, rule_id)
            if rule is None:
                raise RulesServiceError("rule not found", code="not_found")
            return preview_rule(
                rule_row_to_definition(rule),
                sample_text,
                sample_media_type=sample_media_type,
                sample_media_count=sample_media_count,
            )

    async def export_rules(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(KeywordRule).order_by(
                            KeywordRule.priority.asc(), KeywordRule.id.asc()
                        )
                    )
                ).scalars()
            )
            return [
                {
                    "name": r.name,
                    "description": r.description,
                    "enabled": r.enabled,
                    "priority": r.priority,
                    "rule_type": r.rule_type,
                    "match_type": r.match_type,
                    "pattern": r.pattern,
                    "replacement": r.replacement,
                    "case_sensitive": r.case_sensitive,
                    "whole_word": r.whole_word,
                    "use_regex": r.use_regex,
                    "source_channel_ids": r.source_channel_ids,
                    "target_channel_ids": r.target_channel_ids,
                    "message_types": r.message_types,
                    "action": r.action,
                    "stop_processing": r.stop_processing,
                    "group_id": r.group_id,
                }
                for r in rows
            ]

    async def import_rules(
        self, items: list[dict[str, Any]], *, created_by: int | None
    ) -> list[KeywordRule]:
        created: list[KeywordRule] = []
        for item in items:
            created.append(await self.create_rule(item, created_by=created_by))
        return created

    async def sync_from_file(self, path: str, *, created_by: int | None = None) -> int:
        """Upsert rules from YAML seed file by unique name. Does not delete extras."""
        items = load_rules_config(path)
        if not items:
            return 0
        count = 0
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            async with self.session_factory() as session:
                existing = (
                    await session.execute(select(KeywordRule).where(KeywordRule.name == name))
                ).scalar_one_or_none()
            if existing is None:
                await self.create_rule(item, created_by=created_by)
            else:
                patch = {k: v for k, v in item.items() if k != "name"}
                await self.update_rule(existing.id, patch)
            count += 1
        logger.info("rules_synced_from_file", count=count, path=path)
        return count

    async def list_groups(self) -> list[RuleGroup]:
        async with self.session_factory() as session:
            return list(
                (
                    await session.execute(select(RuleGroup).order_by(RuleGroup.priority.asc()))
                ).scalars()
            )

    async def create_group(self, data: dict[str, Any]) -> RuleGroup:
        async with self.session_factory() as session:
            existing = await session.execute(
                select(RuleGroup).where(RuleGroup.name == str(data["name"]))
            )
            if existing.scalar_one_or_none() is not None:
                raise RulesServiceError("rule group name already exists", code="conflict")
            group = RuleGroup(
                name=str(data["name"]),
                description=data.get("description"),
                enabled=bool(data.get("enabled", True)),
                priority=int(data.get("priority", 100)),
            )
            session.add(group)
            await session.commit()
            await session.refresh(group)
            return group

    async def update_group(self, group_id: int, data: dict[str, Any]) -> RuleGroup:
        async with self.session_factory() as session:
            group = await session.get(RuleGroup, group_id)
            if group is None:
                raise RulesServiceError("rule group not found", code="not_found")
            if "name" in data and data["name"] != group.name:
                clash = await session.execute(
                    select(RuleGroup).where(RuleGroup.name == str(data["name"]))
                )
                if clash.scalar_one_or_none() is not None:
                    raise RulesServiceError("rule group name already exists", code="conflict")
                group.name = str(data["name"])
            if "description" in data:
                group.description = data["description"]
            if "enabled" in data:
                group.enabled = bool(data["enabled"])
            if "priority" in data:
                group.priority = int(data["priority"])
            await session.commit()
            await session.refresh(group)
            return group

    async def delete_group(self, group_id: int) -> None:
        async with self.session_factory() as session:
            group = await session.get(RuleGroup, group_id)
            if group is None:
                raise RulesServiceError("rule group not found", code="not_found")
            rules = await session.execute(
                select(KeywordRule).where(KeywordRule.group_id == group_id)
            )
            for rule in rules.scalars():
                rule.group_id = None
            await session.delete(group)
            await session.commit()

    async def list_execution_logs(
        self, *, page: int, page_size: int, rule_id: int | None = None
    ) -> tuple[list[RuleExecutionLog], int]:
        async with self.session_factory() as session:
            filters = []
            if rule_id is not None:
                filters.append(RuleExecutionLog.rule_id == rule_id)
            count_stmt = select(func.count()).select_from(RuleExecutionLog)
            list_stmt = select(RuleExecutionLog).order_by(RuleExecutionLog.id.desc())
            if filters:
                count_stmt = count_stmt.where(*filters)
                list_stmt = list_stmt.where(*filters)
            total = int((await session.execute(count_stmt)).scalar_one())
            rows = list(
                (
                    await session.execute(list_stmt.offset((page - 1) * page_size).limit(page_size))
                ).scalars()
            )
            return rows, total

    async def persist_hits(
        self,
        session: AsyncSession,
        hits: list[dict[str, object]],
        *,
        review_task_id: int | None = None,
        processed_message_id: int | None = None,
        bump_counts: bool = True,
    ) -> None:
        for hit in hits:
            if hit.get("error"):
                continue
            rule_id = hit.get("rule_id")
            match_start = hit.get("match_start")
            match_end = hit.get("match_end")
            duration_ms = hit.get("duration_ms")
            session.add(
                RuleExecutionLog(
                    processed_message_id=processed_message_id,
                    review_task_id=review_task_id,
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
            if bump_counts and isinstance(rule_id, int):
                rule = await session.get(KeywordRule, rule_id)
                if rule is not None:
                    rule.hit_count += 1
                    rule.last_hit_at = datetime.now(UTC)

    async def apply_enabled(
        self,
        text: str,
        *,
        source_chat_id: int | None = None,
        target_chat_id: int | None = None,
        media_type: str | None = None,
    ) -> RuleApplyResult:
        async with self.session_factory() as session:
            rules = await load_enabled_rules(session)
        return apply_rules(
            text,
            rules,
            source_chat_id=source_chat_id,
            target_chat_id=target_chat_id,
            media_type=media_type,
        )
