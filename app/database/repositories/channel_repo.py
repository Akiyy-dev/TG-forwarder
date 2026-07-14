"""Source channel repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SourceChannel


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        chat_id: int,
        username: str | None = None,
        title: str | None = None,
        enabled: bool = True,
        target_channel_id: int | None = None,
        processing_profile: str = "default",
    ) -> SourceChannel:
        result = await self._session.execute(
            select(SourceChannel).where(SourceChannel.chat_id == chat_id)
        )
        channel = result.scalar_one_or_none()
        if channel is None:
            channel = SourceChannel(
                chat_id=chat_id,
                username=username,
                title=title,
                enabled=enabled,
                target_channel_id=target_channel_id,
                processing_profile=processing_profile,
            )
            self._session.add(channel)
        else:
            channel.username = username if username is not None else channel.username
            channel.title = title if title is not None else channel.title
            channel.enabled = enabled
            if target_channel_id is not None:
                channel.target_channel_id = target_channel_id
            channel.processing_profile = processing_profile
        await self._session.flush()
        return channel

    async def list_all(self) -> list[SourceChannel]:
        result = await self._session.execute(select(SourceChannel).order_by(SourceChannel.id))
        return list(result.scalars().all())

    async def list_enabled(self) -> list[SourceChannel]:
        result = await self._session.execute(
            select(SourceChannel).where(SourceChannel.enabled.is_(True))
        )
        return list(result.scalars().all())

    async def get_by_chat_id(self, chat_id: int) -> SourceChannel | None:
        result = await self._session.execute(
            select(SourceChannel).where(SourceChannel.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def set_enabled(self, chat_id: int, enabled: bool) -> SourceChannel | None:
        channel = await self.get_by_chat_id(chat_id)
        if channel is None:
            return None
        channel.enabled = enabled
        await self._session.flush()
        return channel
