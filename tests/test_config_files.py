"""Config file seed loading tests."""

from __future__ import annotations

from pathlib import Path

from app.config_files import load_channels_config, load_rules_config
from app.database.models import KeywordRule
from app.rules.types import RuleType
from app.services.rules_service import RulesService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_load_channels_and_rules_yaml(tmp_path: Path) -> None:
    channels = tmp_path / "channels.yaml"
    channels.write_text(
        "channels:\n  - chat_id: -1001\n    publish_mode: review\n    enabled: true\n",
        encoding="utf-8",
    )
    rules = tmp_path / "rules.yaml"
    rules.write_text(
        "rules:\n"
        "  - name: media-gate\n"
        "    rule_type: has_media\n"
        "    pattern: has\n"
        "    action: require_review\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    ch = load_channels_config(channels)
    assert len(ch) == 1
    assert ch[0]["chat_id"] == -1001
    rs = load_rules_config(rules)
    assert rs[0]["rule_type"] == "has_media"


async def test_rules_sync_from_file_upsert(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        "rules:\n"
        "  - name: seed-media\n"
        "    rule_type: has_media\n"
        "    pattern: has\n"
        "    action: require_review\n"
        "    priority: 20\n"
        "    enabled: true\n",
        encoding="utf-8",
    )
    svc = RulesService(session_factory)
    assert await svc.sync_from_file(str(path)) == 1
    assert await svc.sync_from_file(str(path)) == 1  # upsert again

    async with session_factory() as session:
        row = (
            await session.execute(select(KeywordRule).where(KeywordRule.name == "seed-media"))
        ).scalar_one()
        assert row.rule_type == RuleType.HAS_MEDIA.value
        assert row.pattern == "has"
        assert row.priority == 20
