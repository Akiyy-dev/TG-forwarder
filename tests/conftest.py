"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.config import Settings, clear_settings_cache
from app.database.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Settings:
    clear_settings_cache()
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TELEGRAM_API_ID", "12345")
    monkeypatch.setenv("TELEGRAM_API_HASH", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("BOT_TOKEN", "123456:TESTTOKEN_abcdefghijklmnop")
    monkeypatch.setenv("BOT_ADMIN_IDS", "111,222")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setenv("TEXT_REPLACEMENTS", "Foo=>Bar|old=>new")
    monkeypatch.setenv("MESSAGE_FOOTER", "— via TG-forwarder")
    monkeypatch.setenv("WEB_ENABLED", "true")
    monkeypatch.setenv("WEB_SECRET_KEY", "test-secret-key-please-change")
    monkeypatch.setenv("WEB_DOCS_ENABLED", "true")
    clear_settings_cache()
    from app.config import Settings as SettingsCls

    return SettingsCls()  # type: ignore[call-arg]


@pytest_asyncio.fixture
async def session_factory(tmp_path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    db_path = tmp_path / "unit.db"
    url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()
