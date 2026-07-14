"""App settings repository for runtime flags."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import AppSetting


class SettingsRepository:
    PAUSED_KEY = "publishing_paused"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> Any | None:
        result = await self._session.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        return None if row is None else row.value

    async def set(self, key: str, value: Any) -> AppSetting:
        result = await self._session.execute(select(AppSetting).where(AppSetting.key == key))
        row = result.scalar_one_or_none()
        if row is None:
            row = AppSetting(key=key, value=value)
            self._session.add(row)
        else:
            row.value = value
        await self._session.flush()
        return row

    async def is_paused(self) -> bool:
        value = await self.get(self.PAUSED_KEY)
        if isinstance(value, dict):
            return bool(value.get("paused", False))
        return bool(value)

    async def set_paused(self, paused: bool) -> None:
        await self.set(self.PAUSED_KEY, {"paused": paused})
