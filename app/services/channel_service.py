"""Source/target channel configuration service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.database.models import SourceChannel, SourceTargetLink, TargetChannel
from app.database.repositories.channel_repo import ChannelRepository
from app.logging import get_logger
from app.schemas.channel import PublishMode, SourceChannelConfig
from app.services.telegram_account import check_channel_accessible, list_broadcast_channels

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
        self._source_by_id: dict[int, int] = {}
        self._target_titles: dict[int, str] = {}

    @property
    def enabled_chat_ids(self) -> set[int]:
        return set(self._enabled_ids)

    @property
    def configured_chat_ids(self) -> set[int]:
        return set(self._configs)

    def is_enabled(self, chat_id: int) -> bool:
        return chat_id in self._enabled_ids

    def get_target_for(self, source_chat_id: int) -> int:
        targets = self.get_targets_for(source_chat_id)
        if targets:
            return targets[0]
        return self.settings.target_channel_id

    def get_targets_for(self, source_chat_id: int) -> list[int]:
        cfg = self._configs.get(source_chat_id)
        if cfg and cfg.target_chat_ids:
            return list(cfg.target_chat_ids)
        if cfg and cfg.target_channel_id is not None:
            return [cfg.target_channel_id]
        return [self.settings.target_channel_id]

    def display_name(self, chat_id: int) -> str:
        cfg = self._configs.get(chat_id)
        if cfg:
            return cfg.title or (f"@{cfg.username}" if cfg.username else str(chat_id))
        if chat_id in self._target_titles:
            return self._target_titles[chat_id]
        return str(chat_id)

    def get_publish_mode(self, source_chat_id: int) -> PublishMode:
        cfg = self._configs.get(source_chat_id)
        if cfg is None:
            return PublishMode.REVIEW
        return cfg.publish_mode

    def _row_to_config(
        self,
        ch: SourceChannel,
        *,
        target_chat_ids: list[int] | None = None,
    ) -> SourceChannelConfig:
        try:
            mode = PublishMode(ch.publish_mode)
        except ValueError:
            mode = PublishMode.REVIEW
        ids = target_chat_ids
        if ids is None and ch.target_channel_id is not None:
            ids = [ch.target_channel_id]
        return SourceChannelConfig(
            id=ch.id,
            chat_id=ch.chat_id,
            username=ch.username,
            title=ch.title,
            enabled=ch.enabled,
            publish_mode=mode,
            target_channel_id=ids[0] if ids else ch.target_channel_id,
            target_chat_ids=ids,
            access_status=getattr(ch, "access_status", "unknown") or "unknown",
            processing_profile=ch.processing_profile,
            created_at=ch.created_at,
            updated_at=ch.updated_at,
        )

    async def _load_target_map(self, session: AsyncSession) -> dict[int, list[int]]:
        """source_id -> list of target telegram chat_ids."""
        links = (
            await session.execute(
                select(SourceTargetLink, TargetChannel.chat_id).join(
                    TargetChannel, SourceTargetLink.target_id == TargetChannel.id
                )
            )
        ).all()
        mapping: dict[int, list[int]] = {}
        for link, chat_id in links:
            mapping.setdefault(int(link.source_id), []).append(int(chat_id))
        return mapping

    def _apply_cache(
        self,
        channels: list[SourceChannel],
        target_map: dict[int, list[int]] | None = None,
        targets: list[TargetChannel] | None = None,
    ) -> None:
        target_map = target_map or {}
        self._configs = {
            ch.chat_id: self._row_to_config(ch, target_chat_ids=target_map.get(ch.id))
            for ch in channels
        }
        self._enabled_ids = {ch.chat_id for ch in channels if ch.enabled}
        self._source_by_id = {ch.id: ch.chat_id for ch in channels}
        if targets is not None:
            self._target_titles = {
                t.chat_id: (t.title or (f"@{t.username}" if t.username else str(t.chat_id)))
                for t in targets
            }

    async def load_from_db(self) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            channels = await repo.list_all()
            targets = await repo.list_targets()
            target_map = await self._load_target_map(session)
        self._apply_cache(channels, target_map, targets)

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
        await self.load_from_db()
        logger.info("channels_synced", count=len(self._enabled_ids))

    async def sync_from_config_rows(self, rows: list[dict[str, Any]]) -> int:
        """Upsert channels from resolved config-file rows.

        Expected keys: chat_id, username?, title?, enabled?, publish_mode?, target_chat_id?
        """
        if not rows:
            return 0
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            for row in rows:
                chat_id = int(row["chat_id"])
                existing = await repo.get_by_chat_id(chat_id)
                mode = row.get("publish_mode")
                enabled = row.get("enabled")
                await repo.upsert(
                    chat_id=chat_id,
                    username=row.get("username"),
                    title=row.get("title"),
                    enabled=(
                        bool(enabled)
                        if enabled is not None
                        else (True if existing is None else existing.enabled)
                    ),
                    target_channel_id=(
                        int(row["target_chat_id"])
                        if row.get("target_chat_id") is not None
                        else (
                            self.settings.target_channel_id
                            if existing is None or existing.target_channel_id is None
                            else existing.target_channel_id
                        )
                    ),
                    publish_mode=(
                        None if existing is not None else (mode or PublishMode.REVIEW.value)
                    ),
                )
            await session.commit()
        await self.load_from_db()
        logger.info("channels_synced_from_file", count=len(rows))
        return len(rows)

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

    async def create_source(self, data: dict[str, Any], *, client: Any = None) -> SourceChannel:
        chat_id = int(data["chat_id"])
        mode = PublishMode(data.get("publish_mode", PublishMode.REVIEW))
        access = await self._resolve_access(
            client,
            chat_id=chat_id,
            username=data.get("username"),
        )
        want_enabled = bool(data.get("enabled", True))
        # Only force-disable when Telethon confirmed the channel is unreachable.
        if want_enabled and access["status"] == "missing":
            want_enabled = False
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            existing = await repo.get_by_chat_id(chat_id)
            if existing is not None:
                raise ChannelServiceError("source channel already exists", code="conflict")
            channel = await repo.upsert(
                chat_id=chat_id,
                username=data.get("username") or access.get("username"),
                title=data.get("title") or access.get("title"),
                enabled=want_enabled,
                target_channel_id=data.get("target_channel_id"),
                processing_profile=str(data.get("processing_profile") or "default"),
                publish_mode=mode,
                access_status=access["status"],
            )
            target_ids = data.get("target_ids") or data.get("target_chat_ids")
            if target_ids and data.get("target_channel_id") is None:
                primary = await self._resolve_target_chat_ids(session, target_ids)
                if primary:
                    channel.target_channel_id = primary[0]
            await session.commit()
            await session.refresh(channel)
            channel_id = channel.id
            if channel.target_channel_id is not None and not target_ids:
                tgt = await repo.get_target_by_chat_id(channel.target_channel_id)
                if tgt is not None:
                    session.add(SourceTargetLink(source_id=channel_id, target_id=tgt.id))
                    await session.commit()
            elif target_ids:
                await self._replace_source_links(session, channel_id, list(target_ids))
                await session.commit()
        await self.load_from_db()
        return await self.get_source(channel_id)

    async def update_source(
        self, source_id: int, data: dict[str, Any], *, client: Any = None
    ) -> SourceChannel:
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
                want = bool(data["enabled"])
                if want and (channel.access_status or "unknown") == "missing":
                    # Re-verify if client available
                    access = await self._resolve_access(
                        client,
                        chat_id=channel.chat_id,
                        username=channel.username,
                    )
                    channel.access_status = access["status"]
                    if access["status"] == "missing":
                        raise ChannelServiceError(
                            "channel is not accessible; cannot enable",
                            code="not_accessible",
                        )
                channel.enabled = want
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
                if data["target_channel_id"] is not None:
                    tgt = await repo.get_target_by_chat_id(int(data["target_channel_id"]))
                    if tgt is not None:
                        await self._replace_source_links(session, source_id, [tgt.id])
            if "processing_profile" in data and data["processing_profile"] is not None:
                channel.processing_profile = str(data["processing_profile"])
            if "access_status" in data and data["access_status"] is not None:
                channel.access_status = str(data["access_status"])
            await session.commit()
            await session.refresh(channel)
        await self.load_from_db()
        return await self.get_source(source_id)

    async def create_target(self, data: dict[str, Any], *, client: Any = None) -> TargetChannel:
        chat_id = int(data["chat_id"])
        access = await self._resolve_access(
            client,
            chat_id=chat_id,
            username=data.get("username"),
        )
        want_enabled = bool(data.get("enabled", True))
        if want_enabled and access["status"] == "missing":
            want_enabled = False
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            existing = await repo.get_target_by_chat_id(chat_id)
            if existing is not None:
                raise ChannelServiceError("target channel already exists", code="conflict")
            target = await repo.upsert_target(
                chat_id=chat_id,
                username=data.get("username") or access.get("username"),
                title=data.get("title") or access.get("title"),
                enabled=want_enabled,
                default_footer=data.get("default_footer"),
                access_status=access["status"],
            )
            await session.commit()
            await session.refresh(target)
            tid = target.id
        await self.load_from_db()
        return await self.get_target(tid)

    async def update_target(
        self, target_id: int, data: dict[str, Any], *, client: Any = None
    ) -> TargetChannel:
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
                want = bool(data["enabled"])
                if want and (target.access_status or "unknown") == "missing":
                    access = await self._resolve_access(
                        client,
                        chat_id=target.chat_id,
                        username=target.username,
                    )
                    target.access_status = access["status"]
                    if access["status"] == "missing":
                        raise ChannelServiceError(
                            "channel is not accessible; cannot enable",
                            code="not_accessible",
                        )
                target.enabled = want
            if "default_footer" in data:
                target.default_footer = data["default_footer"]
            if "access_status" in data and data["access_status"] is not None:
                target.access_status = str(data["access_status"])
            await session.commit()
            await session.refresh(target)
            tid = target.id
        await self.load_from_db()
        return await self.get_target(tid)

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

    async def delete_target(self, target_id: int) -> None:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            await session.delete(target)
            await session.commit()
        await self.load_from_db()

    async def _resolve_access(
        self,
        client: Any,
        *,
        chat_id: int | None = None,
        username: str | None = None,
    ) -> dict[str, Any]:
        if client is None:
            return {"status": "unknown", "username": username, "title": None}
        result = await check_channel_accessible(client, chat_id=chat_id, username=username)
        status = "ok" if result.get("accessible") else "missing"
        return {
            "status": status,
            "username": result.get("username") or username,
            "title": result.get("title"),
            "chat_id": result.get("chat_id") or chat_id,
            "error": result.get("error"),
        }

    async def _resolve_target_db_ids(self, session: AsyncSession, ids: list[int]) -> list[int]:
        """Accept target DB ids or telegram chat_ids; return target DB ids."""
        repo = ChannelRepository(session)
        out: list[int] = []
        for raw in ids:
            tid = int(raw)
            by_id = await repo.get_target_by_id(tid)
            if by_id is not None:
                out.append(by_id.id)
                continue
            by_chat = await repo.get_target_by_chat_id(tid)
            if by_chat is not None:
                out.append(by_chat.id)
        return out

    async def _resolve_target_chat_ids(self, session: AsyncSession, ids: list[int]) -> list[int]:
        repo = ChannelRepository(session)
        out: list[int] = []
        for raw in ids:
            tid = int(raw)
            by_id = await repo.get_target_by_id(tid)
            if by_id is not None:
                out.append(by_id.chat_id)
                continue
            by_chat = await repo.get_target_by_chat_id(tid)
            if by_chat is not None:
                out.append(by_chat.chat_id)
        return out

    async def _replace_source_links(
        self, session: AsyncSession, source_id: int, target_refs: list[int]
    ) -> list[int]:
        """Replace links for source; refs are DB/chat ids. Returns telegram chat_ids."""
        target_db_ids = await self._resolve_target_db_ids(session, target_refs)
        existing = (
            (
                await session.execute(
                    select(SourceTargetLink).where(SourceTargetLink.source_id == source_id)
                )
            )
            .scalars()
            .all()
        )
        for link in existing:
            await session.delete(link)
        await session.flush()
        chat_ids: list[int] = []
        repo = ChannelRepository(session)
        for tid in target_db_ids:
            session.add(SourceTargetLink(source_id=source_id, target_id=tid))
            tgt = await repo.get_target_by_id(tid)
            if tgt is not None:
                chat_ids.append(tgt.chat_id)
        await session.flush()
        # Keep legacy column as first target
        source = await repo.get_by_id(source_id)
        if source is not None:
            source.target_channel_id = chat_ids[0] if chat_ids else None
        return chat_ids

    async def set_source_targets(self, source_id: int, target_ids: list[int]) -> list[int]:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            source = await repo.get_by_id(source_id)
            if source is None:
                raise ChannelServiceError("source channel not found", code="not_found")
            chat_ids = await self._replace_source_links(session, source_id, target_ids)
            await session.commit()
        await self.load_from_db()
        return chat_ids

    async def set_target_sources(self, target_id: int, source_ids: list[int]) -> list[int]:
        async with self.session_factory() as session:
            repo = ChannelRepository(session)
            target = await repo.get_target_by_id(target_id)
            if target is None:
                raise ChannelServiceError("target channel not found", code="not_found")
            wanted = set()
            for raw in source_ids:
                sid = int(raw)
                by_id = await repo.get_by_id(sid)
                if by_id is not None:
                    wanted.add(by_id.id)
                    continue
                by_chat = await repo.get_by_chat_id(sid)
                if by_chat is not None:
                    wanted.add(by_chat.id)
            existing = (
                (
                    await session.execute(
                        select(SourceTargetLink).where(SourceTargetLink.target_id == target_id)
                    )
                )
                .scalars()
                .all()
            )
            existing_source_ids = {link.source_id for link in existing}
            for link in existing:
                if link.source_id not in wanted:
                    await session.delete(link)
            for sid in wanted - existing_source_ids:
                session.add(SourceTargetLink(source_id=sid, target_id=target_id))
            await session.flush()
            # Refresh legacy primary for affected sources
            for sid in wanted | existing_source_ids:
                links = (
                    await session.execute(
                        select(SourceTargetLink, TargetChannel.chat_id)
                        .join(TargetChannel, SourceTargetLink.target_id == TargetChannel.id)
                        .where(SourceTargetLink.source_id == sid)
                    )
                ).all()
                source = await repo.get_by_id(sid)
                if source is not None:
                    chat_ids = [int(cid) for _, cid in links]
                    source.target_channel_id = chat_ids[0] if chat_ids else None
            await session.commit()
            result_source_ids = sorted(wanted)
        await self.load_from_db()
        return result_source_ids

    async def get_linked_target_ids(self, source_id: int) -> list[int]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SourceTargetLink.target_id).where(
                            SourceTargetLink.source_id == source_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [int(x) for x in rows]

    async def get_linked_source_ids(self, target_id: int) -> list[int]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SourceTargetLink.source_id).where(
                            SourceTargetLink.target_id == target_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return [int(x) for x in rows]

    async def list_account_channels(self, client: Any) -> list[dict[str, Any]]:
        if client is None:
            raise ChannelServiceError("telegram client unavailable", code="unavailable")
        return await list_broadcast_channels(client)

    async def refresh_channels(self, client: Any) -> dict[str, Any]:
        """Re-read YAML config and rescan account dialogs for access_status."""
        from app.config_files import load_channels_config

        yaml_count = 0
        path = self.settings.channels_config_path
        raw = load_channels_config(path)
        if raw and client is not None:
            rows: list[dict[str, Any]] = []
            for entry in raw:
                chat_id = entry.get("chat_id")
                username = entry.get("username")
                title = entry.get("title")
                if chat_id is None:
                    ref = username or entry.get("ref")
                    if not ref:
                        continue
                    access = await self._resolve_access(
                        client,
                        username=str(ref),
                    )
                    if not access.get("chat_id"):
                        continue
                    chat_id = int(access["chat_id"])
                    username = access.get("username") or username
                    title = title or access.get("title")
                else:
                    chat_id = int(chat_id)
                rows.append(
                    {
                        "chat_id": chat_id,
                        "username": username,
                        "title": title,
                        "enabled": entry.get("enabled"),
                        "publish_mode": entry.get("publish_mode"),
                        "target_chat_id": entry.get("target_chat_id"),
                    }
                )
            yaml_count = await self.sync_from_config_rows(rows)

        updated = 0
        account_items: list[dict[str, Any]] = []
        if client is not None:
            account_items = await list_broadcast_channels(client)
            accessible_ids = {int(i["chat_id"]) for i in account_items}
            async with self.session_factory() as session:
                repo = ChannelRepository(session)
                for ch in await repo.list_all():
                    status = "ok" if ch.chat_id in accessible_ids else "missing"
                    if ch.access_status != status:
                        ch.access_status = status
                        updated += 1
                    if status != "ok" and ch.enabled:
                        ch.enabled = False
                for t in await repo.list_targets():
                    status = "ok" if t.chat_id in accessible_ids else "missing"
                    if t.access_status != status:
                        t.access_status = status
                        updated += 1
                    if status != "ok" and t.enabled:
                        t.enabled = False
                await session.commit()
            await self.load_from_db()

        return {
            "yaml_upserted": yaml_count,
            "access_updated": updated,
            "account_channels": len(account_items),
        }

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
