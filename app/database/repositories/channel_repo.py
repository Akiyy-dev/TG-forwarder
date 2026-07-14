"""Source and target channel repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SourceChannel, TargetChannel
from app.schemas.channel import PublishMode


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
        publish_mode: str | PublishMode | None = None,
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
                publish_mode=(
                    PublishMode(publish_mode).value
                    if publish_mode is not None
                    else PublishMode.REVIEW.value
                ),
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
            if publish_mode is not None:
                channel.publish_mode = PublishMode(publish_mode).value
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

    async def get_by_id(self, source_id: int) -> SourceChannel | None:
        return await self._session.get(SourceChannel, source_id)

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

    async def delete(self, source_id: int) -> bool:
        channel = await self.get_by_id(source_id)
        if channel is None:
            return False
        await self._session.delete(channel)
        await self._session.flush()
        return True

    async def list_targets(self) -> list[TargetChannel]:
        result = await self._session.execute(select(TargetChannel).order_by(TargetChannel.id))
        return list(result.scalars().all())

    async def get_target_by_id(self, target_id: int) -> TargetChannel | None:
        return await self._session.get(TargetChannel, target_id)

    async def get_target_by_chat_id(self, chat_id: int) -> TargetChannel | None:
        result = await self._session.execute(
            select(TargetChannel).where(TargetChannel.chat_id == chat_id)
        )
        return result.scalar_one_or_none()

    async def upsert_target(
        self,
        *,
        chat_id: int,
        username: str | None = None,
        title: str | None = None,
        enabled: bool = True,
        default_footer: str | None = None,
    ) -> TargetChannel:
        target = await self.get_target_by_chat_id(chat_id)
        if target is None:
            target = TargetChannel(
                chat_id=chat_id,
                username=username,
                title=title,
                enabled=enabled,
                default_footer=default_footer,
                permission_status="unknown",
            )
            self._session.add(target)
        else:
            if username is not None:
                target.username = username
            if title is not None:
                target.title = title
            target.enabled = enabled
            if default_footer is not None:
                target.default_footer = default_footer
        await self._session.flush()
        return target
