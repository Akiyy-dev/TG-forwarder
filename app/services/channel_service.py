"""Source channel configuration service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.repositories.channel_repo import ChannelRepository
from app.logging import get_logger
from app.schemas.channel import SourceChannelConfig

logger = get_logger(__name__)


def parse_channel_ref(ref: str) -> str | int:
    value = ref.strip()
    if value.startswith("@"):
        return value
    if value.lstrip("-").isdigit():
        return int(value)
    return value


class ChannelService:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self._enabled_ids: set[int] = set()
        self._configs: dict[int, SourceChannelConfig] = {}

    @property
    def enabled_chat_ids(self) -> set[int]:
        return set(self._enabled_ids)

    def get_target_for(self, source_chat_id: int) -> int:
        cfg = self._configs.get(source_chat_id)
        if cfg and cfg.target_channel_id is not None:
            return cfg.target_channel_id
        return self.settings.target_channel_id

    async def sync_from_settings(
        self,
        resolved: list[tuple[int, str | None, str | None]],
    ) -> None:
        """Persist resolved channels from env into DB and memory cache."""
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            for chat_id, username, title in resolved:
                await repo.upsert(
                    chat_id=chat_id,
                    username=username,
                    title=title,
                    enabled=True,
                    target_channel_id=self.settings.target_channel_id,
                )
            await session.commit()
            channels = await repo.list_all()

        self._configs = {
            ch.chat_id: SourceChannelConfig(
                chat_id=ch.chat_id,
                username=ch.username,
                title=ch.title,
                enabled=ch.enabled,
                target_channel_id=ch.target_channel_id,
                processing_profile=ch.processing_profile,
                created_at=ch.created_at,
                updated_at=ch.updated_at,
            )
            for ch in channels
        }
        self._enabled_ids = {ch.chat_id for ch in channels if ch.enabled}
        logger.info(
            "channels_synced",
            count=len(self._enabled_ids),
        )

    async def load_from_db(self) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            channels = await repo.list_all()
        self._configs = {
            ch.chat_id: SourceChannelConfig(
                chat_id=ch.chat_id,
                username=ch.username,
                title=ch.title,
                enabled=ch.enabled,
                target_channel_id=ch.target_channel_id,
                processing_profile=ch.processing_profile,
            )
            for ch in channels
        }
        self._enabled_ids = {cid for cid, cfg in self._configs.items() if cfg.enabled}

    async def list_sources(self) -> list[SourceChannelConfig]:
        return list(self._configs.values())
