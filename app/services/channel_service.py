"""Source/target channel configuration service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.models import SourceChannel, TargetChannel
from app.database.repositories.channel_repo import ChannelRepository
from app.logging import get_logger
from app.schemas.channel import PublishMode, SourceChannelConfig

logger = get_logger(__name__)


def parse_channel_ref(ref: str) -> str | int:
    value = ref.strip()
    if value.startswith("@"):
        return value
    if value.lstrip("-").isdigit():
        return int(value)
    return value


class ChannelServiceError(Exception):
    def __init__(self, message: str, *, code: str = "channel_error") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


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

    def get_publish_mode(self, source_chat_id: int) -> PublishMode:
        cfg = self._configs.get(source_chat_id)
        if cfg is None:
            return PublishMode.REVIEW
        return cfg.publish_mode

    def _row_to_config(self, ch: SourceChannel) -> SourceChannelConfig:
        try:
            mode = PublishMode(ch.publish_mode)
        except ValueError:
            mode = PublishMode.REVIEW
        return SourceChannelConfig(
            chat_id=ch.chat_id,
            username=ch.username,
            title=ch.title,
            enabled=ch.enabled,
            publish_mode=mode,
            target_channel_id=ch.target_channel_id,
            processing_profile=ch.processing_profile,
            created_at=ch.created_at,
            updated_at=ch.updated_at,
        )

    def _apply_cache(self, channels: list[SourceChannel]) -> None:
        self._configs = {ch.chat_id: self._row_to_config(ch) for ch in channels}
        self._enabled_ids = {ch.chat_id for ch in channels if ch.enabled}

    async def sync_from_settings(
        self,
        resolved: list[tuple[int, str | None, str | None]],
    ) -> None:
        """Persist resolved channels from env into DB and memory cache."""
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            for chat_id, username, title in resolved:
                existing = await repo.get_by_chat_id(chat_id)
                await repo.upsert(
                    chat_id=chat_id,
                    username=username,
                    title=title,
                    enabled=True if existing is None else existing.enabled,
                    target_channel_id=(
                        self.settings.target_channel_id
                        if existing is None or existing.target_channel_id is None
                        else existing.target_channel_id
                    ),
                    publish_mode=None if existing is not None else PublishMode.REVIEW,
                )
            await session.commit()
            channels = await repo.list_all()

        self._apply_cache(channels)
        logger.info("channels_synced", count=len(self._enabled_ids))

    async def load_from_db(self) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            channels = await repo.list_all()
        self._apply_cache(channels)

    async def list_sources(self) -> list[SourceChannelConfig]:
        return list(self._configs.values())

    async def list_sources_paginated(
        self,
        *,
        page: int,
        page_size: int,
        enabled: bool | None = None,
        publish_mode: str | None = None,
        q: str | None = None,
    ) -> tuple[list[SourceChannel], int]:
        async with self.session_factory() as session:
            count_stmt = select(func.count()).select_from(SourceChannel)
            list_stmt = select(SourceChannel).order_by(SourceChannel.id.asc())
            if enabled is not None:
                count_stmt = count_stmt.where(SourceChannel.enabled.is_(enabled))
                list_stmt = list_stmt.where(SourceChannel.enabled.is_(enabled))
            if publish_mode is not None:
                count_stmt = count_stmt.where(SourceChannel.publish_mode == publish_mode)
                list_stmt = list_stmt.where(SourceChannel.publish_mode == publish_mode)
            if q:
                like = f"%{q}%"
                from sqlalchemy import or_

                clause = or_(
                    SourceChannel.title.like(like),
                    SourceChannel.username.like(like),
                )
                count_stmt = count_stmt.where(clause)
                list_stmt = list_stmt.where(clause)
            total = int((await session.execute(count_stmt)).scalar_one())
            rows = list(
                (
                    await session.execute(list_stmt.offset((page - 1) * page_size).limit(page_size))
                ).scalars()
            )
            return rows, total

    async def get_source(self, source_id: int) -> SourceChannel:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            channel = await repo.get_by_id(source_id)
            if channel is None:
                raise ChannelServiceError("source channel not found", code="not_found")
            return channel

    async def create_source(self, data: dict[str, Any]) -> SourceChannel:
        chat_id = int(data["chat_id"])
        mode = PublishMode(data.get("publish_mode", PublishMode.REVIEW))
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            existing = await repo.get_by_chat_id(chat_id)
            if existing is not None:
                raise ChannelServiceError("source channel already exists", code="conflict")
            channel = await repo.upsert(
                chat_id=chat_id,
                username=data.get("username"),
                title=data.get("title"),
                enabled=bool(data.get("enabled", True)),
                target_channel_id=data.get("target_channel_id"),
                processing_profile=str(data.get("processing_profile") or "default"),
                publish_mode=mode,
            )
            await session.commit()
            await session.refresh(channel)
            channel_id = channel.id
        await self.load_from_db()
        return await self.get_source(channel_id)

    async def update_source(self, source_id: int, data: dict[str, Any]) -> SourceChannel:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            channel = await repo.get_by_id(source_id)
            if channel is None:
                raise ChannelServiceError("source channel not found", code="not_found")
            if "username" in data:
                channel.username = data["username"]
            if "title" in data:
                channel.title = data["title"]
            if "enabled" in data:
                channel.enabled = bool(data["enabled"])
            if "publish_mode" in data and data["publish_mode"] is not None:
                try:
                    channel.publish_mode = PublishMode(data["publish_mode"]).value
                except ValueError as exc:
                    raise ChannelServiceError(
                        f"invalid publish_mode: {data['publish_mode']}",
                        code="validation_error",
                    ) from exc
            if "target_channel_id" in data:
                channel.target_channel_id = data["target_channel_id"]
            if "processing_profile" in data and data["processing_profile"] is not None:
                channel.processing_profile = str(data["processing_profile"])
            await session.commit()
            await session.refresh(channel)
        await self.load_from_db()
        return await self.get_source(source_id)

    async def delete_source(self, source_id: int) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            deleted = await repo.delete(source_id)
            if not deleted:
                raise ChannelServiceError("source channel not found", code="not_found")
            await session.commit()
        await self.load_from_db()

    async def list_targets(self) -> list[TargetChannel]:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            return await repo.list_targets()

    async def get_target(self, target_id: int) -> TargetChannel:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            return target

    async def create_target(self, data: dict[str, Any]) -> TargetChannel:
        chat_id = int(data["chat_id"])
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            existing = await repo.get_target_by_chat_id(chat_id)
            if existing is not None:
                raise ChannelServiceError("target channel already exists", code="conflict")
            target = await repo.upsert_target(
                chat_id=chat_id,
                username=data.get("username"),
                title=data.get("title"),
                enabled=bool(data.get("enabled", True)),
                default_footer=data.get("default_footer"),
            )
            await session.commit()
            await session.refresh(target)
            return target

    async def update_target(self, target_id: int, data: dict[str, Any]) -> TargetChannel:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            if "username" in data:
                target.username = data["username"]
            if "title" in data:
                target.title = data["title"]
            if "enabled" in data:
                target.enabled = bool(data["enabled"])
            if "default_footer" in data:
                target.default_footer = data["default_footer"]
            await session.commit()
            await session.refresh(target)
            return target

    async def delete_target(self, target_id: int) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            await session.delete(target)
            await session.commit()

    async def check_target_permissions(self, target_id: int, bot: Any) -> dict[str, Any]:
        if bot is None:
            raise ChannelServiceError("bot is not available", code="unavailable")
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            chat_id = target.chat_id

        detail: dict[str, Any]
        status = "ok"
        try:
            me = await bot.get_me()
            member = await bot.get_chat_member(chat_id, me.id)
            can_post = bool(getattr(member, "can_post_messages", False))
            status_name = getattr(getattr(member, "status", None), "value", None) or str(
                getattr(member, "status", "unknown")
            )
            status = "ok" if status_name in {"administrator", "creator"} or can_post else "missing"
            detail = {
                "bot_id": me.id,
                "bot_username": me.username,
                "member_status": status_name,
                "can_post_messages": can_post,
            }
        except Exception as exc:
            status = "error"
            detail = {"error": type(exc).__name__, "message": str(exc)}

        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            target.permission_status = status
            target.permission_detail = detail
            target.last_permission_check_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(target)
            return {
                "target_id": target.id,
                "chat_id": target.chat_id,
                "permission_status": target.permission_status,
                "permission_detail": target.permission_detail,
                "last_permission_check_at": (
                    target.last_permission_check_at.isoformat()
                    if target.last_permission_check_at
                    else None
                ),
            }

    async def send_target_test_message(self, target_id: int, bot: Any, text: str) -> dict[str, Any]:
        if bot is None:
            raise ChannelServiceError("bot is not available", code="unavailable")
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            if not target.enabled:
                raise ChannelServiceError("target channel is disabled", code="invalid_state")
            chat_id = target.chat_id
        try:
            sent = await bot.send_message(chat_id, text)
        except Exception as exc:
            raise ChannelServiceError(
                f"failed to send test message: {exc}", code="publish_failed"
            ) from exc
        message_id = getattr(sent, "message_id", None)
        return {"chat_id": chat_id, "message_id": message_id, "text": text}
