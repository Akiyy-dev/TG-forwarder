"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _ensure_sqlite_parent(database_url: str) -> None:
    if "sqlite" not in database_url:
        return
    marker = ":///"
    idx = database_url.find(marker)
    if idx < 0:
        return
    raw = database_url[idx + len(marker) :]
    path = Path(raw)
    if path.parent and str(path.parent) not in (".", ""):
        path.parent.mkdir(parents=True, exist_ok=True)


def _apply_sqlite_pragmas(dbapi_conn: object, _connection_record: object) -> None:
    cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine(database_url: str) -> AsyncEngine:
    _ensure_sqlite_parent(database_url)
    is_sqlite = "sqlite" in database_url
    connect_args: dict[str, object] = {}
    kwargs: dict[str, object] = {"echo": False}
    if is_sqlite:
        connect_args["check_same_thread"] = False
        # In-memory / test DBs share one connection via StaticPool when needed
        if ":memory:" in database_url:
            kwargs["poolclass"] = StaticPool
    engine = create_async_engine(database_url, connect_args=connect_args, **kwargs)
    if is_sqlite:
        event.listen(engine.sync_engine, "connect", _apply_sqlite_pragmas)
    return engine


def init_engine(database_url: str) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _engine is not None:
        return _session_factory  # type: ignore[return-value]
    _engine = create_engine(database_url)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _session_factory


def async_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        msg = "Database engine not initialized; call init_engine() first"
        raise RuntimeError(msg)
    return _session_factory


async def init_db(database_url: str) -> async_sessionmaker[AsyncSession]:
    factory = init_engine(database_url)
    assert _engine is not None
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if "sqlite" in database_url:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA busy_timeout=5000"))
    return factory


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    factory = async_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
