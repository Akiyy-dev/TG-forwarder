"""Database constraint tests."""

from __future__ import annotations

from app.database.repositories.message_repo import MessageRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_unique_source_message_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        repo = MessageRepository(session)
        first = await repo.try_create(source_chat_id=-1001, source_message_id=42)
        second = await repo.try_create(source_chat_id=-1001, source_message_id=42)
        await session.commit()
    assert first is not None
    assert second is None
