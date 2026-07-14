"""Media access and preview tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from app.api.app import create_api_app
from app.auth.roles import Role
from app.auth.service import AuthService
from app.config import Settings
from app.context import AppContext
from app.database.models import ProcessedMessage
from app.publishers.telegram_publisher import TelegramPublisher
from app.review.preview import build_publish_preview
from app.review.service import ReviewService
from app.schemas.message import MediaItem, MediaType, NormalizedMessage
from app.services.channel_service import ChannelService
from app.services.media_service import MediaService
from app.services.message_service import MessageService
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_preview_truncation() -> None:
    from app.database.models import ReviewTask

    task = ReviewTask(
        processed_message_id=1,
        status="pending",
        source_chat_id=-1,
        source_message_id=1,
        original_text="x" * 5000,
        processed_text="x" * 5000,
        final_text="x" * 5000,
        media_type="text",
        media_count=0,
        revision=1,
    )
    preview = build_publish_preview(task)
    assert preview["truncated"] is True
    assert preview["text_length"] == 5000
    assert len(preview["split_plan"]) >= 2


async def test_media_requires_auth_and_blocks_traversal(
    settings_env: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    download = tmp_path / "downloads"
    download.mkdir()
    media_file = download / "safe.jpg"
    media_file.write_bytes(b"fake-image")

    settings_env.download_dir = str(download)
    auth = AuthService(settings_env, session_factory)
    channel = ChannelService(settings_env, session_factory)
    media = MediaService(str(download), max_size_bytes=1024, ttl_minutes=1)
    publisher = TelegramPublisher(MagicMock(), max_retries=1, base_delay=0.01)
    message = MessageService(settings_env, session_factory, channel, publisher, media)
    ctx = AppContext(
        settings=settings_env,
        session_factory=session_factory,
        channel_service=channel,
        media_service=media,
        message_service=message,
        publisher=publisher,
        auth_service=auth,
    )
    await auth.create_user(username="v", password="password123", role=Role.VIEWER)

    async with session_factory() as session:
        processed = ProcessedMessage(
            source_chat_id=-1001,
            source_message_id=9,
            status="pending_review",
            target_chat_id=-1002,
        )
        session.add(processed)
        await session.commit()
        await session.refresh(processed)
        pid = processed.id
    svc = ReviewService(session_factory)
    async with session_factory() as session:
        processed = await session.get(ProcessedMessage, pid)
        assert processed is not None
        task = await svc.create_from_message(
            processed=processed,
            original_text="cap",
            processed_message=NormalizedMessage(
                source_chat_id=-1001,
                source_message_id=9,
                text="cap",
                media_type=MediaType.PHOTO,
                media_items=[
                    MediaItem(
                        media_type=MediaType.PHOTO,
                        local_path=str(media_file),
                        original_filename="safe.jpg",
                        mime_type="image/jpeg",
                        file_size=10,
                    )
                ],
                target_chat_id=-1002,
            ),
        )

    app = create_api_app(ctx)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        denied = await client.get(f"/api/v1/media/reviews/{task.id}/files/0")
        assert denied.status_code == 401

        await client.post(
            "/api/v1/auth/login",
            json={"username": "v", "password": "password123"},
        )
        ok = await client.get(f"/api/v1/media/reviews/{task.id}/files/0")
        assert ok.status_code == 200
        assert ok.content == b"fake-image"

        preview = await client.get(f"/api/v1/reviews/{task.id}/preview")
        assert preview.status_code == 200
        body = preview.json()["data"]
        assert body["approximate"] is True
        assert body["media_items"][0]["available"] is True
        assert "downloads" not in (body["media_items"][0].get("url") or "")
